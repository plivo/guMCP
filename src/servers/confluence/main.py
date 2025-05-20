import json
import logging
import os
import sys
from pathlib import Path

# Add both project root and src directory to Python path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import mcp.types as types
import requests
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.auth.factory import create_auth_client
from src.utils.utils import ToolResponse

SERVICE_NAME = Path(__file__).parent.name
CONFLUENCE_BASE_API_URL = "https://api.atlassian.com/ex/confluence"
API_VERSION = "v2"

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


async def get_credentials(user_id, api_key=None):
    """
    Retrieves the OAuth access token for a specific Confluence user.

    Args:
        user_id (str): The identifier of the user.
        api_key (Optional[str]): Optional API key passed during server creation.

    Returns:
        str: The access token to authenticate with the Confluence API or None if not found.
    """
    auth_client = create_auth_client(api_key=api_key)
    credentials_data = auth_client.get_user_credentials(SERVICE_NAME, user_id)

    if credentials_data:
        return credentials_data.get("access_token")
    return None


async def get_headers(user_id, api_key=None):
    """
    Creates headers needed for Confluence API authentication.

    Args:
        user_id (str): The user identifier.
        api_key (Optional[str]): Optional API key.

    Returns:
        dict: Headers for making Confluence API requests.
    """
    access_token = await get_credentials(user_id, api_key)
    # Use empty string if access_token is None to avoid None errors
    token = access_token or ""
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


async def get_cloud_id(user_id, api_key=None):
    """
    Retrieves the first cloud ID for a user's Confluence instance.
    No validation is performed on the cloud ID.

    Args:
        user_id (str): The user identifier.
        api_key (Optional[str]): Optional API key.

    Returns:
        str: The first available cloud ID for the user or None if not available.
    """
    headers = await get_headers(user_id, api_key)

    # Use the Atlassian API to get accessible resources
    url = "https://api.atlassian.com/oauth/token/accessible-resources"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        logger.error(
            f"Failed to retrieve cloud ID: {response.status_code} - {response.text}"
        )
        return None

    sites = response.json()

    if not sites:
        logger.error("No Confluence sites are accessible with the provided token")
        return None

    # Return the first available cloud ID without any further checks
    return sites[0].get("id")


def create_server(user_id, api_key=None):
    """
    Initializes and configures a Confluence MCP server instance.

    Args:
        user_id (str): The unique user identifier for session context.
        api_key (Optional[str]): Optional API key for user auth context.

    Returns:
        Server: Configured server instance with all Confluence tools registered.
    """
    server = Server("confluence-server")
    server.user_id = user_id
    server.api_key = api_key

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """
        Lists all available tools for interacting with the Confluence API.

        Returns:
            list[types.Tool]: A list of tool metadata with schema definitions.
        """
        logger.info(f"Listing tools for user: {user_id}")
        return [
            types.Tool(
                name="get_cloud_ids",
                description="List all accessible Confluence cloud IDs",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            types.Tool(
                name="list_pages",
                description="List Confluence pages",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "cloud_id": {"type": "string"},
                        "limit": {"type": "integer"},
                        "start": {"type": "integer"},
                    },
                },
            ),
            types.Tool(
                name="get_page",
                description="Retrieve a Confluence page by ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "cloud_id": {"type": "string"},
                        "page_id": {"type": "string"},
                        "body_format": {
                            "type": "string",
                            "enum": ["storage", "atlas_doc_format", "view"],
                            "default": "storage",
                        },
                    },
                    "required": ["page_id"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None):
        """
        Dispatches a tool call to the corresponding Confluence API method.

        Args:
            name (str): The tool name to execute.
            arguments (dict | None): Arguments to pass to the tool.

        Returns:
            list[types.TextContent]: The JSON-formatted result of the API call.
        """
        logger.info(f"User {user_id} calling tool: {name} with args: {arguments}")

        headers = await get_headers(server.user_id, server.api_key)

        if arguments is None:
            arguments = {}

        try:
            if name == "get_cloud_ids":
                url = "https://api.atlassian.com/oauth/token/accessible-resources"
                response = requests.get(url, headers=headers)

                if response.status_code != 200:
                    logger.error(
                        f"Failed to retrieve cloud IDs: {response.status_code} - {response.text}"
                    )
                    result = []  # Empty array as a fallback
                else:
                    result = response.json()

            elif name == "list_pages":
                # Get cloud_id from arguments or retrieve the default one
                cloud_id = arguments.get("cloud_id")
                if not cloud_id:
                    cloud_id = await get_cloud_id(server.user_id, server.api_key)
                    if not cloud_id:
                        return [
                            types.TextContent(
                                type="text",
                                text=json.dumps(
                                    ToolResponse(
                                        success=False,
                                        data=None,
                                        error="Could not retrieve cloud ID",
                                    ),
                                    indent=2,
                                ),
                            )
                        ]

                limit = arguments.get("limit", 25)
                start = arguments.get("start", 0)

                url = (
                    f"{CONFLUENCE_BASE_API_URL}/{cloud_id}/wiki/api/{API_VERSION}/pages"
                )
                params = {"limit": limit, "start": start, "body-format": "storage"}

                response = requests.get(url, params=params, headers=headers)
                if response.status_code != 200:
                    logger.error(
                        f"Confluence API error: {response.status_code} - {response.text}"
                    )
                    result = {"results": []}  # Empty results object as fallback
                else:
                    result = response.json()

            elif name == "get_page":
                # Get page_id from arguments (required)
                page_id = arguments.get("page_id")
                if not page_id:
                    return [
                        types.TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=None,
                                    error="page_id is required",
                                ),
                                indent=2,
                            ),
                        )
                    ]

                # Get cloud_id from arguments or retrieve the default one
                cloud_id = arguments.get("cloud_id")
                if not cloud_id:
                    cloud_id = await get_cloud_id(server.user_id, server.api_key)
                    if not cloud_id:
                        return [
                            types.TextContent(
                                type="text",
                                text=json.dumps(
                                    ToolResponse(
                                        success=False,
                                        data=None,
                                        error="Could not retrieve cloud ID",
                                    ),
                                    indent=2,
                                ),
                            )
                        ]

                body_format = arguments.get("body_format", "storage")

                url = f"{CONFLUENCE_BASE_API_URL}/{cloud_id}/wiki/api/{API_VERSION}/pages/{page_id}"
                params = {"body-format": body_format}

                response = requests.get(url, params=params, headers=headers)
                if response.status_code != 200:
                    logger.error(
                        f"Confluence API error: {response.status_code} - {response.text}"
                    )
                    result = {}  # Empty object as fallback
                else:
                    result = response.json()

            else:
                return [
                    types.TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False, data=None, error=f"Unknown tool: {name}"
                            ),
                            indent=2,
                        ),
                    )
                ]

            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        ToolResponse(success=True, data=result, error=None), indent=2
                    ),
                )
            ]

        except Exception as e:
            logger.error(f"Error calling Confluence API: {e}")
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        ToolResponse(success=False, data=None, error=str(e)), indent=2
                    ),
                )
            ]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """
    Provides initialization options required for registering the server.

    Args:
        server_instance (Server): The guMCP server instance.

    Returns:
        InitializationOptions: The initialization configuration block.
    """
    return InitializationOptions(
        server_name="confluence-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


if __name__ == "__main__":
    print("Confluence Server - OAuth 2.0 (3LO) authentication is required.")
    print("Usage instructions for developers:")
    print("1. Create an OAuth 2.0 app in the Atlassian developer console")
    print("2. Implement the OAuth 2.0 (3LO) flow to get an access token")
    print("3. Store the token using the appropriate auth client")
