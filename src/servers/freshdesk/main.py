import json
import logging
import os
import sys
from pathlib import Path

import requests

# Add both project root and src directory to Python path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.auth.factory import create_auth_client
from src.utils.utils import ToolResponse

SERVICE_NAME = Path(__file__).parent.name

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


async def get_credentials(user_id, api_key_override=None):
    """
    Retrieves the API key and custom subdomain for a specific Freshdesk user.
    The custom subdomain is always fetched from stored credentials.
    The API key can be overridden by api_key_override.

    Args:
        user_id (str): The identifier of the user.
        api_key_override (Optional[str]): Optional API key to override the stored one.

    Returns:
        dict: A dictionary containing the API key and custom_subdomain.

    Raises:
        ValueError: If credentials (API key or custom subdomain) are missing or invalid.
    """
    auth_client = create_auth_client()
    credentials_data = auth_client.get_user_credentials(SERVICE_NAME, user_id)

    def handle_missing(reason=""):
        err = f"Freshdesk credentials not found for user {user_id}. {reason}".strip()
        if os.environ.get("ENVIRONMENT", "local") == "local":
            err += " Please ensure API key and custom subdomain are configured via auth flow."
        logger.error(err)
        raise ValueError(err)

    if not credentials_data:
        handle_missing("No credentials data stored.")

    final_api_key = api_key_override or credentials_data.get("api_key")
    custom_subdomain = credentials_data.get("custom_subdomain")

    if not final_api_key:
        handle_missing("API key missing (neither override nor stored).")
    if not custom_subdomain:
        handle_missing("Custom subdomain missing from stored credentials.")

    return {"api_key": final_api_key, "custom_subdomain": custom_subdomain}


class FreshdeskClient:
    """A client for interacting with the Freshdesk API."""

    def __init__(self, custom_subdomain, api_key):
        """
        Initialize the Freshdesk client.

        Args:
            custom_subdomain (str): The Freshdesk custom subdomain (e.g., 'your-company').
            api_key (str): The API key for authentication.
        """
        self.custom_subdomain = custom_subdomain
        self.api_key = api_key
        self.base_url = f"https://{custom_subdomain}.freshdesk.com"
        self.auth = (
            api_key,
            "X",
        )  # Freshdesk uses API key as username and X as password
        self.headers = {
            "Content-Type": "application/json",
        }

    async def request(self, method, endpoint, data=None, params=None):
        """
        Make a request to the Freshdesk API.

        Args:
            method (str): HTTP method (GET, POST, PUT, DELETE).
            endpoint (str): API endpoint path.
            data (dict, optional): Request body for POST/PUT requests.
            params (dict, optional): Query parameters.

        Returns:
            dict: Response data.

        Raises:
            Exception: If the API request fails.
        """
        url = f"{self.base_url}/api/v2/{endpoint.lstrip('/')}"

        try:
            response = requests.request(
                method=method,
                url=url,
                auth=self.auth,
                headers=self.headers,
                json=data if data else None,
                params=params,
            )

            response.raise_for_status()

            if response.status_code == 204:  # No content
                return {"status": "success"}

            return response.json()
        except requests.exceptions.RequestException as e:
            error_msg = f"Freshdesk API error: {str(e)}"
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_details = e.response.json()
                    error_msg = f"Freshdesk API error: {error_details}"
                except ValueError:
                    error_msg = f"Freshdesk API error: {e.response.text}"

            logger.error(error_msg)
            raise Exception(error_msg)

    # Solutions API methods
    async def list_solution_categories(self):
        """List all solution categories."""
        return await self.request("GET", "solutions/categories")

    async def get_solution_category(self, category_id):
        """Get a specific solution category."""
        return await self.request("GET", f"solutions/categories/{category_id}")

    async def create_solution_category(self, data):
        """Create a new solution category."""
        return await self.request("POST", "solutions/categories", data=data)

    async def update_solution_category(self, category_id, data):
        """Update a solution category."""
        return await self.request(
            "PUT", f"solutions/categories/{category_id}", data=data
        )

    async def delete_solution_category(self, category_id):
        """Delete a solution category."""
        return await self.request("DELETE", f"solutions/categories/{category_id}")

    async def list_solution_folders(self, category_id):
        """List all solution folders in a category."""
        return await self.request("GET", f"solutions/categories/{category_id}/folders")

    async def get_solution_folder(self, category_id, folder_id):
        """Get a specific solution folder."""
        return await self.request(
            "GET", f"solutions/categories/{category_id}/folders/{folder_id}"
        )

    async def create_solution_folder(self, category_id, data):
        """Create a new solution folder in a category."""
        return await self.request(
            "POST", f"solutions/categories/{category_id}/folders", data=data
        )

    async def update_solution_folder(self, category_id, folder_id, data):
        """Update a solution folder."""
        return await self.request(
            "PUT", f"solutions/categories/{category_id}/folders/{folder_id}", data=data
        )

    async def delete_solution_folder(self, category_id, folder_id):
        """Delete a solution folder."""
        return await self.request(
            "DELETE", f"solutions/categories/{category_id}/folders/{folder_id}"
        )

    async def list_solution_articles(self, folder_id):
        """List all solution articles in a folder."""
        return await self.request("GET", f"solutions/folders/{folder_id}/articles")

    async def get_solution_article(self, article_id):
        """Get a specific solution article."""
        return await self.request("GET", f"solutions/articles/{article_id}")

    async def create_solution_article(self, category_id, folder_id, data):
        """Create a new solution article in a folder."""
        return await self.request(
            "POST",
            f"solutions/categories/{category_id}/folders/{folder_id}/articles",
            data=data,
        )

    async def update_solution_article(self, category_id, folder_id, article_id, data):
        """Update a solution article."""
        return await self.request(
            "PUT",
            f"solutions/categories/{category_id}/folders/{folder_id}/articles/{article_id}",
            data=data,
        )

    async def delete_solution_article(self, category_id, folder_id, article_id):
        """Delete a solution article."""
        return await self.request(
            "DELETE",
            f"solutions/categories/{category_id}/folders/{folder_id}/articles/{article_id}",
        )

    async def search_solution_articles(self, query):
        """Search for solution articles."""
        return await self.request("GET", "search/solutions", params={"term": query})


async def create_freshdesk_client(user_id, api_key=None):
    """
    Creates an authorized Freshdesk client instance.

    Args:
        user_id (str): The user identifier.
        api_key (Optional[str]): Optional API key to override the one in credentials.

    Returns:
        FreshdeskClient: An authenticated Freshdesk client object.
    """
    credentials = await get_credentials(user_id, api_key)
    return FreshdeskClient(credentials["custom_subdomain"], credentials["api_key"])


def create_server(user_id, api_key=None):
    """
    Initializes and configures a Freshdesk MCP server instance.

    Args:
        user_id (str): The unique user identifier for session context.
        api_key (Optional[str]): Optional API key for user auth context.

    Returns:
        Server: Configured server instance with all Freshdesk tools registered.
    """
    server = Server("freshdesk-server")
    server.user_id = user_id
    server.api_key = api_key

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """
        Lists all available tools for interacting with the Freshdesk Solutions API.

        Returns:
            list[types.Tool]: A list of tool metadata with schema definitions.
        """
        logger.info(f"Listing tools for user: {user_id}")
        return [
            # Solution Categories
            types.Tool(
                name="list_solution_categories",
                description="List all solution categories in the knowledge base",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="get_solution_category",
                description="Get details of a specific solution category by ID",
                inputSchema={
                    "type": "object",
                    "properties": {"category_id": {"type": "number"}},
                    "required": ["category_id"],
                },
            ),
            types.Tool(
                name="create_solution_category",
                description="Create a new solution category in the knowledge base",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "visible_in_portals": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                    },
                    "required": ["name"],
                },
            ),
            types.Tool(
                name="update_solution_category",
                description="Update an existing solution category",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category_id": {"type": "number"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "visible_in_portals": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                    },
                    "required": ["category_id"],
                },
            ),
            types.Tool(
                name="delete_solution_category",
                description="Delete a solution category",
                inputSchema={
                    "type": "object",
                    "properties": {"category_id": {"type": "number"}},
                    "required": ["category_id"],
                },
            ),
            # Solution Folders
            types.Tool(
                name="list_solution_folders",
                description="List all folders in a solution category",
                inputSchema={
                    "type": "object",
                    "properties": {"category_id": {"type": "number"}},
                    "required": ["category_id"],
                },
            ),
            types.Tool(
                name="get_solution_folder",
                description="Get details of a specific solution folder",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category_id": {"type": "number"},
                        "folder_id": {"type": "number"},
                    },
                    "required": ["category_id", "folder_id"],
                },
            ),
            types.Tool(
                name="create_solution_folder",
                description="Create a new folder in a solution category",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category_id": {"type": "number"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "visibility": {"type": "number", "enum": [1, 2, 3, 4]},
                        "visible_in_portals": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                    },
                    "required": ["category_id", "name"],
                },
            ),
            types.Tool(
                name="update_solution_folder",
                description="Update an existing solution folder",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category_id": {"type": "number"},
                        "folder_id": {"type": "number"},
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "visibility": {"type": "number", "enum": [1, 2, 3, 4]},
                        "visible_in_portals": {
                            "type": "array",
                            "items": {"type": "number"},
                        },
                    },
                    "required": ["category_id", "folder_id"],
                },
            ),
            types.Tool(
                name="delete_solution_folder",
                description="Delete a solution folder",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category_id": {"type": "number"},
                        "folder_id": {"type": "number"},
                    },
                    "required": ["category_id", "folder_id"],
                },
            ),
            # Solution Articles
            types.Tool(
                name="list_solution_articles",
                description="List all articles in a solution folder",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folder_id": {"type": "number"},
                    },
                    "required": ["folder_id"],
                },
            ),
            types.Tool(
                name="get_solution_article",
                description="Get details of a specific solution article",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "article_id": {"type": "number"},
                    },
                    "required": ["article_id"],
                },
            ),
            types.Tool(
                name="create_solution_article",
                description="Create a new article in a solution folder",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category_id": {"type": "number"},
                        "folder_id": {"type": "number"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "status": {"type": "number", "enum": [1, 2]},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["category_id", "folder_id", "title", "description"],
                },
            ),
            types.Tool(
                name="update_solution_article",
                description="Update an existing solution article",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category_id": {"type": "number"},
                        "folder_id": {"type": "number"},
                        "article_id": {"type": "number"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "status": {"type": "number", "enum": [1, 2]},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["category_id", "folder_id", "article_id"],
                },
            ),
            types.Tool(
                name="delete_solution_article",
                description="Delete a solution article",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category_id": {"type": "number"},
                        "folder_id": {"type": "number"},
                        "article_id": {"type": "number"},
                    },
                    "required": ["category_id", "folder_id", "article_id"],
                },
            ),
            types.Tool(
                name="search_solution_articles",
                description="Search for solution articles by keyword",
                inputSchema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None):
        """
        Dispatches a tool call to the corresponding Freshdesk API method.

        Args:
            name (str): The tool name to execute.
            arguments (dict | None): Arguments to pass to the tool.

        Returns:
            list[types.TextContent]: The JSON-formatted result of the API call.

        Raises:
            ValueError: If an unknown tool name is provided.
        """
        logger.info(f"User {user_id} calling tool: {name} with args: {arguments}")

        freshdesk = await create_freshdesk_client(server.user_id, server.api_key)

        if arguments is None:
            arguments = {}

        try:
            # Solution Categories
            if name == "list_solution_categories":
                result = await freshdesk.list_solution_categories()
            elif name == "get_solution_category":
                result = await freshdesk.get_solution_category(arguments["category_id"])
            elif name == "create_solution_category":
                category_data = {
                    "name": arguments["name"],
                    "description": arguments.get("description", ""),
                    "visible_in_portals": arguments.get("visible_in_portals", []),
                }
                result = await freshdesk.create_solution_category(category_data)
            elif name == "update_solution_category":
                category_id = arguments.pop("category_id")
                result = await freshdesk.update_solution_category(
                    category_id, arguments
                )
            elif name == "delete_solution_category":
                result = await freshdesk.delete_solution_category(
                    arguments["category_id"]
                )

            # Solution Folders
            elif name == "list_solution_folders":
                result = await freshdesk.list_solution_folders(arguments["category_id"])
            elif name == "get_solution_folder":
                result = await freshdesk.get_solution_folder(
                    arguments["category_id"], arguments["folder_id"]
                )
            elif name == "create_solution_folder":
                category_id = arguments.pop("category_id")
                result = await freshdesk.create_solution_folder(category_id, arguments)
            elif name == "update_solution_folder":
                category_id = arguments.pop("category_id")
                folder_id = arguments.pop("folder_id")
                result = await freshdesk.update_solution_folder(
                    category_id, folder_id, arguments
                )
            elif name == "delete_solution_folder":
                result = await freshdesk.delete_solution_folder(
                    arguments["category_id"], arguments["folder_id"]
                )

            # Solution Articles
            elif name == "list_solution_articles":
                result = await freshdesk.list_solution_articles(arguments["folder_id"])
            elif name == "get_solution_article":
                result = await freshdesk.get_solution_article(arguments["article_id"])
            elif name == "create_solution_article":
                category_id = arguments.pop("category_id")
                folder_id = arguments.pop("folder_id")
                result = await freshdesk.create_solution_article(
                    category_id, folder_id, arguments
                )
            elif name == "update_solution_article":
                category_id = arguments.pop("category_id")
                folder_id = arguments.pop("folder_id")
                article_id = arguments.pop("article_id")
                result = await freshdesk.update_solution_article(
                    category_id, folder_id, article_id, arguments
                )
            elif name == "delete_solution_article":
                result = await freshdesk.delete_solution_article(
                    arguments["category_id"],
                    arguments["folder_id"],
                    arguments["article_id"],
                )
            elif name == "search_solution_articles":
                result = await freshdesk.search_solution_articles(arguments["query"])
            else:
                raise ValueError(f"Unknown tool: {name}")

            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(
                        ToolResponse(success=True, data=result, error=None), indent=2
                    ),
                )
            ]

        except Exception as e:
            logger.error(f"Error calling Freshdesk API: {e}")
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
        server_name="freshdesk-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == "auth":
        user_id_input = sys.argv[2] if len(sys.argv) > 2 else "local"
        api_key_input = input("Enter your Freshdesk API key: ")
        custom_subdomain_input = input(
            "Enter your Freshdesk custom subdomain (e.g., your-company): "
        )

        auth_client = create_auth_client()
        auth_client.save_user_credentials(
            SERVICE_NAME,
            user_id_input,
            {"api_key": api_key_input, "custom_subdomain": custom_subdomain_input},
        )
        print(
            f"Freshdesk credentials (API key and custom subdomain) saved for user {user_id_input}"
        )
    else:
        print("Usage:")
        print(
            "  python main.py auth [user_id] - Save Freshdesk API credentials (key and custom subdomain) for a user"
        )
