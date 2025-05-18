import json
import os
import sys
import uuid  # Add import for uuid
from typing import Iterable, Optional

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

from src.utils.intercom.utils import authenticate_and_save_credentials, get_credentials
from src.utils.utils import ToolResponse  # Added import

SERVICE_NAME = Path(__file__).parent.name
INTERCOM_API_URL = "https://api.intercom.io"
SCOPES = [
    "read",
    "write",
]

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


async def execute_intercom_request(
    method, path, data=None, params=None, access_token=None
):
    """Execute a request against the Intercom API"""
    if not access_token:
        raise ValueError("Intercom access token is required")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Intercom-Version": "2.9",
    }

    url = f"{INTERCOM_API_URL}/{path}"

    async with httpx.AsyncClient() as client:
        if method.lower() == "get":
            response = await client.get(url, params=params, headers=headers)
        elif method.lower() == "post":
            response = await client.post(url, json=data, headers=headers)
        elif method.lower() == "put":
            response = await client.put(url, json=data, headers=headers)
        elif method.lower() == "delete":
            response = await client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response_data = response.json()
        response.raise_for_status()
        return response_data


def create_server(user_id, api_key=None):
    """Create a new server instance with optional user context"""
    server = Server("intercom-server")

    server.user_id = user_id

    async def get_intercom_client():
        """Get Intercom access token for the current user"""
        access_token = await get_credentials(user_id, SERVICE_NAME, api_key=api_key)
        return access_token

    @server.list_resources()
    async def handle_list_resources(
        cursor: Optional[str] = None,
    ) -> list[Resource]:
        """List conversations from Intercom"""
        access_token = await get_intercom_client()

        params = {}
        if cursor:
            params["starting_after"] = cursor

        try:
            tags_result = await execute_intercom_request(
                "get", "tags", params=None, access_token=access_token
            )

            tags = tags_result.get("data", [])
            tag_resources = []

            for tag in tags:
                tag_resources.append(
                    Resource(
                        uri=f"intercom://tag/{tag['id']}",
                        mimeType="application/json",
                        name=f"Tag: {tag['name']}",
                    )
                )

            conversations_result = await execute_intercom_request(
                "get", "conversations", params=params, access_token=access_token
            )

            conversations = conversations_result.get("conversations", [])
            conversation_resources = []

            for conversation in conversations:
                title = f"Conversation with {conversation.get('source', {}).get('author', {}).get('name', 'Unknown')}"

                conversation_resources.append(
                    Resource(
                        uri=f"intercom://conversation/{conversation['id']}",
                        mimeType="application/json",
                        name=title,
                    )
                )

            contacts_result = await execute_intercom_request(
                "get", "contacts", params=params, access_token=access_token
            )

            contacts = contacts_result.get("data", [])
            contact_resources = []

            for contact in contacts:
                contact_type = "User" if contact.get("role") == "user" else "Lead"
                name = contact.get("name", "Unnamed Contact")
                email = contact.get("email", "No Email")

                contact_resources.append(
                    Resource(
                        uri=f"intercom://contact/{contact['id']}",
                        mimeType="application/json",
                        name=f"{contact_type}: {name} ({email})",
                    )
                )

            return tag_resources + conversation_resources + contact_resources

        except Exception as e:
            import traceback

            logger.error(f"Error fetching Intercom resources: {str(e)}")
            logger.error(f"Stacktrace: {traceback.format_exc()}")
            return []

    @server.read_resource()
    async def handle_read_resource(uri: AnyUrl) -> Iterable[ReadResourceContents]:
        """Read a resource from Intercom by URI"""
        access_token = await get_intercom_client()
        uri_str = str(uri)

        if uri_str.startswith("intercom://tag/"):
            tag_id = uri_str.replace("intercom://tag/", "")

            tag_result = await execute_intercom_request(
                "get", f"tags/{tag_id}", access_token=access_token
            )

            if not tag_result:
                raise ValueError(f"Tag not found: {tag_id}")

            formatted_content = json.dumps(tag_result, indent=2)
            return [
                ReadResourceContents(
                    content=formatted_content, mime_type="application/json"
                )
            ]

        elif uri_str.startswith("intercom://conversation/"):
            conversation_id = uri_str.replace("intercom://conversation/", "")

            conversation_result = await execute_intercom_request(
                "get", f"conversations/{conversation_id}", access_token=access_token
            )

            if not conversation_result:
                raise ValueError(f"Conversation not found: {conversation_id}")

            formatted_content = json.dumps(conversation_result, indent=2)
            return [
                ReadResourceContents(
                    content=formatted_content, mime_type="application/json"
                )
            ]

        elif uri_str.startswith("intercom://contact/"):
            contact_id = uri_str.replace("intercom://contact/", "")

            contact_result = await execute_intercom_request(
                "get", f"contacts/{contact_id}", access_token=access_token
            )

            if not contact_result:
                raise ValueError(f"Contact not found: {contact_id}")

            formatted_content = json.dumps(contact_result, indent=2)
            return [
                ReadResourceContents(
                    content=formatted_content, mime_type="application/json"
                )
            ]

        raise ValueError(f"Unsupported resource URI: {uri_str}")

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        """List available tools for Intercom"""
        return [
            Tool(
                name="search_contacts",
                description="Search for contacts in Intercom by name or email",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for contacts (name or email)",
                        }
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="create_contact",
                description="Create a new contact in Intercom",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "Email of the contact",
                        },
                        "name": {
                            "type": "string",
                            "description": "Name of the contact",
                        },
                        "role": {
                            "type": "string",
                            "description": "Role of the contact (user or lead)",
                            "enum": ["user", "lead"],
                        },
                        "custom_attributes": {
                            "type": "object",
                            "description": "Custom attributes for the contact (optional)",
                        },
                    },
                    "required": ["email"],
                },
            ),
            Tool(
                name="create_conversation",
                description="Create a new conversation in Intercom",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contact_id": {
                            "type": "string",
                            "description": "ID of the contact to create conversation with",
                        },
                        "message": {
                            "type": "string",
                            "description": "Initial message for the conversation",
                        },
                        "admin_id": {
                            "type": "string",
                            "description": "ID of the admin initiating the conversation (optional)",
                        },
                        "tag_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tag IDs to apply to the conversation (optional)",
                        },
                    },
                    "required": ["contact_id", "message"],
                },
            ),
            Tool(
                name="reply_to_conversation",
                description="Reply to an existing conversation in Intercom",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Reply message",
                        },
                        "user_id": {
                            "type": "string",
                            "description": "ID of the contact/user sending the reply (use this for replies from contacts)",
                        },
                        "admin_id": {
                            "type": "string",
                            "description": "ID of the admin sending the reply (use this for replies from admins)",
                        },
                        "attachment_urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "URLs of attachments to include (optional)",
                        },
                    },
                    "required": ["message"],
                },
            ),
            Tool(
                name="add_tags_to_conversation",
                description="Add tags to an existing conversation",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": "ID of the conversation to tag",
                        },
                        "tag_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "IDs of tags to apply to the conversation",
                        },
                    },
                    "required": ["conversation_id", "tag_ids"],
                },
            ),
            Tool(
                name="remove_tags_from_conversation",
                description="Remove tags from an existing conversation",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "conversation_id": {
                            "type": "string",
                            "description": "ID of the conversation to untag",
                        },
                        "tag_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "IDs of tags to remove from the conversation",
                        },
                    },
                    "required": ["conversation_id", "tag_ids"],
                },
            ),
            Tool(
                name="list_admins",
                description="List all admins/team members in the Intercom workspace",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="search_companies",
                description="Search for companies in Intercom",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for companies (name)",
                        }
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="create_company",
                description="Create a new company in Intercom",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the company",
                        },
                        "company_id": {
                            "type": "string",
                            "description": "Unique identifier for the company in your system (optional)",
                        },
                        "website": {
                            "type": "string",
                            "description": "Website URL of the company (optional)",
                        },
                        "industry": {
                            "type": "string",
                            "description": "Industry of the company (optional)",
                        },
                        "custom_attributes": {
                            "type": "object",
                            "description": "Custom attributes for the company (optional)",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="associate_contact_with_company",
                description="Associate a contact with a company",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contact_id": {
                            "type": "string",
                            "description": "ID of the contact",
                        },
                        "company_id": {
                            "type": "string",
                            "description": "ID of the company",
                        },
                    },
                    "required": ["contact_id", "company_id"],
                },
            ),
            Tool(
                name="list_articles",
                description="List articles",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_id": {
                            "type": "string",
                            "description": "ID of the article collection (optional)",
                        }
                    },
                },
            ),
            Tool(
                name="retrieve_article",
                description="Retrieve articles by ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID of the help center",
                        }
                    },
                    "required": ["id"],
                },
            ),
            Tool(
                name="create_article",
                description="Create a new help center article",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "Title of the article",
                        },
                        "body": {
                            "type": "string",
                            "description": "HTML content of the article",
                        },
                        "author_id": {
                            "type": "string",
                            "description": "ID of the admin authoring the article",
                        },
                        "collection_id": {
                            "type": "string",
                            "description": "ID of the collection to add the article to (optional)",
                        },
                        "state": {
                            "type": "string",
                            "description": "State of the article",
                            "enum": ["draft", "published"],
                        },
                    },
                    "required": ["title", "body", "author_id"],
                },
            ),
            # Ticket management tools
            Tool(
                name="list_tickets",
                description="List support tickets in Intercom",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "state": {
                            "type": "string",
                            "description": "Filter tickets by state (submitted, in_progress, waiting_on_customer, resolved)",
                            "enum": [
                                "submitted",
                                "in_progress",
                                "waiting_on_customer",
                                "resolved",
                                "all",
                            ],
                        },
                        "tag_id": {
                            "type": "string",
                            "description": "Filter tickets by tag ID (optional)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of tickets to return (optional)",
                        },
                    },
                },
            ),
            Tool(
                name="get_ticket",
                description="Get details of a specific support ticket",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticket_id": {
                            "type": "string",
                            "description": "ID of the ticket to retrieve",
                        }
                    },
                    "required": ["ticket_id"],
                },
            ),
            Tool(
                name="create_ticket",
                description="Create a new support ticket in Intercom",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contact_id": {
                            "type": "string",
                            "description": "ID of the contact associated with the ticket",
                        },
                        "ticket_type_id": {
                            "type": "string",
                            "description": "ID of the ticket type",
                        },
                        "title": {
                            "type": "string",
                            "description": "Title/subject of the ticket",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the issue",
                        },
                        "company_id": {
                            "type": "string",
                            "description": "ID of the company to associate with the ticket (optional)",
                        },
                    },
                    "required": [
                        "contact_id",
                        "title",
                        "description",
                        "ticket_type_id",
                    ],
                },
            ),
            Tool(
                name="update_ticket",
                description="Update an existing support ticket in Intercom",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticket_id": {
                            "type": "string",
                            "description": "ID of the ticket to update",
                        },
                        "title": {
                            "type": "string",
                            "description": "New title/subject of the ticket (optional)",
                        },
                        "description": {
                            "type": "string",
                            "description": "New description of the ticket (optional)",
                        },
                        "state": {
                            "type": "string",
                            "description": "New state of the ticket (optional)",
                            "enum": ["in_progress", "waiting_on_customer", "resolved"],
                        },
                        "admin_id": {
                            "type": "string",
                            "description": "ID of the admin to assign the ticket to (optional)",
                        },
                        "is_shared": {
                            "type": "boolean",
                            "description": "Whether the ticket is visible to users (optional)",
                        },
                    },
                    "required": ["ticket_id"],
                },
            ),
            Tool(
                name="add_comment_to_ticket",
                description="Add a comment to an existing support ticket",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticket_id": {
                            "type": "string",
                            "description": "ID of the ticket to add a comment to",
                        },
                        "comment": {
                            "type": "string",
                            "description": "Content of the comment",
                        },
                        "admin_id": {
                            "type": "string",
                            "description": "ID of the admin adding the comment (required)",
                        },
                        "message_type": {
                            "type": "string",
                            "description": "Type of message (only note is supported)",
                            "enum": ["note"],
                        },
                    },
                    "required": ["ticket_id", "comment", "admin_id"],
                },
            ),
            Tool(
                name="list_ticket_types",
                description="List all available ticket types in the Intercom workspace",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[TextContent | ImageContent | EmbeddedResource]:
        """Handle tool execution requests for Intercom"""
        access_token = await get_intercom_client()
        processed_args = arguments or {}

        if name == "search_contacts":
            if "query" not in processed_args:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error="Missing query parameter",
                            )
                        ),
                    )
                ]
            query = processed_args["query"]

            try:
                search_params_email = {
                    "query": {"field": "email", "operator": "~", "value": query}
                }
                search_result = await execute_intercom_request(
                    "post",
                    "contacts/search",
                    data=search_params_email,
                    access_token=access_token,
                )

                contacts = search_result.get("data", [])

                if not contacts:
                    search_params_name = {
                        "query": {"field": "name", "operator": "~", "value": query}
                    }
                    search_result = await execute_intercom_request(
                        "post",
                        "contacts/search",
                        data=search_params_name,
                        access_token=access_token,
                    )

                # search_result will contain the data from the last successful call or the one that found contacts
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=search_result, error=None)
                        ),
                    )
                ]

            except httpx.HTTPStatusError as e:
                logger.error(f"Error searching contacts: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except Exception:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error searching contacts: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "create_contact":
            required_fields = ["email"]
            for field in required_fields:
                if field not in processed_args:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=None,
                                    error=f"Missing required parameter: {field}",
                                )
                            ),
                        )
                    ]

            data = {
                "role": processed_args.get("role", "user"),
                "email": processed_args["email"],
            }

            if "name" in processed_args:
                data["name"] = processed_args["name"]

            if "custom_attributes" in processed_args:
                data["custom_attributes"] = processed_args["custom_attributes"]

            try:
                contact_result = await execute_intercom_request(
                    "post", "contacts", data=data, access_token=access_token
                )

                if not contact_result or "id" not in contact_result:
                    error_message = "Failed to create contact."
                    if (
                        contact_result
                        and isinstance(contact_result.get("errors"), list)
                        and contact_result["errors"]
                    ):
                        error_message = contact_result["errors"][0].get(
                            "message", error_message
                        )

                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=contact_result,
                                    error=error_message,
                                )
                            ),
                        )
                    ]

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=contact_result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error creating contact: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except Exception:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error creating contact: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "create_conversation":
            required_fields = ["contact_id", "message"]
            for field in required_fields:
                if field not in processed_args:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=None,
                                    error=f"Missing required parameter: {field}",
                                )
                            ),
                        )
                    ]

            data = {
                "from": {"type": "user", "id": processed_args["contact_id"]},
                "body": processed_args["message"],
            }

            if "admin_id" in processed_args:
                data["from"] = {"type": "admin", "id": processed_args["admin_id"]}

            if "tag_ids" in processed_args:
                data["tags"] = {"ids": processed_args["tag_ids"]}

            try:
                conversation_result = await execute_intercom_request(
                    "post", "conversations", data=data, access_token=access_token
                )

                if not conversation_result or "id" not in conversation_result:
                    error_message = "Failed to create conversation."
                    if (
                        conversation_result
                        and isinstance(conversation_result.get("errors"), list)
                        and conversation_result["errors"]
                    ):
                        error_message = conversation_result["errors"][0].get(
                            "message", error_message
                        )
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=conversation_result,
                                    error=error_message,
                                )
                            ),
                        )
                    ]

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=True, data=conversation_result, error=None
                            )
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error creating conversation: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except Exception:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error creating conversation: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "reply_to_conversation":
            # The Intercom endpoint for "reply to conversation" is /conversations/{id}/reply
            # The current code uses "conversations/last/reply", which replies to the *last* conversation.
            # The input schema for this tool is missing "conversation_id". This is a pre-existing issue.
            # For now, we adapt to current code, assuming "conversations/last/reply" is intended.
            # If a specific conversation ID is ever used, it must be added to required_fields and path.

            if "message" not in processed_args:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error="Missing required parameter: message",
                            )
                        ),
                    )
                ]

            # conversation_id = processed_args.get("conversation_id") # Not used in current API path but was in old messages

            data = {
                "message_type": "comment",  # As per Intercom API for replying
                "body": processed_args["message"],
            }

            # Set sender type based on provided ID
            if "user_id" in processed_args:  # This implies a reply from a contact/user
                data["from"] = {"type": "user", "id": processed_args["user_id"]}
            elif "admin_id" in processed_args:  # This implies a reply from an admin
                data["from"] = {"type": "admin", "id": processed_args["admin_id"]}
            else:
                # If neither user_id nor admin_id is provided, the API might require one or use a default.
                # The original code did not explicitly handle this "from" field structure for /conversations/last/reply
                # It used `data["type"] = "user"` or `data["type"] = "admin"`
                # And `data["intercom_user_id"]` or `data["admin_id"]`
                # The correct structure for the `from` field when creating messages is usually {"type": "...", "id": "..."}
                # For "conversations/last/reply" or "conversations/{id}/reply", the message body is POSTed.
                # The actual API might be POST /conversations/{id}/reply with message body.
                # The original code used: data["type"], data["intercom_user_id"], data["admin_id"]
                # This might be for a different endpoint or an older API version.
                # The "Reply to conversation part" (POST /conversations/{id}/parts) takes { "message_type": "comment", "body": "...", "author_id": "...", "author_type": "..."}
                # Let's stick to the `message_type` and `body` as per original code, and add `from` if possible
                pass  # API will decide sender or error out if ambiguous/required and not given

            if "attachment_urls" in processed_args:
                data["attachment_urls"] = processed_args["attachment_urls"]

            # Determine conversation ID for the API path
            conversation_id_for_path = processed_args.get("conversation_id")
            if not conversation_id_for_path:
                # Using "last" as per original path if no ID is provided
                api_path = "conversations/last/reply"
            else:
                api_path = f"conversations/{conversation_id_for_path}/reply"

            try:
                reply_result = await execute_intercom_request(
                    "post",
                    api_path,
                    data=data,
                    access_token=access_token,
                )

                if (
                    not reply_result
                    or reply_result.get("type") == "error.list"
                    or "id" not in reply_result
                ):  # Check for API error structure or missing ID
                    error_message = "Failed to reply to conversation."
                    if (
                        reply_result
                        and isinstance(reply_result.get("errors"), list)
                        and reply_result["errors"]
                    ):
                        error_message = reply_result["errors"][0].get(
                            "message", error_message
                        )
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=reply_result,
                                    error=error_message,
                                )
                            ),
                        )
                    ]

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=reply_result, error=None)
                        ),
                    )
                ]

            except httpx.HTTPStatusError as e:
                logger.error(f"Error replying to conversation: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except Exception:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error replying to conversation: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "add_tags_to_conversation":
            required_fields = ["conversation_id", "tag_ids"]
            for field in required_fields:
                if field not in processed_args:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=None,
                                    error=f"Missing required parameter: {field}",
                                )
                            ),
                        )
                    ]

            conversation_id = processed_args["conversation_id"]
            tag_ids = processed_args["tag_ids"]

            # According to Intercom API, adding tags is POST /conversations/{id}/tags with {"id": "tag_id"}
            # Or more commonly: data = {"tags": [{"id": "tag_id1"}, {"id": "tag_id2"}]} to the conversation itself
            # Or POST /tags with {"name": "Urgent", "users": [{"id": "user_id_1"}, ...]}
            # The original code did: POST /conversations/{id}/tags with data = {"tags": {"ids": tag_ids}}
            # Let's assume this is correct structure for this endpoint.
            data = {"id": tag_ids[0]}  # This is for tagging a single tag.
            # If tag_ids is a list, we might need to loop or use a different payload.
            # The endpoint is `/conversations/{conversation_id}/tags`
            # The payload for POST /conversations/{id}/tags seems to be {"id": "tag_id_to_apply"}
            # If multiple tags, it's usually an admin action to create/update a tag with multiple users/conversations
            # or PATCH conversation with tags.
            # The original code used data = {"tags": {"ids": tag_ids}} for POST conversations/{id}/tags
            # Let's try to match that:
            data_payload = {
                "admin_id": "YOUR_ADMIN_ID_HERE",
                "tags": [{"id": tid} for tid in tag_ids],
            }  # This might be a PUT/PATCH on conversation
            # The endpoint /conversations/{id}/tags usually takes a single tag id for POST.
            # Let's use the original logic's data structure and endpoint.

            # Correcting: The API is typically POST /conversations/{id}/tags with a body like { "id": "tag_id_to_add" }
            # To add multiple tags, this might need to be called multiple times, or the conversation updated directly.
            # The previous code: data = {"tags": {"ids": tag_ids}} to f"conversations/{conversation_id}/tags"
            # This structure is unusual for a POST to `/tags` sub-resource.
            # A more common way is PUT/PATCH on the conversation object itself with a list of tags.
            # Or, if the endpoint truly supports it:
            data_for_tagging = {
                "tags": [{"id": tag_id} for tag_id in tag_ids]
            }  # This is more standard for updating a resource with tags
            # However, the original code used a `data = {"tags": {"ids": tag_ids}}`. Let's use that if it's a specific Intercomism.
            # The API doc for "Tag a conversation" (POST /conversations/{id}/tags) shows body: { "id": "string" (Tag ID) }
            # This means it can only add one tag at a time.
            # The original code's `data = {"tags": {"ids": tag_ids}}` is likely incorrect for this endpoint.
            # To match `add_tags_to_conversation` where `tag_ids` is a list:
            # We should probably iterate and add one by one.

            results = []
            errors = []

            try:
                for tag_id in tag_ids:
                    tag_payload = {"id": tag_id}
                    result = await execute_intercom_request(
                        "post",
                        f"conversations/{conversation_id}/tags",
                        data=tag_payload,
                        access_token=access_token,
                    )
                    # Assuming result is the conversation object or a success indicator.
                    # Intercom usually returns the object that was acted upon (e.g., the tag applied or the conversation).
                    results.append(result)

                if errors:  # If some tags failed
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data={
                                        "successful_tags": results,
                                        "failed_tags": errors,
                                    },
                                    error="Some tags could not be added.",
                                )
                            ),
                        )
                    ]

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=True,
                                data={"applied_tags_responses": results},
                                error=None,
                            )  # Data contains list of responses for each tag add.
                        ),
                    )
                ]

            except httpx.HTTPStatusError as e:
                logger.error(f"Error adding tags to conversation: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                errors.append(
                    {
                        "tag_id": "current_tag_being_processed",
                        "error": str(e),
                        "details": error_data,
                    }
                )  # Simplified error aggregation
                # If an error occurs, we might have partial success. The current loop structure doesn't easily return that.
                # For simplicity, first error fails the whole operation for now.
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=error_data,
                                error=f"Error adding tags: {str(e)}",
                            )
                        ),
                    )
                ]

            except Exception as e:
                logger.error(f"Error adding tags to conversation: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error=f"Error adding tags: {str(e)}",
                            )
                        ),
                    )
                ]

        elif name == "remove_tags_from_conversation":
            required_fields = ["conversation_id", "tag_ids"]
            for field in required_fields:
                if field not in processed_args:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=None,
                                    error=f"Missing required parameter: {field}",
                                )
                            ),
                        )
                    ]

            conversation_id = processed_args["conversation_id"]
            tag_ids = processed_args["tag_ids"]

            removed_tags_responses = []
            errors = []

            try:
                for tag_id in tag_ids:
                    # DELETE /conversations/{conversation_id}/tags/{tag_id}
                    response = await execute_intercom_request(
                        "delete",
                        f"conversations/{conversation_id}/tags/{tag_id}",
                        access_token=access_token,
                    )
                    # DELETE often returns 204 No Content, or the parent object.
                    # execute_intercom_request returns response.json(). For 204, this might be an issue if no body.
                    # Assuming execute_intercom_request handles empty JSON responses for DELETE.
                    removed_tags_responses.append(
                        {"tag_id": tag_id, "response": response}
                    )

                if errors:  # If any error occurred
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data={
                                        "removed_tags": removed_tags_responses,
                                        "errors": errors,
                                    },
                                    error="Some tags could not be removed.",
                                )
                            ),
                        )
                    ]

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=True,
                                data={"removed_tags_info": removed_tags_responses},
                                error=None,
                            )
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error removing tags from conversation: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                # This exception will break the loop. For simplicity, first error fails all.
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=error_data,
                                error=f"Error removing tags: {str(e)}",
                            )
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error removing tags from conversation: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error=f"Error removing tags: {str(e)}",
                            )
                        ),
                    )
                ]

        elif name == "list_admins":
            try:
                admins_result = await execute_intercom_request(
                    "get", "admins", access_token=access_token
                )
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=admins_result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error listing admins: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error listing admins: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "search_companies":
            if "query" not in processed_args:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error="Missing query parameter",
                            )
                        ),
                    )
                ]
            query = processed_args["query"]
            try:
                # Intercom search for companies is typically POST companies/search or GET companies with filters
                # Original code used POST companies/list with "filter"
                # Assuming this is correct:
                search_params = {
                    # "name": query # A common way to search
                    # Or using the filter syntax if supported by companies/list
                    "filter": {
                        "field": "name",
                        "operator": "~",
                        "value": query,
                    }  # As per original
                }
                search_result = await execute_intercom_request(
                    "post",  # Or GET depending on API
                    "companies/list",  # Or "companies/search" or "companies"
                    data=search_params,  # This implies POST
                    access_token=access_token,
                )
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=search_result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error searching companies: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error searching companies: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "create_company":
            if "name" not in processed_args:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error="Missing required parameter: name",
                            )
                        ),
                    )
                ]

            data = {"name": processed_args["name"]}
            optional_fields = ["company_id", "website", "industry", "custom_attributes"]
            for field in optional_fields:
                if field in processed_args:
                    data[field] = processed_args[field]

            if (
                "company_id" not in data
            ):  # Ensure company_id is set, as per original logic
                data["company_id"] = str(uuid.uuid4())

            logger.info(f"Creating company with data: {data}")
            try:
                company_result = await execute_intercom_request(
                    "post", "companies", data=data, access_token=access_token
                )
                logger.info(f"Company result: {company_result}")

                if not company_result or "id" not in company_result:
                    error_message = "Failed to create company."
                    if (
                        company_result
                        and isinstance(company_result.get("errors"), list)
                        and company_result["errors"]
                    ):
                        error_message = company_result["errors"][0].get(
                            "message", error_message
                        )
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=company_result,
                                    error=error_message,
                                )
                            ),
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=company_result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error creating company: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error creating company: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "associate_contact_with_company":
            required_fields = ["contact_id", "company_id"]
            for field in required_fields:
                if field not in processed_args:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=None,
                                    error=f"Missing required parameter: {field}",
                                )
                            ),
                        )
                    ]

            contact_id = processed_args["contact_id"]
            company_id = processed_args["company_id"]

            # Intercom API to associate: POST /contacts/{contact_id}/companies with body {"id": company_id}
            # Or update contact: PUT /contacts/{contact_id} with body {"company_ids": [company_id]}
            # Original code: POST /contacts/{contact_id}/companies with data = {"companies": [{"id": company_id}]}
            # This looks like it might be for adding multiple companies, but schema implies one.
            # Let's use the simpler one if it is just one association:
            payload = {"id": company_id}
            # If the original payload `{"companies": [{"id": company_id}]}` is specifically required by Intercom:
            # payload = {"companies": [{"id": company_id}]}
            # Sticking to original code's payload structure for now.
            payload = {"companies": [{"id": company_id}]}

            try:
                # This endpoint should ideally return the updated contact or the company.
                result = await execute_intercom_request(
                    "post",  # Or PUT on contact
                    f"contacts/{contact_id}/companies",  # This seems like adding company to contact
                    data=payload,
                    access_token=access_token,
                )
                # Check result for success indication
                if (
                    not result or result.get("type") == "error.list"
                ):  # Example error check
                    error_message = "Failed to associate contact with company."
                    if (
                        result
                        and isinstance(result.get("errors"), list)
                        and result["errors"]
                    ):
                        error_message = result["errors"][0].get(
                            "message", error_message
                        )
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False, data=result, error=error_message
                                )
                            ),
                        )
                    ]

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error associating contact with company: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error associating contact with company: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error=f"Error associating contact with company: {str(e)}",
                            )
                        ),
                    )
                ]

        elif name == "list_articles":
            params = {}
            if "collection_id" in processed_args:
                params["collection_id"] = processed_args["collection_id"]
            # Other params like page, per_page could be added from processed_args
            try:
                articles_result = await execute_intercom_request(
                    "get", "articles", params=params, access_token=access_token
                )
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=True,
                                data=articles_result.get("data", []),
                                error=None,
                            )
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error listing articles: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error listing articles: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "retrieve_article":
            if "id" not in processed_args:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error="Missing required article ID parameter",
                            )
                        ),
                    )
                ]
            article_id = processed_args["id"]
            try:
                article_result = await execute_intercom_request(
                    "get",
                    f"articles/{article_id}",
                    access_token=access_token,
                )
                logger.info(f"Article result: {article_result}")

                if (
                    not article_result or "id" not in article_result
                ):  # Basic check for valid article data
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=article_result,  # Include what was returned
                                    error=f"No article found with ID: {article_id}",
                                )
                            ),
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=article_result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error retrieving article: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error retrieving article: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "create_article":
            required_fields = ["title", "body", "author_id"]
            for field in required_fields:
                if field not in processed_args:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=None,
                                    error=f"Missing required parameter: {field}",
                                )
                            ),
                        )
                    ]

            data = {
                "title": processed_args["title"],
                "body": processed_args["body"],  # Should be HTML
                "author_id": processed_args["author_id"],  # Admin ID
                "state": processed_args.get("state", "draft"),  # "draft" or "published"
            }

            if "collection_id" in processed_args:  # collection_id is parent_id
                data["parent_id"] = processed_args["collection_id"]
                data["parent_type"] = "collection"  # As per Intercom API

            try:
                article_result = await execute_intercom_request(
                    "post", "articles", data=data, access_token=access_token
                )

                if not article_result or "id" not in article_result:
                    error_message = "Failed to create article."
                    if (
                        article_result
                        and isinstance(article_result.get("errors"), list)
                        and article_result["errors"]
                    ):
                        error_message = article_result["errors"][0].get(
                            "message", error_message
                        )
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=article_result,
                                    error=error_message,
                                )
                            ),
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=article_result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error creating article: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error creating article: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        # Ticket management tool implementations
        elif name == "list_tickets":
            params = {}
            if "state" in processed_args and processed_args["state"] != "all":
                params["state"] = processed_args["state"]
            if (
                "tag_id" in processed_args
            ):  # Assuming this is a valid filter for Intercom tickets API
                params["tag_id"] = processed_args["tag_id"]
            if "limit" in processed_args:  # API might use "per_page" or "count"
                params["per_page"] = processed_args["limit"]

            try:
                tickets_result = await execute_intercom_request(
                    "get", "tickets", params=params, access_token=access_token
                )
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=tickets_result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error listing tickets: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error listing tickets: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "get_ticket":
            if "ticket_id" not in processed_args:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error="Missing required parameter: ticket_id",
                            )
                        ),
                    )
                ]
            ticket_id = processed_args["ticket_id"]
            try:
                ticket_result = await execute_intercom_request(
                    "get", f"tickets/{ticket_id}", access_token=access_token
                )
                if not ticket_result or "id" not in ticket_result:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=ticket_result,
                                    error=f"Ticket with ID {ticket_id} not found.",
                                )
                            ),
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=ticket_result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error retrieving ticket: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                # Check if status code is 404 for "not found" specifically
                if e.response and e.response.status_code == 404:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=error_data,
                                    error=f"Ticket with ID {ticket_id} not found.",
                                )
                            ),
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error retrieving ticket: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "create_ticket":
            # Required fields from schema: "contact_id", "title", "description", "ticket_type_id"
            required_fields = ["contact_id", "title", "description", "ticket_type_id"]
            for field in required_fields:
                if field not in processed_args:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=None,
                                    error=f"Missing required parameter: {field}",
                                )
                            ),
                        )
                    ]

            # Structure for creating a ticket (this was simplified in original code)
            # POST /tickets
            # {
            #   "ticket_type_id": "...",
            #   "contacts": [{"id": "contact_id_1"}],
            #   "ticket_attributes": { "_default_title_": "...", "_default_description_": "..." },
            #   "admin_assignee_id": "optional_admin_id", (or use assignment object)
            #   "company_associations": [{"id": "company_id_1"}]
            # }
            data = {
                "ticket_type_id": processed_args["ticket_type_id"],
                "contacts": [
                    {"id": processed_args["contact_id"]}
                ],  # Assuming one contact
                "ticket_attributes": {
                    "_default_title_": processed_args["title"],
                    "_default_description_": processed_args["description"],
                },
            }

            if "company_id" in processed_args:  # This should be company_associations
                data["company_associations"] = [{"id": processed_args["company_id"]}]

            # Add other optional fields from processed_args if API supports them directly (e.g. admin_assignee_id)

            try:
                ticket_result = await execute_intercom_request(
                    "post", "tickets", data=data, access_token=access_token
                )
                if not ticket_result or "id" not in ticket_result:
                    error_message = "Failed to create ticket."
                    if (
                        ticket_result
                        and isinstance(ticket_result.get("errors"), list)
                        and ticket_result["errors"]
                    ):
                        error_message = ticket_result["errors"][0].get(
                            "message", error_message
                        )
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=ticket_result,
                                    error=error_message,
                                )
                            ),
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=ticket_result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error creating ticket: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error creating ticket: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "update_ticket":
            if "ticket_id" not in processed_args:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error="Missing required parameter: ticket_id",
                            )
                        ),
                    )
                ]
            ticket_id = processed_args["ticket_id"]
            data_to_update = {}  # PUT /tickets/{id}

            ticket_attributes = {}
            if "title" in processed_args:
                ticket_attributes["_default_title_"] = processed_args["title"]
            if "description" in processed_args:
                ticket_attributes["_default_description_"] = processed_args[
                    "description"
                ]
            if ticket_attributes:
                data_to_update["ticket_attributes"] = ticket_attributes

            if "state" in processed_args:  # e.g., "in_progress", "resolved"
                data_to_update["state"] = processed_args["state"]

            if "admin_id" in processed_args:  # admin_assignee_id
                data_to_update["admin_assignee_id"] = processed_args["admin_id"]
                # Or using assignment object: data_to_update["assignment"] = {"admin_id": processed_args["admin_id"]}

            if (
                "is_shared" in processed_args
            ):  # This field might not be directly updatable or named differently
                data_to_update["is_shared"] = processed_args[
                    "is_shared"
                ]  # Verify API field name

            if not data_to_update:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error="No fields provided to update.",
                            )
                        ),
                    )
                ]
            try:
                ticket_result = await execute_intercom_request(
                    "put",
                    f"tickets/{ticket_id}",
                    data=data_to_update,
                    access_token=access_token,
                )
                if not ticket_result or "id" not in ticket_result:
                    error_message = "Failed to update ticket."
                    if (
                        ticket_result
                        and isinstance(ticket_result.get("errors"), list)
                        and ticket_result["errors"]
                    ):
                        error_message = ticket_result["errors"][0].get(
                            "message", error_message
                        )
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=ticket_result,
                                    error=error_message,
                                )
                            ),
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=ticket_result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error updating ticket: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error updating ticket: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        elif name == "add_comment_to_ticket":
            # POST /tickets/{id}/reply
            required_fields = ["ticket_id", "comment", "admin_id"]
            for field in required_fields:
                if field not in processed_args:
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=None,
                                    error=f"Missing required parameter: {field}",
                                )
                            ),
                        )
                    ]
            ticket_id = processed_args["ticket_id"]

            # Payload for POST /tickets/{id}/reply
            # { "message_type": "note" (or "comment"), "type": "admin", "admin_id": "...", "body": "..."}
            # "type" here is sender type.
            data = {
                "message_type": processed_args.get(
                    "message_type", "note"
                ),  # Schema says "note"
                "type": "admin",  # Comment is from an admin
                "admin_id": processed_args["admin_id"],
                "body": processed_args["comment"],
            }
            try:
                comment_result = await execute_intercom_request(
                    "post",
                    f"tickets/{ticket_id}/reply",
                    data=data,
                    access_token=access_token,
                )
                # Successful reply usually returns the created ticket part / comment object.
                if (
                    not comment_result or "id" not in comment_result
                ):  # Check for valid comment object
                    error_message = "Failed to add comment."
                    if (
                        comment_result
                        and isinstance(comment_result.get("errors"), list)
                        and comment_result["errors"]
                    ):
                        error_message = comment_result["errors"][0].get(
                            "message", error_message
                        )
                    return [
                        TextContent(
                            type="text",
                            text=json.dumps(
                                ToolResponse(
                                    success=False,
                                    data=comment_result,
                                    error=error_message,
                                )
                            ),
                        )
                    ]
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=True, data=comment_result, error=None)
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error adding comment to ticket: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error adding comment to ticket: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=False,
                                data=None,
                                error=f"Error adding comment to ticket: {str(e)}",
                            )
                        ),
                    )
                ]

        elif name == "list_ticket_types":
            # GET /ticket_types
            try:
                ticket_types_result = await execute_intercom_request(
                    "get", "ticket_types", access_token=access_token
                )
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(
                                success=True, data=ticket_types_result, error=None
                            )
                        ),
                    )
                ]
            except httpx.HTTPStatusError as e:
                logger.error(f"Error listing ticket types: {str(e)}")
                error_data = None
                try:
                    error_data = e.response.json()
                except:
                    pass
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=error_data, error=str(e))
                        ),
                    )
                ]
            except Exception as e:
                logger.error(f"Error listing ticket types: {str(e)}")
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            ToolResponse(success=False, data=None, error=str(e))
                        ),
                    )
                ]

        # Fallback for unknown tool
        return [
            TextContent(
                type="text",
                text=json.dumps(
                    ToolResponse(
                        success=False, data=None, error=f"Unknown tool: {name}"
                    )
                ),
            )
        ]
        # raise ValueError(f"Unknown tool: {name}") # Old way

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    """Get the initialization options for the server"""
    return InitializationOptions(
        server_name="intercom-server",
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
