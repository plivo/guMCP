import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from simple_salesforce import Salesforce

project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from src.utils.salesforce.util import authenticate_and_save_credentials, get_credentials
from src.utils.utils import ToolResponse

SERVICE_NAME = Path(__file__).parent.name

SCOPES = [  # Basic web integration capabilities
    "full",
    "api",
    "id",
    "profile",
    "email",
    "address",
    "phone",
    "web",
    "refresh_token",
    "offline_access",
    "openid",
    "custom_permissions",
    # Full access to all resources the user has access to
]


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(SERVICE_NAME)


async def get_salesforce_token(user_id, api_key=None):
    """
    This function is used to get the Salesforce access token for a specific user.

    Args:
        user_id (str): The user identifier.
        api_key (Optional[str]): Optional API key.

    Returns:
        str: The access token to authenticate with the Snowflake API.
    """
    token = await get_credentials(user_id, SERVICE_NAME, api_key)
    return token


def create_server(user_id, api_key=None):
    """
    Initializes and configures a Salesforce MCP server instance.

    Args:
        user_id (str): The unique user identifier for session context.
        api_key (Optional[str]): Optional API key for user auth context.

    Returns:
        Server: Configured server instance with all Snowflake tools registered.
    """
    server = Server("salesforce-server")
    server.user_id = user_id
    server.api_key = api_key

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        """
        Lists all available tools for interacting with the Salesforce API.

        Returns:
            list[types.Tool]: A list of tool metadata with schema definitions.
        """
        logger.info(f"Listing tools for user: {user_id}")
        return [
            types.Tool(
                name="soql_query",
                description="Executes a SOQL query to retrieve Salesforce records with support for relationships and complex filters",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The SOQL query to execute (e.g., 'SELECT Id, Name FROM Account WHERE Industry = \\'Technology\\'')",
                        },
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="sosl_search",
                description="Performs a text-based search across multiple Salesforce objects using SOSL",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "search": {
                            "type": "string",
                            "description": "The SOSL search string (e.g., 'FIND {Cloud} IN ALL FIELDS RETURNING Account, Opportunity')",
                        },
                    },
                    "required": ["search"],
                },
            ),
            types.Tool(
                name="describe_object",
                description="Retrieves detailed metadata about a Salesforce object including fields, relationships, and permissions",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "object_name": {
                            "type": "string",
                            "description": "The API name of the Salesforce object (e.g., 'Account', 'Contact', 'Custom_Object__c')",
                        },
                    },
                    "required": ["object_name"],
                },
            ),
            types.Tool(
                name="get_record",
                description="Retrieves a specific Salesforce record by ID with all accessible fields",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "object_name": {
                            "type": "string",
                            "description": "The API name of the Salesforce object (e.g., 'Account', 'Contact')",
                        },
                        "record_id": {
                            "type": "string",
                            "description": "The 15 or 18-character Salesforce ID of the record",
                        },
                        "fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of specific fields to retrieve (retrieves all accessible fields if not specified)",
                        },
                    },
                    "required": ["object_name", "record_id"],
                },
            ),
            types.Tool(
                name="create_record",
                description="Creates a new record in Salesforce",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "object_name": {
                            "type": "string",
                            "description": "The API name of the Salesforce object (e.g., 'Account', 'Contact')",
                        },
                        "data": {
                            "type": "object",
                            "description": "Field data for the new record as key-value pairs",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["object_name", "data"],
                },
            ),
            types.Tool(
                name="update_record",
                description="Updates an existing Salesforce record",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "object_name": {
                            "type": "string",
                            "description": "The API name of the Salesforce object (e.g., 'Account', 'Contact')",
                        },
                        "record_id": {
                            "type": "string",
                            "description": "The 15 or 18-character Salesforce ID of the record to update",
                        },
                        "data": {
                            "type": "object",
                            "description": "Field data to update as key-value pairs",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["object_name", "record_id", "data"],
                },
            ),
            types.Tool(
                name="delete_record",
                description="Deletes a Salesforce record",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "object_name": {
                            "type": "string",
                            "description": "The API name of the Salesforce object (e.g., 'Account', 'Contact')",
                        },
                        "record_id": {
                            "type": "string",
                            "description": "The 15 or 18-character Salesforce ID of the record to delete",
                        },
                    },
                    "required": ["object_name", "record_id"],
                },
            ),
            types.Tool(
                name="get_org_limits",
                description="Retrieves current organization limits and usage",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit_type": {
                            "type": "string",
                            "description": "Optional specific limit to check (e.g., 'DailyApiRequests', 'DataStorageMB')",
                        },
                    },
                },
            ),
            types.Tool(
                name="get_contact_by_phone",
                description="Retrieves contact details by phone number",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "phone_number": {
                            "type": "string",
                            "description": "The phone number to search for contacts",
                        },
                    },
                    "required": ["phone_number"],
                },
            ),
            types.Tool(
                name="get_contact_by_email",
                description="Retrieves contact details by email address",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "The email address to search for contacts",
                        },
                    },
                    "required": ["email"],
                },
            ),
            types.Tool(
                name="get_contact_by_id",
                description="Retrieves contact details by Salesforce contact ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contact_id": {
                            "type": "string",
                            "description": "The Salesforce contact ID",
                        },
                    },
                    "required": ["contact_id"],
                },
            ),
            types.Tool(
                name="create_contact",
                description="Creates a new contact in Salesforce",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "first_name": {
                            "type": "string",
                            "description": "First name of the contact",
                        },
                        "last_name": {
                            "type": "string",
                            "description": "Last name of the contact",
                        },
                        "email": {
                            "type": "string",
                            "description": "Email address of the contact",
                        },
                        "phone": {
                            "type": "string",
                            "description": "Phone number of the contact",
                        },
                        "additional_fields": {
                            "type": "object",
                            "description": "Additional field data for the contact as key-value pairs",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["last_name"],
                },
            ),
            types.Tool(
                name="update_contact",
                description="Updates an existing contact in Salesforce",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contact_id": {
                            "type": "string",
                            "description": "The Salesforce contact ID to update",
                        },
                        "first_name": {
                            "type": "string",
                            "description": "First name of the contact",
                        },
                        "last_name": {
                            "type": "string",
                            "description": "Last name of the contact",
                        },
                        "email": {
                            "type": "string",
                            "description": "Email address of the contact",
                        },
                        "phone": {
                            "type": "string",
                            "description": "Phone number of the contact",
                        },
                        "additional_fields": {
                            "type": "object",
                            "description": "Additional field data for the contact as key-value pairs",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["contact_id"],
                },
            ),
            types.Tool(
                name="create_lead",
                description="Creates a new lead in Salesforce",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "first_name": {
                            "type": "string",
                            "description": "First name of the lead",
                        },
                        "last_name": {
                            "type": "string",
                            "description": "Last name of the lead",
                        },
                        "email": {
                            "type": "string",
                            "description": "Email address of the lead",
                        },
                        "phone": {
                            "type": "string",
                            "description": "Phone number of the lead",
                        },
                        "company": {
                            "type": "string",
                            "description": "Company name of the lead",
                        },
                        "additional_fields": {
                            "type": "object",
                            "description": "Additional field data for the lead as key-value pairs",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["last_name", "company"],
                },
            ),
            types.Tool(
                name="get_case_by_id",
                description="Retrieves case details by Salesforce case ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "The Salesforce case ID",
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            types.Tool(
                name="get_recent_cases",
                description="Retrieves recent cases for a contact",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contact_id": {
                            "type": "string",
                            "description": "The Salesforce contact ID",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of cases to retrieve (default: 10)",
                        },
                    },
                    "required": ["contact_id"],
                },
            ),
            types.Tool(
                name="create_case",
                description="Creates a new case in Salesforce",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "contact_id": {
                            "type": "string",
                            "description": "The Salesforce contact ID associated with the case",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Subject of the case",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the case",
                        },
                        "status": {
                            "type": "string",
                            "description": "Status of the case (e.g., 'New', 'Open', 'Closed')",
                        },
                        "origin": {
                            "type": "string",
                            "description": "Origin of the case (e.g., 'Phone', 'Email', 'Web')",
                        },
                        "additional_fields": {
                            "type": "object",
                            "description": "Additional field data for the case as key-value pairs",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["subject"],
                },
            ),
            types.Tool(
                name="update_case",
                description="Updates an existing case in Salesforce",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "case_id": {
                            "type": "string",
                            "description": "The Salesforce case ID to update",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Subject of the case",
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of the case",
                        },
                        "status": {
                            "type": "string",
                            "description": "Status of the case (e.g., 'New', 'Open', 'Closed')",
                        },
                        "additional_fields": {
                            "type": "object",
                            "description": "Additional field data for the case as key-value pairs",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["case_id"],
                },
            ),
            types.Tool(
                name="get_cases_by_phone",
                description="Retrieves recent cases associated with a phone number",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "phone_number": {
                            "type": "string",
                            "description": "The phone number to search for related cases",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of cases to retrieve (default: 10)",
                        },
                    },
                    "required": ["phone_number"],
                },
            ),
            types.Tool(
                name="get_cases_by_email",
                description="Retrieves recent cases associated with an email address",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "The email address to search for related cases",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of cases to retrieve (default: 10)",
                        },
                    },
                    "required": ["email"],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict | None):
        """
        Dispatches a tool call to the corresponding Salesforce API method.

        Args:
            name (str): The tool name to execute.
            arguments (dict | None): Arguments to pass to the tool.

        Returns:
            list[types.TextContent]: The JSON-formatted result of the API call.

        Raises:
            ValueError: If an unknown tool name is provided.
        """
        logger.info(f"User {user_id} calling tool: {name} with args: {arguments}")

        token = await get_salesforce_token(server.user_id, server.api_key)
        salesforce_client = Salesforce(
            instance_url=token.get("instance_url", ""),
            session_id=token.get("access_token", ""),
        )
        custom_fields = token.get("custom_fields", {}) or {}
        if arguments is None:
            arguments = {}

        try:
            if name == "soql_query":
                query = arguments.get("query")
                if not query:
                    raise ValueError("Missing 'query' argument")
                return await execute_soql_query(salesforce_client, query)
            elif name == "sosl_search":
                search = arguments.get("search")
                if not search:
                    raise ValueError("Missing 'search' argument")
                return await execute_sosl_search(salesforce_client, search)
            elif name == "describe_object":
                object_name = arguments.get("object_name")
                if not object_name:
                    raise ValueError("Missing 'object_name' argument")
                return await describe_salesforce_object(salesforce_client, object_name)
            elif name == "get_record":
                object_name = arguments.get("object_name")
                record_id = arguments.get("record_id")
                if not object_name or not record_id:
                    raise ValueError("Missing 'object_name' or 'record_id' argument")
                return await get_salesforce_record(
                    salesforce_client, object_name, record_id
                )
            elif name == "create_record":
                object_name = arguments.get("object_name")
                data = arguments.get("data")
                if not object_name or not data:
                    raise ValueError("Missing 'object_name' or 'data' argument")
                return await create_salesforce_record(
                    salesforce_client, object_name, data
                )
            elif name == "update_record":
                object_name = arguments.get("object_name")
                record_id = arguments.get("record_id")
                data = arguments.get("data")
                if not object_name or not record_id or not data:
                    raise ValueError(
                        "Missing 'object_name', 'record_id', or 'data' argument"
                    )
                return await update_salesforce_record(
                    salesforce_client, object_name, record_id, data
                )
            elif name == "delete_record":
                object_name = arguments.get("object_name")
                record_id = arguments.get("record_id")
                if not object_name or not record_id:
                    raise ValueError("Missing 'object_name' or 'record_id' argument")
                return await delete_salesforce_record(
                    salesforce_client, object_name, record_id
                )
            elif name == "get_org_limits":
                limit_type = arguments.get("limit_type")
                return await get_salesforce_org_limits(salesforce_client, limit_type)
            elif name == "get_contact_by_phone":
                phone_number = arguments.get("phone_number")
                if not phone_number:
                    raise ValueError("Missing 'phone_number' argument")
                return await get_contact_by_phone(
                    salesforce_client, token, phone_number, custom_fields
                )
            elif name == "get_contact_by_email":
                email = arguments.get("email")
                if not email:
                    raise ValueError("Missing 'email' argument")
                return await get_contact_by_email(
                    salesforce_client, token, email, custom_fields
                )
            elif name == "get_contact_by_id":
                contact_id = arguments.get("contact_id")
                if not contact_id:
                    raise ValueError("Missing 'contact_id' argument")
                return await get_contact_by_id(
                    salesforce_client, token, contact_id, custom_fields
                )
            elif name == "create_contact":
                last_name = arguments.get("last_name")
                if not last_name:
                    raise ValueError("Missing required 'last_name' argument")
                return await create_contact(
                    salesforce_client, token, arguments, custom_fields
                )
            elif name == "update_contact":
                contact_id = arguments.get("contact_id")
                if not contact_id:
                    raise ValueError("Missing required 'contact_id' argument")
                return await update_contact(
                    salesforce_client, token, contact_id, arguments, custom_fields
                )
            elif name == "create_lead":
                last_name = arguments.get("last_name")
                company = arguments.get("company")
                if not last_name or not company:
                    raise ValueError(
                        "Missing required 'last_name' or 'company' argument"
                    )
                return await create_lead(
                    salesforce_client, token, arguments, custom_fields
                )
            elif name == "get_case_by_id":
                case_id = arguments.get("case_id")
                if not case_id:
                    raise ValueError("Missing 'case_id' argument")
                return await get_case_by_id(
                    salesforce_client, token, case_id, custom_fields
                )
            elif name == "get_recent_cases":
                contact_id = arguments.get("contact_id")
                limit = arguments.get("limit", 10)
                if not contact_id:
                    raise ValueError("Missing 'contact_id' argument")
                return await get_recent_cases(
                    salesforce_client, token, contact_id, limit, custom_fields
                )
            elif name == "create_case":
                subject = arguments.get("subject")
                if not subject:
                    raise ValueError("Missing required 'subject' argument")
                return await create_case(
                    salesforce_client, token, arguments, custom_fields
                )
            elif name == "update_case":
                case_id = arguments.get("case_id")
                if not case_id:
                    raise ValueError("Missing required 'case_id' argument")
                return await update_case(
                    salesforce_client, token, case_id, arguments, custom_fields
                )
            elif name == "get_cases_by_phone":
                phone_number = arguments.get("phone_number")
                limit = arguments.get("limit", 10)
                if not phone_number:
                    raise ValueError("Missing 'phone_number' argument")
                return await get_cases_by_phone(
                    salesforce_client, token, phone_number, limit, custom_fields
                )
            elif name == "get_cases_by_email":
                email = arguments.get("email")
                limit = arguments.get("limit", 10)
                if not email:
                    raise ValueError("Missing 'email' argument")
                return await get_cases_by_email(
                    salesforce_client, token, email, limit, custom_fields
                )
            raise ValueError(f"Unknown tool: {name}")

        except Exception as e:
            tb_lineno = "unknown"
            if e.__traceback__:
                tb_lineno = str(e.__traceback__.tb_lineno)

            logger.error(f"Error calling Salesforce API: {e} on line {tb_lineno}")
            return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]

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
        server_name="snowflake-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


if __name__ == "__main__":
    if sys.argv[1].lower() == "auth":
        user_id = "local"
        authenticate_and_save_credentials(user_id, SERVICE_NAME, SCOPES)

    else:
        print("Usage:")
        print("  python main.py auth - Run authentication flow for a user")


async def execute_soql_query(client: Salesforce, query: str):
    """Execute a SOQL query on Salesforce."""
    response: ToolResponse = {"success": False, "data": None, "error": None}

    try:
        results = client.query_all(query)
        response["success"] = True
        response["data"] = results
    except Exception as e:
        response["error"] = str(e)

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def execute_sosl_search(client: Salesforce, search: str):
    """Execute a SOSL search on Salesforce."""
    results = client.search(search)
    return [
        types.TextContent(
            type="text",
            text=json.dumps(results),
        )
    ]


async def describe_salesforce_object(client: Salesforce, object_name: str):
    """Retrieve metadata for a Salesforce object."""
    # Get object description
    sf_object = getattr(client, object_name)
    describe_result = sf_object.describe()

    # Format field information
    fields_info = []
    for field in describe_result["fields"]:
        field_info = {
            "name": field["name"],
            "label": field["label"],
            "type": field["type"],
            "required": not field["nillable"],
            "updateable": field["updateable"],
            "createable": field["createable"],
        }
        if field["type"] == "picklist":
            field_info["picklistValues"] = [
                {"label": pv["label"], "value": pv["value"]}
                for pv in field["picklistValues"]
                if pv["active"]
            ]
        fields_info.append(field_info)

    return [
        types.TextContent(
            type="text",
            text=json.dumps(fields_info),
        )
    ]


async def get_salesforce_record(client: Salesforce, object_name: str, record_id: str):
    """Retrieve a specific Salesforce record by ID."""
    sf_object = getattr(client, object_name)
    results = sf_object.get(record_id)
    return [
        types.TextContent(
            type="text",
            text=json.dumps(results),
        )
    ]


async def create_salesforce_record(client: Salesforce, object_name: str, data: dict):
    """Create a new record in Salesforce."""
    sf_object = getattr(client, object_name)
    results = sf_object.create(data)
    return [
        types.TextContent(
            type="text",
            text=json.dumps(results),
        )
    ]


async def update_salesforce_record(
    client: Salesforce, object_name: str, record_id: str, data: dict
):
    """Update an existing record in Salesforce."""
    sf_object = getattr(client, object_name)
    results = sf_object.update(record_id, data)
    # If results is not a dict, convert it to one
    if not isinstance(results, dict):
        results = {"error": results}
    return [
        types.TextContent(
            type="text",
            text=json.dumps(results),
        )
    ]


async def delete_salesforce_record(
    client: Salesforce, object_name: str, record_id: str
):
    """Delete a Salesforce record."""
    sf_object = getattr(client, object_name)
    results = sf_object.delete(record_id)
    # If results is not a dict, convert it to one
    if not isinstance(results, dict):
        results = {"error": results}
    return [
        types.TextContent(
            type="text",
            text=json.dumps(results),
        )
    ]


async def get_salesforce_org_limits(
    client: Salesforce, limit_type: Optional[str] = None
):
    """Retrieve organization limits from Salesforce."""
    # Get all organization limits
    org_limits = client.limits()

    # If a specific limit type is requested, filter the results
    if limit_type:
        if limit_type in org_limits:
            results = {limit_type: org_limits[limit_type]}
        else:
            available_limits = list(org_limits.keys())
            response: ToolResponse = {
                "success": False,
                "data": None,
                "error": f"Limit type '{limit_type}' not found",
            }
            response["data"] = {"available_limits": available_limits}
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps(response),
                )
            ]
    else:
        results = org_limits

    # Format the results with usage percentages for better readability
    formatted_results = {}
    for key, value in results.items():
        if isinstance(value, dict) and "Max" in value and "Remaining" in value:
            used = value["Max"] - value["Remaining"]
            percentage = (used / value["Max"] * 100) if value["Max"] > 0 else 0
            formatted_results[key] = {
                "Max": value["Max"],
                "Used": used,
                "Remaining": value["Remaining"],
                "UsagePercentage": f"{percentage:.2f}%",
            }
        else:
            formatted_results[key] = value

    response: ToolResponse = {"success": True, "data": formatted_results, "error": None}

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def get_contact_by_phone(
    client: Salesforce, token: dict, phone_number: str, custom_fields: dict
):
    """Retrieve contact details by phone number."""
    # Format phone number query
    query = f"SELECT Id, FirstName, LastName, Email, Phone, AccountId, Account.Name FROM Contact WHERE Phone = '{phone_number}' OR MobilePhone = '{phone_number}' LIMIT 1"
    results = client.query_all(query)

    response: ToolResponse = {"success": False, "data": None, "error": None}

    if (
        results
        and results.get("totalSize", 0) > 0
        and results.get("records")
        and len(results.get("records", [])) > 0
    ):
        record = results["records"][0]
        contact_data = {
            "id": record.get("Id"),
            "first_name": record.get("FirstName"),
            "last_name": record.get("LastName"),
            "email": record.get("Email"),
            "phone": record.get("Phone"),
            "account_id": record.get("AccountId"),
            "account_name": (record.get("Account") or {}).get("Name"),
            "url": f"{token.get('instance_url', '')}/lightning/r/Contact/{record.get('Id')}/view",
        }

        # Process custom fields if any
        if custom_fields:
            for field_name, field_config in custom_fields.items():
                if field_name.startswith("Contact.") and field_name[8:] in record:
                    contact_data[field_name.lower()] = record.get(field_name[8:])

        response["success"] = True
        response["data"] = contact_data
    else:
        response["error"] = f"No contact found with phone number: {phone_number}"

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def get_contact_by_email(
    client: Salesforce, token: dict, email: str, custom_fields: dict
):
    """Retrieve contact details by email address."""
    query = f"SELECT Id, FirstName, LastName, Email, Phone, AccountId, Account.Name FROM Contact WHERE Email = '{email}' LIMIT 1"
    results = client.query_all(query)

    response: ToolResponse = {"success": False, "data": None, "error": None}

    if (
        results
        and results.get("totalSize", 0) > 0
        and results.get("records")
        and len(results.get("records", [])) > 0
    ):
        record = results["records"][0]
        contact_data = {
            "id": record.get("Id"),
            "first_name": record.get("FirstName"),
            "last_name": record.get("LastName"),
            "email": record.get("Email"),
            "phone": record.get("Phone"),
            "account_id": record.get("AccountId"),
            "account_name": (record.get("Account") or {}).get("Name"),
            "url": f"{token.get('instance_url', '')}/lightning/r/Contact/{record.get('Id')}/view",
        }

        # Process custom fields if any
        if custom_fields:
            for field_name, field_config in custom_fields.items():
                if field_name.startswith("Contact.") and field_name[8:] in record:
                    contact_data[field_name.lower()] = record.get(field_name[8:])

        response["success"] = True
        response["data"] = contact_data
    else:
        response["error"] = f"No contact found with email: {email}"

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def get_contact_by_id(
    client: Salesforce, token: dict, contact_id: str, custom_fields: dict
):
    """Retrieve contact details by Salesforce ID."""
    query = f"SELECT Id, FirstName, LastName, Email, Phone, AccountId, Account.Name FROM Contact WHERE Id = '{contact_id}'"
    results = client.query_all(query)

    response: ToolResponse = {"success": False, "data": None, "error": None}

    if (
        results
        and results.get("totalSize", 0) > 0
        and results.get("records")
        and len(results.get("records", [])) > 0
    ):
        record = results["records"][0]
        contact_data = {
            "id": record.get("Id"),
            "first_name": record.get("FirstName"),
            "last_name": record.get("LastName"),
            "email": record.get("Email"),
            "phone": record.get("Phone"),
            "account_id": record.get("AccountId"),
            "account_name": (record.get("Account") or {}).get("Name"),
            "url": f"{token.get('instance_url', '')}/lightning/r/Contact/{record.get('Id')}/view",
        }

        # Process custom fields if any
        if custom_fields:
            for field_name, field_config in custom_fields.items():
                if field_name.startswith("Contact.") and field_name[8:] in record:
                    contact_data[field_name.lower()] = record.get(field_name[8:])

        response["success"] = True
        response["data"] = contact_data
    else:
        response["error"] = f"No contact found with ID: {contact_id}"

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def create_contact(
    client: Salesforce, token: dict, contact_data: dict, custom_fields: dict
):
    """Create a new contact in Salesforce and return the full contact details."""
    # Create the contact
    results = client.Contact.create(contact_data)

    # Format response in Go schema
    response: ToolResponse = {"success": False, "data": None, "error": None}

    # Check if creation was successful and get ID
    if (
        results
        and isinstance(results, dict)
        and results.get("id")
        and results.get("success", False)
    ):
        contact_id = results.get("id")

        # Now call the same logic as get_contact_by_id to retrieve full details
        query = f"SELECT Id, FirstName, LastName, Email, Phone, AccountId, Account.Name FROM Contact WHERE Id = '{contact_id}'"
        contact_results = client.query_all(query)

        if (
            contact_results
            and contact_results.get("totalSize", 0) > 0
            and contact_results.get("records")
            and len(contact_results.get("records", [])) > 0
        ):
            record = contact_results["records"][0]
            contact_data = {
                "id": record.get("Id"),
                "first_name": record.get("FirstName"),
                "last_name": record.get("LastName"),
                "email": record.get("Email"),
                "phone": record.get("Phone"),
                "account_id": record.get("AccountId"),
                "account_name": (record.get("Account") or {}).get("Name"),
                "url": f"{token.get('instance_url', '')}/lightning/r/Contact/{record.get('Id')}/view",
                "creation_status": "success",
            }

            # Process custom fields if any
            if custom_fields:
                for field_name, field_config in custom_fields.items():
                    if field_name.startswith("Contact.") and field_name[8:] in record:
                        contact_data[field_name.lower()] = record.get(field_name[8:])

            response["success"] = True
            response["data"] = contact_data
        else:
            response["error"] = "Contact created but unable to retrieve details"
            response["success"] = True  # Still successful creation
    else:
        response["error"] = "Failed to create contact"
        if isinstance(results, dict) and results.get("errors"):
            response["error"] = str(results.get("errors"))

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def update_contact(
    client: Salesforce,
    token: dict,
    contact_id: str,
    contact_data: dict,
    custom_fields: dict,
):
    """Update an existing contact in Salesforce and return the full contact details."""
    # Update the contact
    results = client.Contact.update(contact_id, contact_data)

    # Format response in Go schema
    response: ToolResponse = {"success": False, "data": None, "error": None}

    # Check if update was successful
    if (
        results == 204
        or results == 201
        or results == 200
        or (isinstance(results, dict) and results.get("success", False))
    ):
        # Now call the same logic as get_contact_by_id to retrieve full details
        query = f"SELECT Id, FirstName, LastName, Email, Phone, AccountId, Account.Name FROM Contact WHERE Id = '{contact_id}'"
        contact_results = client.query_all(query)

        if (
            contact_results
            and contact_results.get("totalSize", 0) > 0
            and contact_results.get("records")
            and len(contact_results.get("records", [])) > 0
        ):
            record = contact_results["records"][0]
            contact_data = {
                "id": record.get("Id"),
                "first_name": record.get("FirstName"),
                "last_name": record.get("LastName"),
                "email": record.get("Email"),
                "phone": record.get("Phone"),
                "account_id": record.get("AccountId"),
                "account_name": (record.get("Account") or {}).get("Name"),
                "url": f"{token.get('instance_url', '')}/lightning/r/Contact/{record.get('Id')}/view",
                "update_status": "success",
            }

            # Process custom fields if any
            if custom_fields:
                for field_name, field_config in custom_fields.items():
                    if field_name.startswith("Contact.") and field_name[8:] in record:
                        contact_data[field_name.lower()] = record.get(field_name[8:])

            response["success"] = True
            response["data"] = contact_data
        else:
            response["error"] = "Contact updated but unable to retrieve details"
            response["success"] = True  # Still successful update
    else:
        response["error"] = "Failed to update contact"
        if isinstance(results, dict) and results.get("errors"):
            response["error"] = str(results.get("errors"))

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def create_lead(
    client: Salesforce, token: dict, lead_data: dict, custom_fields: dict
):
    """Create a new lead in Salesforce."""
    try:
        results = client.Lead.create(lead_data)

        response: ToolResponse = {"success": True, "data": results, "error": None}
    except Exception as e:
        response = {"success": False, "data": None, "error": str(e)}

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def get_case_by_id(
    client: Salesforce, token: dict, case_id: str, custom_fields: dict
):
    """Retrieve case details by Salesforce ID."""
    response: ToolResponse = {"success": False, "data": None, "error": None}

    try:
        query = f"SELECT Id, CaseNumber, Subject, Description, Status, Priority, ContactId, Contact.Name, CreatedDate, LastModifiedDate FROM Case WHERE Id = '{case_id}'"
        results = client.query_all(query)

        # Process custom fields if any
        if results and results.get("totalSize", 0) > 0 and results.get("records"):
            for record in results.get("records", []):
                if record:
                    for field_name, field_config in custom_fields.items():
                        if field_name.startswith("Case.") and field_name[5:] in record:
                            field_value = record.get(field_name[5:])
                            # Apply any transformation from field_config if needed

        if (
            results
            and results.get("totalSize", 0) > 0
            and results.get("records")
            and len(results.get("records", [])) > 0
        ):
            record = results["records"][0]
            case_data = {
                "id": record.get("Id"),
                "case_number": record.get("CaseNumber"),
                "subject": record.get("Subject"),
                "description": record.get("Description"),
                "status": record.get("Status"),
                "priority": record.get("Priority"),
                "contact_id": record.get("ContactId"),
                "contact_name": (record.get("Contact") or {}).get("Name"),
                "created_date": record.get("CreatedDate"),
                "updated_date": record.get("LastModifiedDate"),
                "url": f"{token.get('instance_url', '')}/lightning/r/Case/{record.get('Id')}/view",
            }
            response["success"] = True
            response["data"] = case_data
        else:
            response["error"] = f"No case found with ID: {case_id}"
    except Exception as e:
        response["error"] = str(e)

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def get_recent_cases(
    client: Salesforce, token: dict, contact_id: str, limit: int, custom_fields: dict
):
    """Retrieve recent cases for a contact."""
    query = f"SELECT Id, CaseNumber, Subject, Description, Status, Priority, ContactId, Contact.Name, CreatedDate, LastModifiedDate FROM Case WHERE ContactId = '{contact_id}' ORDER BY CreatedDate DESC LIMIT {limit}"
    results = client.query_all(query)

    # Format response in Go schema
    response: ToolResponse = {"success": False, "data": None, "error": None}

    # Process custom fields if any
    if results and results.get("totalSize", 0) > 0 and results.get("records"):
        for record in results.get("records", []):
            if record:
                for field_name, field_config in custom_fields.items():
                    if field_name.startswith("Case.") and field_name[5:] in record:
                        field_value = record.get(field_name[5:])
                        # Apply any transformation from field_config if needed

    # Create explicitly typed dictionary with list matching CrmContactSummary structure
    cases_list = []

    if results and results.get("totalSize", 0) > 0 and results.get("records"):
        for record in results.get("records", []):
            # Format according to Go's CrmContactSummary structure
            formatted_case = {
                "id": record.get("Id"),
                "status": record.get("Status"),
                "created_date": record.get("CreatedDate"),
                "updated_date": record.get("LastModifiedDate"),
                "subject": record.get("Subject"),
                "description": record.get("Description"),
                "url": f"{token.get('instance_url', '')}/lightning/r/Case/{record.get('Id')}/view",
                # Additional fields from our implementation
                "case_number": record.get("CaseNumber"),
                "priority": record.get("Priority"),
                "contact_id": record.get("ContactId"),
                "contact_name": (record.get("Contact") or {}).get("Name"),
            }
            cases_list.append(formatted_case)

        response["success"] = True
        response["data"] = {"cases": cases_list}
    else:
        response["error"] = f"No cases found for contact ID: {contact_id}"

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def create_case(
    client: Salesforce, token: dict, case_data: dict, custom_fields: dict
):
    """Create a new case in Salesforce."""
    # Format response in Go schema
    response: ToolResponse = {"success": False, "data": None, "error": None}

    # Process custom fields
    if custom_fields:
        for field_name, field_config in custom_fields.items():
            if field_name.startswith("Case.") and field_name[5:] in case_data:
                # Apply any transformation from field_config if needed
                pass

    try:
        results = client.Case.create(case_data)

        if (
            results
            and isinstance(results, dict)
            and results.get("id")
            and results.get("success", False)
        ):
            response["success"] = True
            response["data"] = {"id": results.get("id"), "creation_status": "success"}
        else:
            response["error"] = "Failed to create case"
            if isinstance(results, dict) and results.get("errors"):
                response["error"] = str(results.get("errors"))
    except Exception as e:
        response["error"] = str(e)

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def update_case(
    client: Salesforce, token: dict, case_id: str, case_data: dict, custom_fields: dict
):
    """Update an existing case in Salesforce."""
    # Format response in Go schema
    response: ToolResponse = {"success": False, "data": None, "error": None}

    # Process custom fields
    if custom_fields:
        for field_name, field_config in custom_fields.items():
            if field_name.startswith("Case.") and field_name[5:] in case_data:
                # Apply any transformation from field_config if needed
                pass

    try:
        results = client.Case.update(case_id, case_data)

        # Check successful status codes
        if (
            results == 204
            or results == 201
            or results == 200
            or (isinstance(results, dict) and results.get("success", False))
        ):
            response["success"] = True
            response["data"] = {"id": case_id, "update_status": "success"}
        else:
            response["error"] = "Failed to update case"
            if isinstance(results, dict) and results.get("errors"):
                response["error"] = str(results.get("errors"))
    except Exception as e:
        response["error"] = str(e)

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def get_cases_by_phone(
    client: Salesforce, token: dict, phone_number: str, limit: int, custom_fields: dict
):
    """Retrieve cases related to a phone number."""
    # Format response in Go schema
    response: ToolResponse = {"success": False, "data": None, "error": None}

    # First, find contacts with the given phone number
    contact_query = f"SELECT Id FROM Contact WHERE Phone = '{phone_number}' OR MobilePhone = '{phone_number}'"
    contact_results = client.query_all(contact_query)

    if contact_results["totalSize"] == 0:
        response["error"] = f"No contacts found with phone number: {phone_number}"
        return [
            types.TextContent(
                type="text",
                text=json.dumps(response),
            )
        ]

    # Create a list of contact IDs for the query
    contact_ids = []
    for record in contact_results.get("records", []):
        contact_ids.append(f"'{record.get('Id')}'")

    contact_ids_str = ", ".join(contact_ids)

    # Query cases related to these contacts
    case_query = f"SELECT Id, CaseNumber, Subject, Description, Status, Priority, ContactId, Contact.Name, CreatedDate, LastModifiedDate FROM Case WHERE ContactId IN ({contact_ids_str}) ORDER BY CreatedDate DESC LIMIT {limit}"
    results = client.query_all(case_query)

    # Process custom fields if any
    if results and results.get("totalSize", 0) > 0 and results.get("records"):
        for record in results.get("records", []):
            if record:
                for field_name, field_config in custom_fields.items():
                    if field_name.startswith("Case.") and field_name[5:] in record:
                        field_value = record.get(field_name[5:])
                        # Apply any transformation from field_config if needed

    # Create explicitly typed dictionary with list matching CrmContactSummary structure
    cases_list = []

    if results and results.get("totalSize", 0) > 0 and results.get("records"):
        for record in results.get("records", []):
            # Format according to Go's CrmContactSummary structure
            formatted_case = {
                "id": record.get("Id"),
                "status": record.get("Status"),
                "created_date": record.get("CreatedDate"),
                "updated_date": record.get("LastModifiedDate"),
                "subject": record.get("Subject"),
                "description": record.get("Description"),
                "url": f"{token.get('instance_url', '')}/lightning/r/Case/{record.get('Id')}/view",
                # Additional fields from our implementation
                "case_number": record.get("CaseNumber"),
                "priority": record.get("Priority"),
                "contact_id": record.get("ContactId"),
                "contact_name": (record.get("Contact") or {}).get("Name"),
            }
            cases_list.append(formatted_case)

        response["success"] = True
        response["data"] = {"cases": cases_list}
    else:
        response["error"] = (
            f"No cases found for contacts with phone number: {phone_number}"
        )

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]


async def get_cases_by_email(
    client: Salesforce, token: dict, email: str, limit: int, custom_fields: dict
):
    """Retrieve cases related to an email address."""
    # Format response in Go schema
    response: ToolResponse = {"success": False, "data": None, "error": None}

    # First, find contacts with the given email
    contact_query = f"SELECT Id FROM Contact WHERE Email = '{email}'"
    contact_results = client.query_all(contact_query)

    if contact_results["totalSize"] == 0:
        response["error"] = f"No contacts found with email: {email}"
        return [
            types.TextContent(
                type="text",
                text=json.dumps(response),
            )
        ]

    # Create a list of contact IDs for the query
    contact_ids = []
    for record in contact_results.get("records", []):
        contact_ids.append(f"'{record.get('Id')}'")

    contact_ids_str = ", ".join(contact_ids)

    # Query cases related to these contacts
    case_query = f"SELECT Id, CaseNumber, Subject, Description, Status, Priority, ContactId, Contact.Name, CreatedDate, LastModifiedDate FROM Case WHERE ContactId IN ({contact_ids_str}) ORDER BY CreatedDate DESC LIMIT {limit}"
    results = client.query_all(case_query)

    # Process custom fields if any
    if results and results.get("totalSize", 0) > 0 and results.get("records"):
        for record in results.get("records", []):
            if record:
                for field_name, field_config in custom_fields.items():
                    if field_name.startswith("Case.") and field_name[5:] in record:
                        field_value = record.get(field_name[5:])
                        # Apply any transformation from field_config if needed

    # Create explicitly typed dictionary with list matching CrmContactSummary structure
    cases_list = []

    if results and results.get("totalSize", 0) > 0 and results.get("records"):
        for record in results.get("records", []):
            # Format according to Go's CrmContactSummary structure
            formatted_case = {
                "id": record.get("Id"),
                "status": record.get("Status"),
                "created_date": record.get("CreatedDate"),
                "updated_date": record.get("LastModifiedDate"),
                "subject": record.get("Subject"),
                "description": record.get("Description"),
                "url": f"{token.get('instance_url', '')}/lightning/r/Case/{record.get('Id')}/view",
                # Additional fields from our implementation
                "case_number": record.get("CaseNumber"),
                "priority": record.get("Priority"),
                "contact_id": record.get("ContactId"),
                "contact_name": (record.get("Contact") or {}).get("Name"),
            }
            cases_list.append(formatted_case)

        response["success"] = True
        response["data"] = {"cases": cases_list}
    else:
        response["error"] = f"No cases found for contacts with email: {email}"

    return [
        types.TextContent(
            type="text",
            text=json.dumps(response),
        )
    ]
