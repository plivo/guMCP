import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

project_root = os.path.abspath(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "src"))

from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.types import (
    EmbeddedResource,
    ImageContent,
    Resource,
    TextContent,
    Tool,
)

from src.utils.shopify.graphql_schemas import (
    CANCEL_ORDER_GRAPHQL_MUTATION,
    GET_CONTACT_BY_EMAIL_GRAPHQL_QUERY,
    GET_CONTACT_BY_ID_GRAPHQL_QUERY,
    GET_CONTACT_BY_PHONE_GRAPHQL_QUERY,
    GET_ORDER_BY_NUMBER_GRAPHQL_QUERY,
    GET_RECENT_ORDERS_GRAPHQL_QUERY,
    INVENTORY_ADJUST_GRAPHQL_MUTATION,
    INVENTORY_ITEM_UPDATE_GRAPHQL_MUTATION,
    INVENTORY_LEVEL_GRAPHQL_QUERY,
    LOCATIONS_GRAPHQL_QUERY,
    PRODUCT_CREATE_GRAPHQL_MUTATION,
    PRODUCT_DELETE_GRAPHQL_MUTATION,
    PRODUCT_GRAPHQL_QUERY,
    PRODUCTS_GRAPHQL_QUERY,
    REFUND_CREATE_GRAPHQL_MUTATION,
    SHOP_DETAILS_GRAPHQL_QUERY,
    VARIANT_INVENTORY_ITEM_GRAPHQL_QUERY,
)
from src.utils.shopify.util import get_credentials, get_service_config
from src.utils.utils import ToolResponse

SERVICE_NAME = Path(__file__).parent.name


def authenticate_and_save_credentials(user_id, scopes=None):
    if scopes is None:
        scopes = [
            "read_products",
            "write_products",
            "read_inventory",
            "write_inventory",
            "read_locations",
        ]

    from src.utils.shopify.util import authenticate_and_save_credentials as auth_save

    return auth_save(user_id, SERVICE_NAME, scopes)


async def execute_graphql_query(user_id, query, variables=None, api_key=None):
    access_token = await get_credentials(user_id, SERVICE_NAME, api_key)

    config = await get_service_config(user_id, SERVICE_NAME, api_key)
    custom_subdomain = config.get("custom_subdomain")
    api_version = config.get("api_version", "2023-10")

    if not custom_subdomain:
        raise ValueError("Missing custom_subdomain in Shopify configuration")

    graphql_url = (
        f"https://{custom_subdomain}.myshopify.com/admin/api/{api_version}/graphql.json"
    )

    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": access_token,
    }

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    async with httpx.AsyncClient() as client:
        response = await client.post(
            graphql_url, json=payload, headers=headers, timeout=30.0
        )

        result = {"_status_code": response.status_code}
        try:
            response_data = response.json()
            result.update(response_data)
        except Exception:
            result["text"] = response.text

        return result


def extract_node_data(response: dict[str, Any]):
    """
    Simply returns the data from the response without any transformations
    """

    if not response or "data" not in response:
        return None

    return response.get("data")


async def calculate_refund(variables: Dict[str, Any]):
    """
    Calculate refund details using Shopify's REST API
    Returns calculated refund information including transaction amounts
    """
    user_id = variables["user_id"]
    order_id = variables["order_id"]
    line_item_id = str(variables["line_item_id"])
    quantity = variables["quantity"]
    restock_type = variables["restock_type"]
    api_key = variables["api_key"]

    access_token = await get_credentials(user_id, SERVICE_NAME, api_key)

    config = await get_service_config(user_id, SERVICE_NAME, api_key)
    custom_subdomain = config.get("custom_subdomain")
    api_version = config.get("api_version", "2023-10")

    if not custom_subdomain:
        raise ValueError("Missing custom_subdomain in Shopify configuration")

    calculate_refund_url = f"https://{custom_subdomain}.myshopify.com/admin/api/{api_version}/orders/{order_id}/refunds/calculate.json"

    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": access_token,
    }

    # Convert restock_type to lowercase for the REST API
    restock_type_lower = restock_type.lower()

    payload = {
        "refund": {
            "shipping": {
                "full_refund": True,
            },
            "refund_line_items": [
                {
                    "line_item_id": line_item_id,
                    "quantity": quantity,
                    "restock_type": restock_type_lower,
                }
            ],
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            calculate_refund_url, json=payload, headers=headers, timeout=30.0
        )

        if response.status_code != 200:
            return {
                "_status_code": response.status_code,
                "error": f"Failed to calculate refund: {response.text}",
            }

        try:
            response_data = response.json()
            return {
                "_status_code": response.status_code,
                **response_data,
            }
        except Exception:
            return {
                "_status_code": response.status_code,
                "error": f"Failed to parse response: {response.text}",
            }


def format_shopify_id(id_value, resource_type):
    if not id_value.startswith("gid://"):
        return f"gid://shopify/{resource_type}/{id_value}"
    return id_value


def create_server(user_id, api_key=None):
    server = Server("shopify-server")
    server.user_id = user_id
    server.api_key = api_key

    @server.list_resources()
    async def handle_list_resources(
        cursor: Optional[str] = None,
    ) -> List[Resource]:
        return []

    @server.list_tools()
    async def handle_list_tools() -> List[Tool]:
        return [
            Tool(
                name="get_shop_details",
                description="Gets the details of a shop in Shopify",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="create_product",
                description="Creates a product on Shopify",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "description": "The name for the product that displays to customers",
                        },
                        "descriptionHtml": {
                            "type": "string",
                            "description": "The description of the product, with HTML tags",
                        },
                        "vendor": {
                            "type": "string",
                            "description": "The name of the product's vendor",
                        },
                        "productType": {
                            "type": "string",
                            "description": "The product type that merchants define",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "A list of searchable keywords associated with the product",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["DRAFT", "ACTIVE", "ARCHIVED"],
                            "description": "The product status, which controls visibility across all sales channels",
                        },
                        "handle": {
                            "type": "string",
                            "description": "A unique, human-readable string of the product's title used in the online store URL",
                        },
                        "giftCard": {
                            "type": "boolean",
                            "description": "Whether the product is a gift card",
                        },
                        "productOptions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {
                                        "type": "string",
                                        "description": "The name of the option (e.g., 'Color', 'Size')",
                                    },
                                    "values": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "properties": {"name": {"type": "string"}},
                                        },
                                        "description": "The values for the option (e.g., ['Red', 'Blue'] for a 'Color' option)",
                                    },
                                },
                                "required": ["name", "values"],
                            },
                            "description": "A list of product options and option values (max 3 options)",
                        },
                        "requiresSellingPlan": {
                            "type": "boolean",
                            "description": "Whether the product can only be purchased with a selling plan (subscription)",
                        },
                        "seo": {
                            "type": "object",
                            "properties": {
                                "title": {
                                    "type": "string",
                                    "description": "SEO title",
                                },
                                "description": {
                                    "type": "string",
                                    "description": "SEO description",
                                },
                            },
                            "description": "The SEO title and description for the product",
                        },
                        "metafields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "namespace": {
                                        "type": "string",
                                        "description": "Metafield namespace",
                                    },
                                    "key": {
                                        "type": "string",
                                        "description": "Metafield key",
                                    },
                                    "value": {
                                        "type": "string",
                                        "description": "Metafield value",
                                    },
                                    "type": {
                                        "type": "string",
                                        "description": "Metafield type",
                                    },
                                },
                                "required": ["namespace", "key", "value", "type"],
                            },
                            "description": "Custom fields to associate with the product",
                        },
                        "templateSuffix": {
                            "type": "string",
                            "description": "The theme template used when customers view the product in a store",
                        },
                    },
                    "required": ["title"],
                },
            ),
            Tool(
                name="get_products",
                description="Retrieves a list of products from Shopify",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "first": {
                            "type": "integer",
                            "description": "The first n elements from the paginated list (default: 10)",
                        },
                        "query": {
                            "type": "string",
                            "description": "A search query to filter products. Supports Shopify's search syntax with filters such as title:, handle:, vendor:, product_type:, status: etc.",
                        },
                        "reverse": {
                            "type": "boolean",
                            "description": "Reverse the order of the underlying list",
                        },
                        "sortKey": {
                            "type": "string",
                            "enum": [
                                "CREATED_AT",
                                "ID",
                                "INVENTORY_TOTAL",
                                "PRODUCT_TYPE",
                                "PUBLISHED_AT",
                                "RELEVANCE",
                                "TITLE",
                                "UPDATED_AT",
                                "VENDOR",
                            ],
                            "description": "Sort the underlying list by a key",
                        },
                        "after": {
                            "type": "string",
                            "description": "Return items after this cursor",
                        },
                        "before": {
                            "type": "string",
                            "description": "Return items before this cursor",
                        },
                        "last": {
                            "type": "integer",
                            "description": "The last n elements from the paginated list",
                        },
                        "savedSearchId": {
                            "type": "string",
                            "description": "The ID of a saved search to use as the query",
                        },
                    },
                },
            ),
            Tool(
                name="get_product",
                description="Retrieves a single product from Shopify by product ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "string",
                            "description": "ID of the product to retrieve",
                        },
                    },
                    "required": ["product_id"],
                },
            ),
            Tool(
                name="delete_product",
                description="Deletes a product from Shopify, including all associated variants and media",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "The ID of the product to delete",
                        },
                    },
                    "required": ["id"],
                },
            ),
            Tool(
                name="get_inventory_level",
                description="Gets the inventory level for a specific inventory item",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "inventory_item_id": {
                            "type": "string",
                            "description": "ID of the inventory item",
                        },
                        "location_id": {
                            "type": "string",
                            "description": "ID of the location (optional)",
                        },
                    },
                    "required": ["inventory_item_id"],
                },
            ),
            Tool(
                name="adjust_inventory",
                description="Adjusts inventory levels for a specific inventory item",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "inventory_level_id": {
                            "type": "string",
                            "description": "ID of the inventory level to adjust",
                        },
                        "quantity_adjustment": {
                            "type": "integer",
                            "description": "Amount to adjust inventory quantity by (positive or negative)",
                        },
                    },
                    "required": [
                        "inventory_level_id",
                        "quantity_adjustment",
                    ],
                },
            ),
            Tool(
                name="update_inventory_tracking",
                description="Enable or disable inventory tracking for a specific inventory item",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "inventory_item_id": {
                            "type": "string",
                            "description": "ID of the inventory item to update",
                        },
                        "tracked": {
                            "type": "boolean",
                            "description": "Whether to enable (true) or disable (false) inventory tracking",
                        },
                    },
                    "required": [
                        "inventory_item_id",
                        "tracked",
                    ],
                },
            ),
            Tool(
                name="get_variant_inventory_item",
                description="Gets the inventory item ID for a specific product variant",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "variant_id": {
                            "type": "string",
                            "description": "ID of the product variant",
                        },
                    },
                    "required": ["variant_id"],
                },
            ),
            Tool(
                name="cancel_order",
                description="Cancels an order in Shopify with options for refund and restocking",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID of the order to cancel",
                        },
                        "refund": {
                            "type": "boolean",
                            "description": "Whether to refund the order",
                        },
                        "restock": {
                            "type": "boolean",
                            "description": "Whether to restock the items",
                        },
                        "staffNote": {
                            "type": "string",
                            "description": "Staff note explaining the cancellation",
                        },
                        "reason": {
                            "type": "string",
                            "enum": [
                                "CUSTOMER",
                                "INVENTORY",
                                "FRAUD",
                                "DECLINED",
                                "OTHER",
                                "STAFF",
                            ],
                            "description": "Reason for cancellation",
                        },
                    },
                    "required": ["id", "refund", "restock", "staffNote", "reason"],
                },
            ),
            Tool(
                name="get_contact_by_email",
                description="Retrieves a customer by their email address",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "Email address of the customer to retrieve",
                        },
                    },
                    "required": ["email"],
                },
            ),
            Tool(
                name="get_contact_by_id",
                description="Retrieves a customer by their Shopify ID",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "ID of the customer to retrieve",
                        },
                    },
                    "required": ["id"],
                },
            ),
            Tool(
                name="get_contact_by_phone",
                description="Retrieves a customer by their phone number",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "phone": {
                            "type": "string",
                            "description": "Phone number of the customer to retrieve",
                        },
                    },
                    "required": ["phone"],
                },
            ),
            Tool(
                name="get_order_by_number",
                description="Retrieves an order by its order number",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Order number (e.g. #1001)",
                        },
                    },
                    "required": ["name"],
                },
            ),
            Tool(
                name="get_recent_orders",
                description="Retrieves recent orders for a specific customer",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "customerId": {
                            "type": "string",
                            "description": "ID of the customer whose orders to retrieve",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of orders to retrieve",
                        },
                    },
                    "required": ["customerId", "limit"],
                },
            ),
            Tool(
                name="get_orders_by_phone_number",
                description="Retrieves orders associated with a specific phone number. First finds a customer by phone number, then retrieves their orders. Returns customer details along with orders or appropriate error messages if no customer is found.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "phone": {
                            "type": "string",
                            "description": "Phone number to search for customer (include country code for best results)",
                        },
                        "first": {
                            "type": "integer",
                            "description": "Maximum number of orders to retrieve (defaults to 10)",
                        },
                    },
                    "required": ["phone"],
                },
            ),
            Tool(
                name="get_orders_by_email",
                description="Retrieves orders associated with a specific email address. First finds a customer by email, then retrieves their orders. Returns customer details along with orders or appropriate error messages if no customer is found.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "Email address to search for customer",
                        },
                        "first": {
                            "type": "integer",
                            "description": "Maximum number of orders to retrieve (defaults to 10)",
                        },
                    },
                    "required": ["email"],
                },
            ),
            Tool(
                name="get_locations",
                description="Retrieves a list of locations from the Shopify store",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "first": {
                            "type": "integer",
                            "description": "Number of locations to retrieve (defaults to 10)",
                        },
                    },
                },
            ),
            Tool(
                name="calculate_refund",
                description="Calculates refund details for a line item in an order",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "orderId": {
                            "type": "string",
                            "description": "ID of the order to calculate refund for",
                        },
                        "lineItemId": {
                            "type": "string",
                            "description": "ID of the line item to refund",
                        },
                        "quantity": {
                            "type": "integer",
                            "description": "Quantity to refund (defaults to 1)",
                        },
                        "restockType": {
                            "type": "string",
                            "enum": ["NO_RESTOCK", "CANCEL", "RETURN"],
                            "description": "How to handle inventory restocking",
                        },
                    },
                    "required": ["orderId", "lineItemId", "restockType"],
                },
            ),
            Tool(
                name="create_refund",
                description="Creates a refund for a specific line item in an order",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "orderId": {
                            "type": "string",
                            "description": "ID of the order to refund",
                        },
                        "lineItemId": {
                            "type": "string",
                            "description": "ID of the line item to refund",
                        },
                        "quantity": {
                            "type": "integer",
                            "description": "Quantity to refund (defaults to 1)",
                        },
                        "restockType": {
                            "type": "string",
                            "enum": ["NO_RESTOCK", "CANCEL", "RETURN"],
                            "description": "How to handle inventory restocking",
                        },
                        "locationId": {
                            "type": "string",
                            "description": "ID of the location to restock inventory (required if restockType is not NO_RESTOCK)",
                        },
                        "note": {
                            "type": "string",
                            "description": "Note for the refund",
                        },
                        "transactionAmount": {
                            "type": "string",
                            "description": "Amount to refund (must match the amount calculated by Shopify)",
                        },
                        "transactionGateway": {
                            "type": "string",
                            "description": "Payment gateway for the refund",
                        },
                        "transactionKind": {
                            "type": "string",
                            "enum": ["REFUND", "VOID"],
                            "description": "Type of transaction",
                        },
                        "transactionParentId": {
                            "type": "string",
                            "description": "ID of the parent transaction",
                        },
                    },
                    "required": [
                        "orderId",
                        "lineItemId",
                        "restockType",
                        "note",
                        "transactionAmount",
                        "transactionGateway",
                        "transactionKind",
                        "transactionParentId",
                    ],
                },
            ),
        ]

    @server.call_tool()
    async def handle_call_tool(
        name: str, arguments: Dict[str, Any] | None
    ) -> List[TextContent | ImageContent | EmbeddedResource]:
        endpoints = {
            "get_products": {
                "query": PRODUCTS_GRAPHQL_QUERY,
                "variables": lambda args: {
                    "first": args.get("first", 10),
                    "query": args.get("query", ""),
                    "sortKey": args.get("sortKey", "ID"),
                    "reverse": args.get("reverse", False),
                    "after": args.get("after"),
                    "before": args.get("before"),
                    "last": args.get("last"),
                    "savedSearchId": args.get("savedSearchId"),
                },
            },
            "get_product": {
                "query": PRODUCT_GRAPHQL_QUERY,
                "variables": lambda args: {
                    "id": format_shopify_id(args["product_id"], "Product")
                },
            },
            "get_shop_details": {
                "query": SHOP_DETAILS_GRAPHQL_QUERY,
                "variables": lambda _: {},
            },
            "create_product": {
                "query": PRODUCT_CREATE_GRAPHQL_MUTATION,
                "variables": lambda args: {
                    "input": {
                        **args,
                        "bodyHtml": args.get("descriptionHtml"),
                    }
                },
            },
            "delete_product": {
                "query": PRODUCT_DELETE_GRAPHQL_MUTATION,
                "variables": lambda args: {
                    "input": {"id": format_shopify_id(args["id"], "Product")}
                },
            },
            "get_inventory_level": {
                "query": INVENTORY_LEVEL_GRAPHQL_QUERY,
                "variables": lambda args: {
                    "inventoryItemId": format_shopify_id(
                        args["inventory_item_id"], "InventoryItem"
                    ),
                    "locationId": (
                        format_shopify_id(args.get("location_id", "1"), "Location")
                        if args.get("location_id")
                        else None
                    ),
                },
            },
            "adjust_inventory": {
                "query": INVENTORY_ADJUST_GRAPHQL_MUTATION,
                "variables": lambda args: {
                    "input": {
                        "inventoryLevelId": args.get("inventory_level_id"),
                        "availableDelta": args["quantity_adjustment"],
                    }
                },
            },
            "update_inventory_tracking": {
                "query": INVENTORY_ITEM_UPDATE_GRAPHQL_MUTATION,
                "variables": lambda args: {
                    "inventoryItemId": format_shopify_id(
                        args["inventory_item_id"], "InventoryItem"
                    ),
                    "tracked": args["tracked"],
                },
            },
            "get_variant_inventory_item": {
                "query": VARIANT_INVENTORY_ITEM_GRAPHQL_QUERY,
                "variables": lambda args: {
                    "variantId": format_shopify_id(args["variant_id"], "ProductVariant")
                },
            },
            "cancel_order": {
                "query": CANCEL_ORDER_GRAPHQL_MUTATION,
                "variables": lambda args: {
                    "id": format_shopify_id(args["id"], "Order"),
                    "refund": args["refund"],
                    "restock": args["restock"],
                    "staffNote": args["staffNote"],
                    "reason": args["reason"],
                },
            },
            "get_contact_by_email": {
                "query": GET_CONTACT_BY_EMAIL_GRAPHQL_QUERY,
                "variables": lambda args: {
                    "email": args["email"],
                },
            },
            "get_contact_by_id": {
                "query": GET_CONTACT_BY_ID_GRAPHQL_QUERY,
                "variables": lambda args: {
                    "id": format_shopify_id(args["id"], "Customer"),
                },
            },
            "get_contact_by_phone": {
                "query": GET_CONTACT_BY_PHONE_GRAPHQL_QUERY,
                "variables": lambda args: {
                    "phone": args["phone"],
                },
            },
            "get_order_by_number": {
                "query": GET_ORDER_BY_NUMBER_GRAPHQL_QUERY,
                "variables": lambda args: {
                    "name": args["name"],
                },
            },
            "get_recent_orders": {
                "query": GET_RECENT_ORDERS_GRAPHQL_QUERY,
                "variables": lambda args: {
                    "customerId": format_shopify_id(args["customerId"], "Customer"),
                    "limit": args["limit"],
                },
            },
            "get_orders_by_phone_number": {
                "fn": get_orders_by_phone,
                "variables": lambda args: {
                    "user_id": server.user_id,
                    "phone_number": args["phone"],
                    "first": args.get("first", 10),
                    "api_key": server.api_key,
                },
            },
            "get_orders_by_email": {
                "fn": get_orders_by_email,
                "variables": lambda args: {
                    "user_id": server.user_id,
                    "email": args["email"],
                    "first": args.get("first", 10),
                    "api_key": server.api_key,
                },
            },
            "get_locations": {
                "query": LOCATIONS_GRAPHQL_QUERY,
                "variables": lambda args: {
                    "first": args.get("first", 10),
                },
            },
            "calculate_refund": {
                "fn": calculate_refund,
                "variables": lambda args: {
                    "user_id": server.user_id,
                    "order_id": args["orderId"],
                    "line_item_id": args["lineItemId"],
                    "quantity": args.get("quantity", 1),
                    "restock_type": args["restockType"],
                    "api_key": server.api_key,
                },
            },
            "create_refund": {
                "query": REFUND_CREATE_GRAPHQL_MUTATION,
                "variables": lambda args: {
                    "input": {
                        "orderId": format_shopify_id(args["orderId"], "Order"),
                        "note": args["note"],
                        "refundLineItems": [
                            {
                                "lineItemId": format_shopify_id(
                                    args["lineItemId"], "LineItem"
                                ),
                                "quantity": args.get("quantity", 1),
                                "restockType": args["restockType"],
                                **(
                                    {
                                        "locationId": format_shopify_id(
                                            args["locationId"], "Location"
                                        ),
                                    }
                                    if "locationId" in args
                                    else {}
                                ),
                            }
                        ],
                        "transactions": [
                            {
                                "amount": args["transactionAmount"],
                                "gateway": args["transactionGateway"],
                                "kind": args["transactionKind"],
                                "orderId": format_shopify_id(args["orderId"], "Order"),
                                "parentId": format_shopify_id(
                                    args["transactionParentId"], "OrderTransaction"
                                ),
                            }
                        ],
                    }
                },
            },
        }

        arguments = arguments or {}

        if name in endpoints:
            endpoint_info = endpoints[name]
            try:
                variables_func = endpoint_info["variables"]
                variables = (
                    variables_func(arguments)
                    if callable(variables_func)
                    else variables_func
                )

                if "query" in endpoint_info:
                    query = endpoint_info["query"]

                    result = await execute_graphql_query(
                        server.user_id,
                        query,
                        variables=variables,
                        api_key=server.api_key,
                    )
                else:
                    fn = endpoint_info["fn"]
                    result = (
                        await fn(variables)
                        if inspect.iscoroutinefunction(fn)
                        else fn(variables)
                    )

                if "errors" not in result:
                    response = ToolResponse(
                        success=True,
                        data=extract_node_data(result),
                        error=None,
                    )
                    return [
                        TextContent(type="text", text=json.dumps(response, indent=2))
                    ]
                else:
                    response = ToolResponse(
                        success=False, data=None, error=result.get("errors")
                    )
                    return [
                        TextContent(type="text", text=json.dumps(response, indent=2))
                    ]
            except Exception as e:
                response = ToolResponse(success=False, data=None, error=str(e))
                return [TextContent(type="text", text=json.dumps(response, indent=2))]

        response = ToolResponse(
            success=False, data=None, error=f"Tool '{name}' is not yet implemented."
        )
        return [TextContent(type="text", text=json.dumps(response, indent=2))]

    return server


server = create_server


def get_initialization_options(server_instance: Server) -> InitializationOptions:
    return InitializationOptions(
        server_name=f"{SERVICE_NAME}-server",
        server_version="1.0.0",
        capabilities=server_instance.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


async def get_orders_by_email(variables: Dict[str, Any]):
    """
    Get orders for a customer identified by email.
    First finds the customer by email, then retrieves their orders.
    """
    user_id = variables["user_id"]
    email = variables["email"]
    first = variables.get("first", 10)
    api_key = variables["api_key"]

    # First find the customer by email
    customer_result = await execute_graphql_query(
        user_id,
        GET_CONTACT_BY_EMAIL_GRAPHQL_QUERY,
        variables={"email": email},
        api_key=api_key,
    )

    # Handle API errors
    if customer_result.get("_status_code", 0) != 200 or "errors" in customer_result:
        errors = customer_result.get("errors", [{"message": "Unknown error occurred"}])
        return {
            "_status_code": customer_result.get("_status_code", 500),
            "errors": errors,
        }

    # Handle case where data structure is unexpected
    if "data" not in customer_result or "customers" not in customer_result["data"]:
        return {
            "_status_code": 500,
            "errors": [{"message": "Unexpected API response structure"}],
        }

    # Handle no customers found
    customer_edges = customer_result["data"]["customers"]["edges"]
    if not customer_edges:
        return {
            "_status_code": 404,
            "errors": [{"message": f"No customer found with email: {email}"}],
        }

    # Extract customer ID
    try:
        customer = customer_edges[0]["node"]
        customer_id = customer["id"]
    except (KeyError, IndexError) as e:
        return {
            "_status_code": 500,
            "errors": [{"message": f"Error parsing customer data: {str(e)}"}],
        }

    # Now get orders for this customer
    return await execute_graphql_query(
        user_id,
        GET_RECENT_ORDERS_GRAPHQL_QUERY,
        variables={"customerId": customer_id, "limit": first},
        api_key=api_key,
    )


async def get_orders_by_phone(variables: Dict[str, Any]):
    """
    Get orders for a customer identified by phone number.
    First finds the customer by phone, then retrieves their orders.
    """
    user_id = variables["user_id"]
    phone_number = variables["phone_number"]
    first = variables.get("first", 10)
    api_key = variables["api_key"]

    # First find the customer by phone
    customer_result = await execute_graphql_query(
        user_id,
        GET_CONTACT_BY_PHONE_GRAPHQL_QUERY,
        variables={"phone": phone_number},
        api_key=api_key,
    )

    # Handle API errors
    if customer_result.get("_status_code", 0) != 200 or "errors" in customer_result:
        errors = customer_result.get("errors", [{"message": "Unknown error occurred"}])
        return {
            "_status_code": customer_result.get("_status_code", 500),
            "errors": errors,
        }

    # Handle case where data structure is unexpected
    if "data" not in customer_result or "customers" not in customer_result["data"]:
        return {
            "_status_code": 500,
            "errors": [{"message": "Unexpected API response structure"}],
        }

    # Handle no customers found
    customer_edges = customer_result["data"]["customers"]["edges"]
    if not customer_edges:
        return {
            "_status_code": 404,
            "errors": [{"message": f"No customer found with phone: {phone_number}"}],
        }

    # Extract customer ID
    try:
        customer = customer_edges[0]["node"]
        customer_id = customer["id"]
    except (KeyError, IndexError) as e:
        return {
            "_status_code": 500,
            "errors": [{"message": f"Error parsing customer data: {str(e)}"}],
        }

    # Now get orders for this customer
    return await execute_graphql_query(
        user_id,
        GET_RECENT_ORDERS_GRAPHQL_QUERY,
        variables={"customerId": customer_id, "limit": first},
        api_key=api_key,
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == "auth":
        user_id = "local"
        authenticate_and_save_credentials(user_id)
    else:
        print("Usage:")
        print("  python main.py auth - Run authentication flow for a user")
