import json
import os
import sys
from typing import Iterable, Optional

from src.utils.utils import (
    CustomFields,
    has_create_permission,
    has_edit_permission,
    has_view_permission,
)

# Add both project root and src directory to Python path
# Get the project root directory and add to path
project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import logging
from pathlib import Path

import httpx
from mcp.server import NotificationOptions, Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.models import InitializationOptions
from mcp.types import (
    AnyUrl,
    EmbeddedResource,
    ImageContent,
    Resource,
    TextContent,
    Tool,
)

from src.utils.zendesk.util import (
    authenticate_and_save_credentials,
    get_credentials,
    get_service_config,
)

SERVICE_NAME = Path(__file__).parent.name
SCOPES = [
    "read",
    "write",
]

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


async def make_zendesk_request(
    method, path, access_token=None, subdomain=None, data=None, params=None
):
    """Make a request to the Zendesk API"""
    if not access_token:
        raise ValueError("Zendesk access token is required")
    if not subdomain:
        raise ValueError("Zendesk subdomain is required")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    url = f"https://{subdomain}.zendesk.com/api/v2/{path}"

    async with httpx.AsyncClient() as client:
        if method.lower() == "get":
            response = await client.get(url, headers=headers, params=params)
        elif method.lower() == "post":
            response = await client.post(url, headers=headers, json=data)
        elif method.lower() == "put":
            response = await client.put(url, headers=headers, json=data)
        elif method.lower() == "delete":
            response = await client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        if response.status_code >= 400:
            raise ValueError(
                f"Zendesk API error: {response.status_code} - {response.text}"
            )

        return response.json()


def create_server(user_id, api_key=None):
    """Create a new server instance with optional user context"""
    server = Server("zendesk-server")

    server.user_id = user_id

    async def get_zendesk_client():
        """Get Zendesk access token and subdomain for the current user"""
        # Get access token
        access_token = await get_credentials(user_id, SERVICE_NAME, api_key=api_key)

        # Get service config (contains subdomain)
        config = await get_service_config(user_id, SERVICE_NAME, api_key=api_key)
        subdomain = config.get("custom_subdomain", "")
        custom_fields: CustomFields = config.get("custom_fields", {})

        return access_token, subdomain, custom_fields

    @server.list_resources()
    async def handle_list_resources(
        cursor: Optional[str] = None,
    ) -> list[Resource]:
        """List resources from Zendesk"""
        logger.info(
            f"Listing resources for user: {server.user_id} with cursor: {cursor}"
        )

        access_token, subdomain, custom_fields = await get_zendesk_client()

        resources = []

        # Add ticket views as resources
        views_params = {}
        if cursor:
            views_params["page"] = cursor

        views_data = await make_zendesk_request(
            "get", "views.json", access_token, subdomain, params=views_params
        )

        for view in views_data.get("views", []):
            resources.append(
                Resource(
                    uri=f"zendesk://view/{view['id']}",
                    mimeType="application/json",
                    name=f"View: {view['title']}",
                    description=f"Zendesk ticket view: {view['title']}",
                )
            )

        return resources

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        """Read a resource from Zendesk by URI"""
        logger.info(f"Reading resource: {uri} for user: {server.user_id}")

        access_token, subdomain, custom_fields = await get_zendesk_client()

        uri_str = str(uri)

        if uri_str.startswith("zendesk://view/"):
            # Handle view resource
            view_id = uri_str.replace("zendesk://view/", "")

            view_data = await make_zendesk_request(
                "get", f"views/{view_id}.json", access_token, subdomain
            )

            # Get tickets from this view
            view_tickets = await make_zendesk_request(
                "get", f"views/{view_id}/tickets.json", access_token, subdomain
            )

            # Combine view data with tickets
            combined_data = {
                "view": view_data.get("view", {}),
                "tickets": view_tickets.get("tickets", []),
            }

            formatted_content = json.dumps(combined_data, indent=2)
            return [
                ReadResourceContents(
                    content=formatted_content, mime_type="application/json"
                )
            ]

        raise ValueError(f"Unsupported resource URI: {uri_str}")

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools for Zendesk"""
        logger.info(f"Listing tools for user: {server.user_id}")
        return [
            Tool(
                name="search_tickets",
                description="Search for tickets in Zendesk",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for tickets",
                        },
                        "sort_by": {
                            "type": "string",
                            "description": "Field to sort by (created_at, updated_at, priority, status)",
                        },
                        "sort_order": {
                            "type": "string",
                            "description": "Sort order (asc, desc)",
                        },
                        "per_page": {
                            "type": "integer",
                            "description": "Number of results per page (max 100)",
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="create_ticket",
                description="Create a new ticket in Zendesk",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contact_id": {
                            "type": "string",
                            "description": "ID of the contact",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Subject of the ticket",
                        },
                        "description": {
                            "type": "string",
                            "description": "Detailed description of the ticket",
                        },
                        "priority": {
                            "type": "string",
                            "description": "Priority level of the ticket (low, normal, high, urgent)",
                        },
                        "type": {
                            "type": "string",
                            "description": "Type of the ticket (problem, incident, question, task)",
                        },
                        "status": {
                            "type": "string",
                            "description": "Status of the ticket (new, open, pending, hold, solved, closed)",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags to apply to the ticket",
                        },
                        "custom_fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "ID of the custom field",
                                    },
                                    "value": {
                                        "type": "any",
                                        "description": "Value of the custom field",
                                    },
                                },
                                "required": ["id", "value"],
                            },
                            "description": "Custom fields to set on the ticket",
                        },
                    },
                    "required": [
                        "contact_id",
                        "subject",
                        "description",
                        "priority",
                        "type",
                        "status",
                    ],
                },
            ),
            Tool(
                name="update_ticket",
                description="Update an existing ticket in Zendesk",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID of the ticket to update",
                        },
                        "contact_id": {
                            "type": "string",
                            "description": "ID of the contact",
                        },
                        "subject": {
                            "type": "string",
                            "description": "New subject",
                        },
                        "description": {
                            "type": "string",
                            "description": "New description",
                        },
                        "status": {
                            "type": "string",
                            "description": "New status (new, open, pending, hold, solved, closed)",
                        },
                        "priority": {
                            "type": "string",
                            "description": "New priority (low, normal, high, urgent)",
                        },
                        "type": {
                            "type": "string",
                            "description": "Type of the ticket (problem, incident, question, task)",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tags to replace on the ticket",
                        },
                        "custom_fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "ID of the custom field",
                                    },
                                    "value": {
                                        "type": "any",
                                        "description": "Value of the custom field",
                                    },
                                },
                                "required": ["id", "value"],
                            },
                            "description": "Custom fields to update on the ticket",
                        },
                    },
                    "required": ["id"],
                },
            ),
            Tool(
                name="add_comment",
                description="Add a comment to an existing ticket",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID of the ticket to comment on",
                        },
                        "comment": {
                            "type": "string",
                            "description": "Comment text to add",
                        },
                        "public": {
                            "type": "boolean",
                            "description": "Whether the comment is public or an internal note",
                        },
                    },
                    "required": ["id", "comment"],
                },
            ),
            Tool(
                name="get_ticket_details",
                description="Get detailed information about a specific ticket",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID of the ticket to retrieve",
                        },
                    },
                    "required": ["id"],
                },
            ),
            Tool(
                name="get_recent_tickets",
                description="Get recent tickets for a specific contact",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contact_id": {
                            "type": "string",
                            "description": "ID of the contact",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of tickets to return",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["contact_id"],
                },
            ),
            Tool(
                name="get_recent_tickets_by_email",
                description="Get recent tickets for a user by their email",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "Email of the user",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of tickets to return",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["email"],
                },
            ),
            Tool(
                name="get_recent_tickets_by_phone_number",
                description="Get recent tickets for a user by their phone number",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "phone_number": {
                            "type": "string",
                            "description": "Phone number of the user",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of tickets to return",
                            "default": 10,
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["phone_number"],
                },
            ),
            Tool(
                name="create_user",
                description="Create a new user in Zendesk",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the user",
                        },
                        "email": {
                            "type": "string",
                            "description": "Email of the user",
                        },
                        "phone_number": {
                            "type": "string",
                            "description": "Phone number of the user",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="get_contact_by_email",
                description="Find a contact by their email address",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "Email of the user to find",
                        },
                    },
                    "required": ["email"],
                },
            ),
            Tool(
                name="get_contact_by_phone_number",
                description="Find a contact by their phone number",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "phone_number": {
                            "type": "string",
                            "description": "Phone number of the user to find",
                        },
                    },
                    "required": ["phone_number"],
                },
            ),
            Tool(
                name="get_contact_by_id",
                description="Find a contact by their Zendesk user ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID of the user to find",
                        },
                    },
                    "required": ["id"],
                },
            ),
            Tool(
                name="get_ticket_fields",
                description="Get available ticket fields",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[TextContent | ImageContent | EmbeddedResource]:
        """Handle tool execution requests for Zendesk"""
        logger.info(
            f"User {server.user_id} calling tool: {name} with arguments: {arguments}"
        )

        # Ensure arguments is not None
        if arguments is None:
            arguments = {}

        try:
            access_token, subdomain, custom_fields = await get_zendesk_client()

            if name == "search_tickets":
                if "query" not in arguments:
                    raise ValueError("Missing query parameter")

                search_query = arguments["query"]

                params = {
                    "query": search_query,
                    "sort_by": arguments.get("sort_by", "created_at"),
                    "sort_order": arguments.get("sort_order", "desc"),
                    "per_page": arguments.get("per_page", 10),
                }

                try:
                    result = await make_zendesk_request(
                        "get", "search.json", access_token, subdomain, params=params
                    )
                    results = result.get("results", [])

                    # Filter to just tickets
                    tickets = [r for r in results if r.get("type") == "ticket"]

                    if not tickets:
                        return [
                            TextContent(
                                type="text",
                                text="No tickets found matching your query.",
                            )
                        ]

                    response_data = {
                        "tickets": [
                            {
                                "id": str(ticket.get("id")),
                                "subject": ticket.get("subject"),
                                "description": ticket.get("description", ""),
                                "status": ticket.get("status", ""),
                                "priority": ticket.get("priority", ""),
                                "created_at": ticket.get("created_at"),
                                "updated_at": ticket.get("updated_at"),
                                "tags": ticket.get("tags", []),
                                "url": ticket.get("url", ""),
                            }
                            for ticket in tickets
                        ]
                    }

                    return [
                        TextContent(
                            type="text",
                            text=f"Success: {json.dumps(response_data, indent=2)}",
                        )
                    ]

                except Exception as e:
                    logger.error(f"Error searching tickets: {str(e)}")
                    return [
                        TextContent(
                            type="text",
                            text=f"Failure: Error searching tickets: {str(e)}",
                        )
                    ]

            elif name == "create_ticket":
                required_fields = [
                    "contact_id",
                    "subject",
                    "description",
                    "priority",
                    "type",
                    "status",
                ]
                for field in required_fields:
                    if field not in arguments:
                        raise ValueError(f"Missing required parameter: {field}")

                ticket_data = {
                    "ticket": {
                        "subject": arguments["subject"],
                        "comment": {"body": arguments["description"]},
                        "priority": arguments["priority"],
                        "type": arguments["type"],
                        "status": arguments["status"],
                        "requester_id": arguments["contact_id"],
                    }
                }

                # Add optional fields
                if "tags" in arguments:
                    ticket_data["ticket"]["tags"] = arguments["tags"]

                # Add custom fields if provided, filtering by permission and config
                if "custom_fields" in arguments:
                    # Filter to only include fields with create permission
                    custom_field_data = []
                    for field in arguments["custom_fields"]:
                        if isinstance(field, dict) and "id" in field:
                            field_id = field["id"]
                            if has_create_permission(custom_fields, field_id):
                                custom_field_data.append(field)

                    if custom_field_data:
                        ticket_data["ticket"]["custom_fields"] = custom_field_data

                try:
                    result = await make_zendesk_request(
                        "post",
                        "tickets.json",
                        access_token,
                        subdomain,
                        data=ticket_data,
                    )
                    ticket = result.get("ticket", {})

                    if ticket:
                        # Filter custom fields to only include those with view permission
                        filtered_custom_fields = []
                        raw_custom_fields = ticket.get("custom_fields", [])
                        for field in raw_custom_fields:
                            if (
                                isinstance(field, dict)
                                and "id" in field
                                and "value" in field
                            ):
                                field_id = field["id"]
                                field_value = field["value"]
                                if has_view_permission(custom_fields, field_id):
                                    field_title = field.get("title", "")
                                    filtered_custom_fields.append(
                                        {
                                            "id": field_id,
                                            "value": field_value,
                                            "title": field_title,
                                        }
                                    )

                        response_data = {
                            "id": str(ticket.get("id")),
                            "contact_id": str(ticket.get("requester_id", "")),
                            "subject": ticket.get("subject", ""),
                            "description": ticket.get("description", ""),
                            "status": ticket.get("status", ""),
                            "priority": ticket.get("priority", ""),
                            "type": ticket.get("type", ""),
                            "tags": ticket.get("tags", []),
                            "created_at": ticket.get("created_at", ""),
                            "updated_at": ticket.get("updated_at", ""),
                            "url": f"https://{subdomain}.zendesk.com/agent/tickets/{ticket.get('id')}",
                            "custom_fields": filtered_custom_fields,
                        }

                        return [
                            TextContent(
                                type="text",
                                text=f"Success: {json.dumps(response_data, indent=2)}",
                            )
                        ]
                    else:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: Failed to create ticket: {json.dumps(result, indent=2)}",
                            )
                        ]

                except Exception as e:
                    logger.error(f"Error creating ticket: {str(e)}")
                    return [
                        TextContent(
                            type="text",
                            text=f"Failure: Error creating ticket: {str(e)}",
                        )
                    ]

            elif name == "update_ticket":

                if "id" not in arguments:
                    raise ValueError("Missing required parameter: id")

                ticket_id = arguments["id"]

                # Start with an empty ticket structure
                ticket_data = {"ticket": {}}

                # Add fields that are present
                if "contact_id" in arguments:
                    ticket_data["ticket"]["requester_id"] = arguments["contact_id"]
                if "subject" in arguments:
                    ticket_data["ticket"]["subject"] = arguments["subject"]
                if "description" in arguments:
                    ticket_data["ticket"]["comment"] = {
                        "body": arguments["description"]
                    }
                if "status" in arguments:
                    ticket_data["ticket"]["status"] = arguments["status"]
                if "priority" in arguments:
                    ticket_data["ticket"]["priority"] = arguments["priority"]
                if "type" in arguments:
                    ticket_data["ticket"]["type"] = arguments["type"]
                if "tags" in arguments:
                    ticket_data["ticket"]["tags"] = arguments["tags"]

                # Add custom fields if provided, filtering by permission and config
                if "custom_fields" in arguments:
                    # Filter to only include fields with edit permission
                    custom_field_data = []
                    for field in arguments["custom_fields"]:
                        if isinstance(field, dict) and "id" in field:
                            field_id = int(field["id"])  # Convert id to number
                            if has_edit_permission(custom_fields, field["id"]):
                                field["id"] = field_id  # Update field with numeric id
                                custom_field_data.append(field)

                    if custom_field_data:
                        ticket_data["ticket"]["custom_fields"] = custom_field_data

                if len(ticket_data["ticket"]) <= 0:
                    raise ValueError("At least one field to update must be provided")

                try:
                    result = await make_zendesk_request(
                        "put",
                        f"tickets/{ticket_id}.json",
                        access_token,
                        subdomain,
                        data=ticket_data,
                    )

                    ticket = result.get("ticket", {})

                    if ticket:
                        # Filter custom fields to only include those with view permission
                        filtered_custom_fields = []
                        raw_custom_fields = ticket.get("custom_fields", [])
                        for field in raw_custom_fields:
                            if (
                                isinstance(field, dict)
                                and "id" in field
                                and "value" in field
                            ):
                                field_id = field["id"]
                                field_value = field["value"]
                                if has_view_permission(custom_fields, field_id):
                                    field_title = field.get("title", "")
                                    filtered_custom_fields.append(
                                        {
                                            "id": field_id,
                                            "value": field_value,
                                            "title": field_title,
                                        }
                                    )

                        response_data = {
                            "id": str(ticket.get("id")),
                            "contact_id": str(ticket.get("requester_id", "")),
                            "subject": ticket.get("subject", ""),
                            "description": ticket.get("description", ""),
                            "status": ticket.get("status", ""),
                            "priority": ticket.get("priority", ""),
                            "type": ticket.get("type", ""),
                            "tags": ticket.get("tags", []),
                            "created_at": ticket.get("created_at", ""),
                            "updated_at": ticket.get("updated_at", ""),
                            "url": f"https://{subdomain}.zendesk.com/agent/tickets/{ticket.get('id')}",
                            "custom_fields": filtered_custom_fields,
                        }

                        return [
                            TextContent(
                                type="text",
                                text=f"Success: {json.dumps(response_data, indent=2)}",
                            )
                        ]
                    else:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: Failed to update ticket: {json.dumps(result, indent=2)}",
                            )
                        ]

                except Exception as e:
                    logger.error(f"Error updating ticket: {str(e)}")
                    return [
                        TextContent(
                            type="text",
                            text=f"Failure: Error updating ticket: {str(e)}",
                        )
                    ]

            elif name == "add_comment":
                required_fields = ["id", "comment"]
                for field in required_fields:
                    if field not in arguments:
                        raise ValueError(f"Missing required parameter: {field}")

                ticket_id = arguments["id"]
                comment_text = arguments["comment"]
                is_public = arguments.get("public", True)

                ticket_data = {
                    "ticket": {"comment": {"body": comment_text, "public": is_public}}
                }

                try:
                    result = await make_zendesk_request(
                        "put",
                        f"tickets/{ticket_id}.json",
                        access_token,
                        subdomain,
                        data=ticket_data,
                    )

                    ticket = result.get("ticket", {})

                    if ticket:
                        # Filter custom fields to only include those with view permission
                        filtered_custom_fields = []
                        raw_custom_fields = ticket.get("custom_fields", [])
                        for field in raw_custom_fields:
                            if (
                                isinstance(field, dict)
                                and "id" in field
                                and "value" in field
                            ):
                                field_id = field["id"]
                                field_value = field["value"]
                                if has_view_permission(custom_fields, field_id):
                                    field_title = field.get("title", "")
                                    filtered_custom_fields.append(
                                        {
                                            "id": field_id,
                                            "value": field_value,
                                            "title": field_title,
                                        }
                                    )

                        # Return TicketDetails structure with comment info and custom fields
                        response_data = {
                            "id": str(ticket.get("id")),
                            "contact_id": str(ticket.get("requester_id", "")),
                            "subject": ticket.get("subject", ""),
                            "status": ticket.get("status", ""),
                            "priority": ticket.get("priority", ""),
                            "type": ticket.get("type", ""),
                            "updated_at": ticket.get("updated_at", ""),
                            "url": f"https://{subdomain}.zendesk.com/agent/tickets/{ticket.get('id')}",
                            "custom_fields": filtered_custom_fields,
                        }

                        return [
                            TextContent(
                                type="text",
                                text=f"Success: {json.dumps(response_data, indent=2)}",
                            )
                        ]
                    else:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: Failed to add comment: {json.dumps(result, indent=2)}",
                            )
                        ]

                except Exception as e:
                    logger.error(f"Error adding comment: {str(e)}")
                    return [
                        TextContent(
                            type="text", text=f"Failure: Error adding comment: {str(e)}"
                        )
                    ]

            elif name == "get_ticket_details":
                if "id" not in arguments:
                    raise ValueError("Missing required parameter: id")

                ticket_id = arguments["id"]

                try:
                    result = await make_zendesk_request(
                        "get", f"tickets/{ticket_id}.json", access_token, subdomain
                    )

                    ticket = result.get("ticket", {})

                    if not ticket:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: No ticket found with ID: {ticket_id}",
                            )
                        ]

                    # Filter custom fields to only include those with view permission
                    filtered_custom_fields = []
                    raw_custom_fields = ticket.get("custom_fields", [])
                    for field in raw_custom_fields:
                        if (
                            isinstance(field, dict)
                            and "id" in field
                            and "value" in field
                        ):
                            field_id = field["id"]
                            field_value = field["value"]
                            if has_view_permission(custom_fields, field_id):
                                field_title = field.get("title", "")
                                filtered_custom_fields.append(
                                    {
                                        "id": field_id,
                                        "value": field_value,
                                        "title": field_title,
                                    }
                                )

                    response_data = {
                        "id": str(ticket.get("id")),
                        "contact_id": str(ticket.get("requester_id", "")),
                        "subject": ticket.get("subject", ""),
                        "description": ticket.get("description", ""),
                        "status": ticket.get("status", ""),
                        "priority": ticket.get("priority", ""),
                        "type": ticket.get("type", ""),
                        "tags": ticket.get("tags", []),
                        "created_at": ticket.get("created_at", ""),
                        "updated_at": ticket.get("updated_at", ""),
                        "url": f"https://{subdomain}.zendesk.com/agent/tickets/{ticket.get('id')}",
                        "custom_fields": filtered_custom_fields,
                    }

                    return [
                        TextContent(
                            type="text",
                            text=f"Success: {json.dumps(response_data, indent=2)}",
                        )
                    ]

                except Exception as e:
                    logger.error(f"Error getting ticket details: {str(e)}")
                    return [
                        TextContent(
                            type="text",
                            text=f"Failure: Error getting ticket details: {str(e)}",
                        )
                    ]

            elif name == "get_recent_tickets":
                if "contact_id" not in arguments:
                    raise ValueError("Missing required parameter: contact_id")

                contact_id = arguments["contact_id"]
                limit = arguments.get("limit", 10)

                try:
                    result = await make_zendesk_request(
                        "get",
                        f"users/{contact_id}/tickets/requested.json?sort_by=updated_at&sort_order=desc&per_page={limit}",
                        access_token,
                        subdomain,
                    )

                    tickets = result.get("tickets", [])

                    if not tickets:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: No recent tickets found for contact ID: {contact_id}",
                            )
                        ]

                    # Filter custom fields to only include those with view permission
                    filtered_custom_fields = []
                    ticket_list = []

                    for ticket in tickets:
                        # Process custom fields for this ticket
                        filtered_custom_fields = []
                        raw_custom_fields = ticket.get("custom_fields", [])
                        for field in raw_custom_fields:
                            if (
                                isinstance(field, dict)
                                and "id" in field
                                and "value" in field
                            ):
                                field_id = field["id"]
                                field_value = field["value"]
                                if has_view_permission(custom_fields, field_id):
                                    field_title = field.get("title", "")
                                    filtered_custom_fields.append(
                                        {
                                            "id": field_id,
                                            "value": field_value,
                                            "title": field_title,
                                        }
                                    )

                        ticket_data = {
                            "id": str(ticket.get("id")),
                            "contact_id": contact_id,
                            "subject": ticket.get("subject", ""),
                            "description": ticket.get("description", ""),
                            "status": ticket.get("status", ""),
                            "priority": ticket.get("priority", ""),
                            "type": ticket.get("type", ""),
                            "created_at": ticket.get("created_at", ""),
                            "updated_at": ticket.get("updated_at", ""),
                            "tags": ticket.get("tags", []),
                            "url": ticket.get("url", ""),
                            "custom_fields": filtered_custom_fields,
                        }

                        ticket_list.append(ticket_data)

                    response_data = {"tickets": ticket_list}

                    return [
                        TextContent(
                            type="text",
                            text=f"Success: {json.dumps(response_data, indent=2)}",
                        )
                    ]

                except Exception as e:
                    logger.error(f"Error getting recent tickets: {str(e)}")
                    return [
                        TextContent(
                            type="text",
                            text=f"Failure: Error getting recent tickets: {str(e)}",
                        )
                    ]

            elif name == "get_recent_tickets_by_email":
                if "email" not in arguments:
                    raise ValueError("Missing required parameter: email")

                email = arguments["email"]
                limit = arguments.get("limit", 10)

                try:
                    # First, get the user ID by email
                    user_search_result = await make_zendesk_request(
                        "get",
                        f"users/search.json?query={email}",
                        access_token,
                        subdomain,
                    )

                    users = user_search_result.get("users", [])

                    if not users:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: No user found with email: {email}",
                            )
                        ]

                    # Use the first matching user
                    user_id = users[0]["id"]

                    # Get tickets for this user
                    result = await make_zendesk_request(
                        "get",
                        f"users/{user_id}/tickets/requested.json?sort_by=updated_at&sort_order=desc&per_page={limit}",
                        access_token,
                        subdomain,
                    )

                    tickets = result.get("tickets", [])

                    if not tickets:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: No recent tickets found for email: {email}",
                            )
                        ]

                    # Filter custom fields to only include those with view permission
                    ticket_list = []

                    for ticket in tickets:
                        # Process custom fields for this ticket
                        filtered_custom_fields = []
                        raw_custom_fields = ticket.get("custom_fields", [])
                        for field in raw_custom_fields:
                            if (
                                isinstance(field, dict)
                                and "id" in field
                                and "value" in field
                            ):
                                field_id = field["id"]
                                field_value = field["value"]
                                if has_view_permission(custom_fields, field_id):
                                    field_title = field.get("title", "")
                                    filtered_custom_fields.append(
                                        {
                                            "id": field_id,
                                            "value": field_value,
                                            "title": field_title,
                                        }
                                    )

                        ticket_data = {
                            "id": str(ticket.get("id")),
                            "contact_id": str(user_id),
                            "subject": ticket.get("subject", ""),
                            "description": ticket.get("description", ""),
                            "status": ticket.get("status", ""),
                            "priority": ticket.get("priority", ""),
                            "type": ticket.get("type", ""),
                            "created_at": ticket.get("created_at", ""),
                            "updated_at": ticket.get("updated_at", ""),
                            "tags": ticket.get("tags", []),
                            "url": ticket.get("url", ""),
                            "custom_fields": filtered_custom_fields,
                        }

                        ticket_list.append(ticket_data)

                    response_data = {"tickets": ticket_list}

                    return [
                        TextContent(
                            type="text",
                            text=f"Success: {json.dumps(response_data, indent=2)}",
                        )
                    ]

                except Exception as e:
                    logger.error(f"Error getting recent tickets by email: {str(e)}")
                    return [
                        TextContent(
                            type="text",
                            text=f"Failure: Error getting recent tickets by email: {str(e)}",
                        )
                    ]

            elif name == "get_recent_tickets_by_phone_number":
                if "phone_number" not in arguments:
                    raise ValueError("Missing required parameter: phone_number")

                phone_number = arguments["phone_number"]
                limit = arguments.get("limit", 10)

                try:
                    # First, get the user ID by phone number
                    user_search_result = await make_zendesk_request(
                        "get",
                        f"users/search.json?query={phone_number}",
                        access_token,
                        subdomain,
                    )

                    users = user_search_result.get("users", [])

                    if not users:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: No user found with phone number: {phone_number}",
                            )
                        ]

                    # Use the first matching user
                    user_id = users[0]["id"]

                    # Get tickets for this user
                    result = await make_zendesk_request(
                        "get",
                        f"users/{user_id}/tickets/requested.json?sort_by=updated_at&sort_order=desc&per_page={limit}",
                        access_token,
                        subdomain,
                    )

                    tickets = result.get("tickets", [])

                    if not tickets:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: No recent tickets found for phone number: {phone_number}",
                            )
                        ]

                    # Filter custom fields to only include those with view permission
                    ticket_list = []

                    for ticket in tickets:
                        # Process custom fields for this ticket
                        filtered_custom_fields = []
                        raw_custom_fields = ticket.get("custom_fields", [])
                        for field in raw_custom_fields:
                            if (
                                isinstance(field, dict)
                                and "id" in field
                                and "value" in field
                            ):
                                field_id = field["id"]
                                field_value = field["value"]
                                if has_view_permission(custom_fields, field_id):
                                    field_title = field.get("title", "")
                                    filtered_custom_fields.append(
                                        {
                                            "id": field_id,
                                            "value": field_value,
                                            "title": field_title,
                                        }
                                    )

                        ticket_data = {
                            "id": str(ticket.get("id")),
                            "contact_id": str(user_id),
                            "subject": ticket.get("subject", ""),
                            "description": ticket.get("description", ""),
                            "status": ticket.get("status", ""),
                            "priority": ticket.get("priority", ""),
                            "type": ticket.get("type", ""),
                            "created_at": ticket.get("created_at", ""),
                            "updated_at": ticket.get("updated_at", ""),
                            "tags": ticket.get("tags", []),
                            "url": ticket.get("url", ""),
                            "custom_fields": filtered_custom_fields,
                        }

                        ticket_list.append(ticket_data)

                    response_data = {"tickets": ticket_list}

                    return [
                        TextContent(
                            type="text",
                            text=f"Success: {json.dumps(response_data, indent=2)}",
                        )
                    ]

                except Exception as e:
                    logger.error(
                        f"Error getting recent tickets by phone number: {str(e)}"
                    )
                    return [
                        TextContent(
                            type="text",
                            text=f"Failure: Error getting recent tickets by phone number: {str(e)}",
                        )
                    ]

            elif name == "create_user":
                if "name" not in arguments:
                    raise ValueError("Missing required parameter: name")

                # Build user data
                user_data = {
                    "user": {
                        "name": arguments["name"],
                        "role": "end-user",
                    }
                }

                # Add optional fields
                if "email" in arguments:
                    user_data["user"]["email"] = arguments["email"]
                if "phone_number" in arguments:
                    user_data["user"]["phone"] = arguments["phone_number"]

                try:
                    result = await make_zendesk_request(
                        "post", "users.json", access_token, subdomain, data=user_data
                    )

                    user = result.get("user", {})

                    if user:
                        response_data = {
                            "id": str(user.get("id")),
                            "name": user.get("name", ""),
                            "email": user.get("email", ""),
                            "phone_number": user.get("phone", ""),
                        }

                        return [
                            TextContent(
                                type="text",
                                text=f"Success: {json.dumps(response_data, indent=2)}",
                            )
                        ]
                    else:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: Failed to create user: {json.dumps(result, indent=2)}",
                            )
                        ]

                except Exception as e:
                    logger.error(f"Error creating user: {str(e)}")
                    return [
                        TextContent(
                            type="text", text=f"Failure: Error creating user: {str(e)}"
                        )
                    ]

            elif name == "get_contact_by_email":
                if "email" not in arguments:
                    raise ValueError("Missing required parameter: email")

                email = arguments["email"]

                try:
                    result = await make_zendesk_request(
                        "get",
                        f"users/search.json?query={email}",
                        access_token,
                        subdomain,
                    )

                    users = result.get("users", [])

                    if not users:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: No user found with email: {email}",
                            )
                        ]

                    # Use the first matching user
                    user = users[0]

                    response_data = {
                        "id": str(user.get("id")),
                        "name": user.get("name", ""),
                        "email": user.get("email", ""),
                        "phone_number": user.get("phone", ""),
                    }

                    return [
                        TextContent(
                            type="text",
                            text=f"Success: {json.dumps(response_data, indent=2)}",
                        )
                    ]

                except Exception as e:
                    logger.error(f"Error getting contact by email: {str(e)}")
                    return [
                        TextContent(
                            type="text",
                            text=f"Failure: Error getting contact by email: {str(e)}",
                        )
                    ]

            elif name == "get_contact_by_phone_number":
                if "phone_number" not in arguments:
                    raise ValueError("Missing required parameter: phone_number")

                phone_number = arguments["phone_number"]

                try:
                    result = await make_zendesk_request(
                        "get",
                        f"users/search.json?query={phone_number}",
                        access_token,
                        subdomain,
                    )

                    users = result.get("users", [])

                    if not users:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: No user found with phone number: {phone_number}",
                            )
                        ]

                    # Use the first matching user
                    user = users[0]

                    response_data = {
                        "id": str(user.get("id")),
                        "name": user.get("name", ""),
                        "email": user.get("email", ""),
                        "phone_number": user.get("phone", ""),
                    }

                    return [
                        TextContent(
                            type="text",
                            text=f"Success: {json.dumps(response_data, indent=2)}",
                        )
                    ]

                except Exception as e:
                    logger.error(f"Error getting contact by phone number: {str(e)}")
                    return [
                        TextContent(
                            type="text",
                            text=f"Failure: Error getting contact by phone number: {str(e)}",
                        )
                    ]

            elif name == "get_contact_by_id":
                if "id" not in arguments:
                    raise ValueError("Missing required parameter: id")

                user_id = arguments["id"]

                try:
                    result = await make_zendesk_request(
                        "get", f"users/{user_id}.json", access_token, subdomain
                    )

                    user = result.get("user", {})

                    if not user:
                        return [
                            TextContent(
                                type="text",
                                text=f"Failure: No user found with ID: {user_id}",
                            )
                        ]

                    response_data = {
                        "id": str(user.get("id")),
                        "name": user.get("name", ""),
                        "email": user.get("email", ""),
                        "phone_number": user.get("phone", ""),
                    }

                    return [
                        TextContent(
                            type="text",
                            text=f"Success: {json.dumps(response_data, indent=2)}",
                        )
                    ]

                except Exception as e:
                    logger.error(f"Error getting contact by ID: {str(e)}")
                    return [
                        TextContent(
                            type="text",
                            text=f"Failure: Error getting contact by ID: {str(e)}",
                        )
                    ]

            elif name == "get_ticket_fields":
                try:
                    # Get all ticket fields from Zendesk
                    result = await make_zendesk_request(
                        "get", "ticket_fields.json", access_token, subdomain
                    )

                    ticket_fields = result.get("ticket_fields", [])

                    if not ticket_fields:
                        return [
                            TextContent(
                                type="text",
                                text="Failure: No ticket fields found.",
                            )
                        ]

                    # Filter to include only custom fields that are active, in the config, and have view permission
                    filtered_custom_fields = []
                    for field in ticket_fields:
                        if isinstance(field, dict) and "id" in field:
                            field_id = field["id"]
                            # Include field if it's active, removable, and has view permission
                            if (
                                field.get("active", False)
                                and field.get("removable", False)
                                and has_view_permission(custom_fields, field_id)
                            ):
                                # Add permission info
                                field_data = {
                                    "id": field_id,
                                    "title": field.get("title", ""),
                                    "type": field.get("type", ""),
                                    "description": field.get("description", ""),
                                    "required": field.get("required", False),
                                    "options": field.get("custom_field_options", []),
                                }

                                # Add permission info if field is in config
                                if str(field_id) in custom_fields:
                                    field_config = custom_fields[str(field_id)]
                                    field_data["can_view"] = field_config.get(
                                        "view", False
                                    )
                                    field_data["can_edit"] = field_config.get(
                                        "edit", False
                                    )
                                    field_data["can_create"] = field_config.get(
                                        "create", False
                                    )

                                filtered_custom_fields.append(field_data)

                    response_data = {"custom_fields": filtered_custom_fields}

                    return [
                        TextContent(
                            type="text",
                            text=f"Success: {json.dumps(response_data, indent=2)}",
                        )
                    ]

                except Exception as e:
                    logger.error(f"Error getting ticket fields: {str(e)}")
                    return [
                        TextContent(
                            type="text",
                            text=f"Failure: Error getting ticket fields: {str(e)}",
                        )
                    ]

            raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            logger.error(f"Error executing tool {name}: {str(e)}")
            return [TextContent(type="text", text=f"Failure: {str(e)}")]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get the initialization options for the server"""
    return InitializationOptions(
        server_name="zendesk-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


# Main handler allows users to auth
if __name__ == "__main__":
    if sys.argv[1].lower() == "auth":
        user_id = "local"
        # Run authentication flow
        authenticate_and_save_credentials(user_id, SERVICE_NAME, SCOPES)
    else:
        print("Usage:")
        print("  python main.py auth - Run authentication flow for a user")
        print("Note: To run the server normally, use the guMCP server framework.")
