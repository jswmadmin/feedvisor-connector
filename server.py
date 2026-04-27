#!/usr/bin/env python3
"""
Feedvisor MCP Connector  —  Full Bidirectional Access
======================================================
Connects Claude to every available Feedvisor External API endpoint:

  READ:
    list_accounts              — See all configured accounts
    get_listings               — Live Amazon listing data with rich filters
    get_listing_by_sku         — Full config for one SKU

  WRITE (live changes applied immediately in Feedvisor):
    update_listing             — Update one SKU (floor, ceiling, cost, repricer…)
    bulk_update_listings       — Update up to 1000 SKUs in one call

  REPORTS:
    request_configuration_report  — Trigger export of pricing/inventory config
    request_analytics_report      — Trigger product analytics report
    get_report_status             — Poll report completion + get download URL

Auth:     OAuth2 Client Credentials (Cognito) — per-account client_id/secret
Token:    Auto-refreshed and cached per account
Docs:     https://feedvisor.zendesk.com/hc/en-us/sections/4415936217748
"""

import os
import json
import time
import requests
from typing import Optional
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# ──────────────────────────────────────────────────────────────────────────────
# Account Registry  (all 12 JSW Media stores)
# ──────────────────────────────────────────────────────────────────────────────
ACCOUNTS: dict[str, dict] = {
    "PiercedOwlUS": {
        "account_id":    os.getenv("PIERCED_OWL_US_ACCOUNT_ID", "6872"),
        "client_id":     os.getenv("PIERCED_OWL_US_CLIENT_ID"),
        "client_secret": os.getenv("PIERCED_OWL_US_CLIENT_SECRET"),
    },
    "PiercedOwlCA": {
        "account_id":    os.getenv("PIERCED_OWL_CA_ACCOUNT_ID", "6873"),
        "client_id":     os.getenv("PIERCED_OWL_CA_CLIENT_ID"),
        "client_secret": os.getenv("PIERCED_OWL_CA_CLIENT_SECRET"),
    },
    "PiercedOwlAU": {
        "account_id":    os.getenv("PIERCED_OWL_AU_ACCOUNT_ID", "6922"),
        "client_id":     os.getenv("PIERCED_OWL_AU_CLIENT_ID"),
        "client_secret": os.getenv("PIERCED_OWL_AU_CLIENT_SECRET"),
    },
    "PiercedOwlMX": {
        "account_id":    os.getenv("PIERCED_OWL_MX_ACCOUNT_ID", "6923"),
        "client_id":     os.getenv("PIERCED_OWL_MX_CLIENT_ID"),
        "client_secret": os.getenv("PIERCED_OWL_MX_CLIENT_SECRET"),
    },
    "ArtisanOwlUS": {
        "account_id":    os.getenv("ARTISAN_OWL_US_ACCOUNT_ID", "6871"),
        "client_id":     os.getenv("ARTISAN_OWL_US_CLIENT_ID"),
        "client_secret": os.getenv("ARTISAN_OWL_US_CLIENT_SECRET"),
    },
    "ArtisanOwlCA": {
        "account_id":    os.getenv("ARTISAN_OWL_CA_ACCOUNT_ID", "6889"),
        "client_id":     os.getenv("ARTISAN_OWL_CA_CLIENT_ID"),
        "client_secret": os.getenv("ARTISAN_OWL_CA_CLIENT_SECRET"),
    },
    "ArtisanOwlMX": {
        "account_id":    os.getenv("ARTISAN_OWL_MX_ACCOUNT_ID", "6888"),
        "client_id":     os.getenv("ARTISAN_OWL_MX_CLIENT_ID"),
        "client_secret": os.getenv("ARTISAN_OWL_MX_CLIENT_SECRET"),
    },
    "AlohaEarringsUS": {
        "account_id":    os.getenv("ALOHA_EARRINGS_US_ACCOUNT_ID", "6993"),
        "client_id":     os.getenv("ALOHA_EARRINGS_US_CLIENT_ID"),
        "client_secret": os.getenv("ALOHA_EARRINGS_US_CLIENT_SECRET"),
    },
    "AlohaEarringsCA": {
        "account_id":    os.getenv("ALOHA_EARRINGS_CA_ACCOUNT_ID", "19191"),
        "client_id":     os.getenv("ALOHA_EARRINGS_CA_CLIENT_ID"),
        "client_secret": os.getenv("ALOHA_EARRINGS_CA_CLIENT_SECRET"),
    },
    "LuxilliaUS": {
        "account_id":    os.getenv("LUXILLIA_US_ACCOUNT_ID", "18654"),
        "client_id":     os.getenv("LUXILLIA_US_CLIENT_ID"),
        "client_secret": os.getenv("LUXILLIA_US_CLIENT_SECRET"),
    },
    "LuxilliaCA": {
        "account_id":    os.getenv("LUXILLIA_CA_ACCOUNT_ID", "18848"),
        "client_id":     os.getenv("LUXILLIA_CA_CLIENT_ID"),
        "client_secret": os.getenv("LUXILLIA_CA_CLIENT_SECRET"),
    },
    "ChrysalisStone": {
        "account_id":    os.getenv("CHRYSALIS_STONE_ACCOUNT_ID", "6874"),
        "client_id":     os.getenv("CHRYSALIS_STONE_CLIENT_ID"),
        "client_secret": os.getenv("CHRYSALIS_STONE_CLIENT_SECRET"),
    },
}

AUTH_URL = "https://feedvisor-auth.auth.us-east-1.amazoncognito.com/oauth2/token"
BASE_URL = "https://api-gateway.feedvisor.com"

_token_cache: dict[str, dict] = {}

mcp = FastMCP("Feedvisor")


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_token(account_name: str) -> str:
    """Return a valid bearer token, refreshing via OAuth2 if needed."""
    cached = _token_cache.get(account_name)
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["token"]

    acct = ACCOUNTS[account_name]
    if not acct.get("client_id") or not acct.get("client_secret"):
        raise ValueError(
            f"Missing credentials for '{account_name}'. Check your .env file."
        )

    resp = requests.post(
        AUTH_URL,
        data={
            "grant_type":    "client_credentials",
            "client_id":     acct["client_id"],
            "client_secret": acct["client_secret"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    _token_cache[account_name] = {
        "token":      token,
        "expires_at": time.time() + data.get("expires_in", 3600),
    }
    return token


def _headers(account_name: str) -> dict:
    return {"Authorization": f"Bearer {_get_token(account_name)}"}


def _api_get(account_name: str, path: str, params: dict = None) -> dict:
    resp = requests.get(
        f"{BASE_URL}{path}", params=params,
        headers=_headers(account_name), timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _api_post(account_name: str, path: str, payload: dict) -> dict:
    resp = requests.post(
        f"{BASE_URL}{path}", json=payload,
        headers={**_headers(account_name), "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {"status": "success"}


def _api_put(account_name: str, path: str, payload: list) -> dict:
    """PUT takes an array of listing objects (up to 1000)."""
    resp = requests.put(
        f"{BASE_URL}{path}", json=payload,
        headers={**_headers(account_name), "Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {"status": "success"}


def _validate_account(account_name: str) -> Optional[str]:
    if account_name not in ACCOUNTS:
        return (
            f"Account '{account_name}' not found. "
            f"Available: {', '.join(ACCOUNTS.keys())}"
        )
    return None


def _range(field: str, min_val, max_val, params: dict):
    if min_val is not None and max_val is not None:
        params[field] = f"[RNG:{min_val},{max_val}]"
    elif min_val is not None:
        params[field] = f"[GTE:{min_val}]"
    elif max_val is not None:
        params[field] = f"[LTE:{max_val}]"


# ──────────────────────────────────────────────────────────────────────────────
# TOOL: list_accounts
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_accounts() -> str:
    """
    List all configured Feedvisor accounts.
    Use the account_name value as the 'account_name' parameter in all other tools.
    """
    return json.dumps([
        {"account_name": name, "account_id": acct["account_id"]}
        for name, acct in ACCOUNTS.items()
    ], indent=2)


# ──────────────────────────────────────────────────────────────────────────────
# TOOL: get_listings
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_listings(
    account_name: str,
    sku: str = None,
    sku_starts_with: str = None,
    sku_contains: str = None,
    asin: str = None,
    brand: str = None,
    active: str = None,
    repricer_activated: str = None,
    repricing_strategy: str = None,
    repricing_method: str = None,
    floor_price_min: float = None,
    floor_price_max: float = None,
    ceiling_price_min: float = None,
    ceiling_price_max: float = None,
    current_price_min: float = None,
    current_price_max: float = None,
    cost_min: float = None,
    cost_max: float = None,
    available_quantity_min: float = None,
    available_quantity_max: float = None,
    page: int = 0,
) -> str:
    """
    Fetch live Amazon listings from Feedvisor for a given account.

    Returns full listing data: SKU, ASIN, price, floor/ceiling, cost, MAP,
    inventory quantities, repricer on/off, strategy, fulfillment method, vendor, etc.

    All filters are optional. Multiple filters combine with AND logic.

    Parameters:
    - account_name        : Account to query (use list_accounts() to see all)
    - sku                 : Exact SKU (case-sensitive)
    - sku_starts_with     : SKU begins with this string
    - sku_contains        : SKU contains this string
    - asin                : Exact ASIN
    - brand               : Exact brand name (case-sensitive)
    - active              : 'true' or 'false'
    - repricer_activated  : 'true' or 'false'
    - repricing_strategy  : Exact strategy name
    - repricing_method    : e.g. 'FIXED' or 'ALGORITHMIC'
    - floor_price_min/max : Filter by floor price range
    - ceiling_price_min/max : Filter by ceiling price range
    - current_price_min/max : Filter by live listing price range
    - cost_min/max        : Filter by product cost range
    - available_quantity_min/max : Filter by available inventory
    - page                : 0-indexed page number (default 0)
    """
    err = _validate_account(account_name)
    if err:
        return f"Error: {err}"

    account_id = ACCOUNTS[account_name]["account_id"]
    params: dict = {"page": page}

    if sku:
        params["sku"] = f"[EQCS:{sku}]"
    elif sku_starts_with:
        params["sku"] = f"[BW:{sku_starts_with}]"
    elif sku_contains:
        params["sku"] = f"[CON:{sku_contains}]"

    if asin:
        params["asin"] = f"[EQCS:{asin}]"
    if brand:
        params["brand"] = f"[EQCS:{brand}]"
    if active is not None:
        params["active"] = active
    if repricer_activated is not None:
        params["repricerActivated"] = repricer_activated
    if repricing_strategy:
        params["repricingStrategy"] = f"[EQCS:{repricing_strategy}]"
    if repricing_method:
        params["repricingMethod"] = f"[EQCS:{repricing_method}]"

    _range("floorPrice",          floor_price_min,        floor_price_max,        params)
    _range("ceilingPrice",        ceiling_price_min,      ceiling_price_max,      params)
    _range("currentListingPrice", current_price_min,      current_price_max,      params)
    _range("cost",                cost_min,               cost_max,               params)
    _range("availableQuantity",   available_quantity_min, available_quantity_max, params)

    try:
        result = _api_get(account_name, f"/external/{account_id}/v2/listings", params)
        return json.dumps(result, indent=2)
    except requests.HTTPError as e:
        return f"API error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Error: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# TOOL: get_listing_by_sku
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_listing_by_sku(account_name: str, sku: str) -> str:
    """
    Fetch full configuration for a single SKU from Feedvisor.
    Returns all fields: pricing, floor/ceiling, cost, MAP, inventory, repricer, etc.

    Parameters:
    - account_name : The account owning this SKU
    - sku          : Exact seller SKU (case-sensitive)
    """
    err = _validate_account(account_name)
    if err:
        return f"Error: {err}"

    account_id = ACCOUNTS[account_name]["account_id"]
    try:
        result = _api_get(
            account_name,
            f"/external/{account_id}/v2/listings",
            {"sku": f"[EQCS:{sku}]"},
        )
        items = result.get("items", [])
        if not items:
            return f"No listing found for SKU '{sku}' in account '{account_name}'."
        return json.dumps(items[0], indent=2)
    except requests.HTTPError as e:
        return f"API error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Error: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# TOOL: update_listing
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def update_listing(
    account_name: str,
    sku: str,
    asin: str,
    fulfillment_channel: str,
    # ── Pricing / repricing ──────────────────────────────────────────────────
    floor_price: float = None,
    ceiling_price: float = None,
    map_price: float = None,
    repricer_activated: bool = None,
    repricing_method: str = None,
    repricing_strategy: str = None,
    repricing_method_value: float = None,
    item_on_sale_repricing_method: str = None,
    item_on_sale_repricing_strategy: str = None,
    cohort: str = None,
    listing_comment: str = None,
    # ── Inventory / cost ────────────────────────────────────────────────────
    cost: float = None,
    shipping_cost: float = None,
    additional_inventory_costs: float = None,
    inventory_comment: str = None,
    vendor_name: str = None,
    vendor_part_number: str = None,
    brand: str = None,
    lead_time: float = None,
    units_in_pack: int = None,
    min_quantity_for_order: int = None,
    parent_sku: str = None,
    days_of_coverage: int = None,
    is_replenishable: bool = None,
    warehouse_inventory: int = None,
) -> str:
    """
    Update configuration for a single listing in Feedvisor.
    Changes are applied LIVE immediately.

    REQUIRED identifiers (Feedvisor needs all three to locate the listing):
    - account_name       : e.g. 'PiercedOwlUS'
    - sku                : Exact seller SKU
    - asin               : Amazon product ASIN
    - fulfillment_channel: 'FBA' or 'FBM'

    OPTIONAL fields to update (only fields you provide will change):
    Pricing/repricing:
    - floor_price                   : Min repricing price
    - ceiling_price                 : Max repricing price
    - map_price                     : Minimum Advertised Price
    - repricer_activated            : true/false — enable/disable repricer
    - repricing_method              : e.g. 'FIXED', 'ALGORITHMIC'
    - repricing_strategy            : Repricing strategy name
    - repricing_method_value        : Numeric value for the repricing method
    - item_on_sale_repricing_method : Method when item is on sale
    - item_on_sale_repricing_strategy: Strategy when item is on sale
    - cohort                        : Cohort group name
    - listing_comment               : Free-text comment on listing

    Inventory/cost:
    - cost                        : Product cost (max 2 decimal places)
    - shipping_cost               : Est. fulfillment cost (FBM only)
    - additional_inventory_costs  : Extra costs (max 2 decimal places)
    - inventory_comment           : Free-text inventory note
    - vendor_name                 : Vendor name
    - vendor_part_number          : Vendor part number
    - brand                       : Brand name
    - lead_time                   : Lead time in days
    - units_in_pack               : Units per pack
    - min_quantity_for_order      : Minimum order quantity
    - parent_sku                  : Parent SKU
    - days_of_coverage            : Days of coverage target
    - is_replenishable            : true/false
    - warehouse_inventory         : Warehouse inventory quantity
    """
    err = _validate_account(account_name)
    if err:
        return f"Error: {err}"

    account_id = ACCOUNTS[account_name]["account_id"]

    item: dict = {
        "sku":               sku,
        "asin":              asin,
        "fulfillmentChannel": fulfillment_channel.upper(),
    }

    # Pricing / repricing
    if floor_price is not None:                  item["floorPrice"]                   = floor_price
    if ceiling_price is not None:                item["ceilingPrice"]                 = ceiling_price
    if map_price is not None:                    item["mapPrice"]                     = map_price
    if repricer_activated is not None:           item["repricerActivated"]            = repricer_activated
    if repricing_method is not None:             item["repricingMethod"]              = repricing_method
    if repricing_strategy is not None:           item["repricingStrategy"]            = repricing_strategy
    if repricing_method_value is not None:       item["repricingMethodValue"]         = repricing_method_value
    if item_on_sale_repricing_method is not None:  item["itemOnSaleRepricingMethod"]  = item_on_sale_repricing_method
    if item_on_sale_repricing_strategy is not None: item["itemOnSaleRepricingStrategy"] = item_on_sale_repricing_strategy
    if cohort is not None:                       item["cohort"]                       = cohort
    if listing_comment is not None:              item["listingComment"]               = listing_comment

    # Inventory / cost
    if cost is not None:                         item["cost"]                         = cost
    if shipping_cost is not None:                item["shippingCost"]                 = shipping_cost
    if additional_inventory_costs is not None:   item["additionalInventoryCosts"]     = additional_inventory_costs
    if inventory_comment is not None:            item["inventoryComment"]             = inventory_comment
    if vendor_name is not None:                  item["vendorName"]                   = vendor_name
    if vendor_part_number is not None:           item["vendorPartNumber"]             = vendor_part_number
    if brand is not None:                        item["brand"]                        = brand
    if lead_time is not None:                    item["leadTime"]                     = lead_time
    if units_in_pack is not None:                item["unitsInPack"]                  = units_in_pack
    if min_quantity_for_order is not None:       item["minQuantityForOrder"]          = min_quantity_for_order
    if parent_sku is not None:                   item["parentSKU"]                    = parent_sku
    if days_of_coverage is not None:             item["daysOfCoverage"]               = days_of_coverage
    if is_replenishable is not None:             item["isReplenishable"]              = is_replenishable
    if warehouse_inventory is not None:          item["warehouseInventory"]           = warehouse_inventory

    if len(item) == 3:
        return "Error: No fields to update provided beyond the required identifiers."

    try:
        result = _api_put(account_name, f"/external/{account_id}/v2/listings", [item])
        return json.dumps({
            "status": "success",
            "account": account_name,
            "sku": sku,
            "fields_updated": {k: v for k, v in item.items() if k not in ("sku", "asin", "fulfillmentChannel")},
            "api_response": result,
        }, indent=2)
    except requests.HTTPError as e:
        return f"API error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Error: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# TOOL: bulk_update_listings
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def bulk_update_listings(account_name: str, updates: str) -> str:
    """
    Update up to 1000 listings at once in a single Feedvisor account.
    Changes are applied LIVE immediately.

    Parameters:
    - account_name : The account owning these SKUs
    - updates      : A JSON array of listing objects. Each object MUST include
                     'sku', 'asin', and 'fulfillmentChannel' ('FBA' or 'FBM').
                     All other fields are optional.

    Example:
    [
      {
        "sku": "SKU-001",
        "asin": "B00ABC1234",
        "fulfillmentChannel": "FBA",
        "floorPrice": 12.99,
        "ceilingPrice": 24.99,
        "repricerActivated": true
      },
      {
        "sku": "SKU-002",
        "asin": "B00XYZ5678",
        "fulfillmentChannel": "FBM",
        "cost": 5.50,
        "shippingCost": 3.00,
        "mapPrice": 18.00
      }
    ]

    Updatable fields: floorPrice, ceilingPrice, mapPrice, cost, shippingCost,
    additionalInventoryCosts, repricerActivated, repricingMethod, repricingStrategy,
    repricingMethodValue, itemOnSaleRepricingMethod, itemOnSaleRepricingStrategy,
    cohort, listingComment, inventoryComment, vendorName, vendorPartNumber, brand,
    leadTime, unitsInPack, minQuantityForOrder, parentSKU, daysOfCoverage,
    isReplenishable, warehouseInventory.
    """
    err = _validate_account(account_name)
    if err:
        return f"Error: {err}"

    try:
        update_list = json.loads(updates)
    except json.JSONDecodeError as e:
        return f"Error: 'updates' is not valid JSON — {e}"

    if not isinstance(update_list, list):
        return "Error: 'updates' must be a JSON array."
    if len(update_list) > 1000:
        return "Error: Maximum 1000 items per bulk update call."

    # Validate required fields
    errors = []
    for i, item in enumerate(update_list):
        missing = [f for f in ("sku", "asin", "fulfillmentChannel") if not item.get(f)]
        if missing:
            errors.append(f"Item {i}: missing required fields: {missing}")
    if errors:
        return "Validation errors:\n" + "\n".join(errors)

    account_id = ACCOUNTS[account_name]["account_id"]
    try:
        result = _api_put(account_name, f"/external/{account_id}/v2/listings", update_list)
        return json.dumps({
            "status": "success",
            "account": account_name,
            "items_submitted": len(update_list),
            "api_response": result,
        }, indent=2)
    except requests.HTTPError as e:
        return f"API error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Error: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# TOOL: request_configuration_report
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def request_configuration_report(
    account_name: str,
    report_type: str = "CONFIGURATION_V2",
    file_type: str = "XLSX",
    fulfillment_channel: str = None,
    repricing_status: bool = None,
    in_stock: bool = None,
    has_buy_box: bool = None,
    active: bool = None,
    search: str = None,
    report_sub_type: str = None,
    advertise_period_start_date: str = None,
    advertise_period_end_date: str = None,
    advertising_metrics_days_back: str = None,
) -> str:
    """
    Request a configuration or advertising export report from Feedvisor.
    Returns a requestId — use get_report_status() to poll for completion.

    Parameters:
    - account_name          : Account to pull report from
    - report_type           : One of:
                              CONFIGURATION_V2 (default) — full pricing/inventory config
                              CONFIGURATION_MINIMAL      — compact config
                              REPLENISH_V2               — replenishment data
                              NON_COMPETITIVE_V2         — non-competitive items
                              CUSTOM_ATTRIBUTE           — custom attributes
                              AMAZON_ADVERTISING_ALL     — advertising data (requires report_sub_type='ALL')
                              ADVERTISING_INITIATIVE_ALL — initiative data (requires report_sub_type='ALL')
    - file_type             : 'XLSX' (default) or 'CSV'
    - fulfillment_channel   : 'FBA' or 'FBM' (omit for all)
    - repricing_status      : true/false — filter by repricer on/off
    - in_stock              : true/false — filter by stock status
    - has_buy_box           : true/false — filter by Buy Box ownership (Amazon only)
    - active                : true/false — filter by active status
    - search                : Search in product name, ASIN, or SKU
    - report_sub_type       : Required for AMAZON_ADVERTISING_ALL: use 'ALL'
    - advertise_period_start_date : YYYY-MM-DD (for AMAZON_ADVERTISING_ALL)
    - advertise_period_end_date   : YYYY-MM-DD (for AMAZON_ADVERTISING_ALL)
    - advertising_metrics_days_back : '1','7','14','30','60' (default 30)
    """
    err = _validate_account(account_name)
    if err:
        return f"Error: {err}"

    account_id = ACCOUNTS[account_name]["account_id"]

    payload: dict = {
        "fileType":   file_type,
        "reportType": report_type,
    }
    if report_sub_type:                          payload["reportSubType"]                = report_sub_type
    if fulfillment_channel:                      payload["fulfillmentChannel"]           = fulfillment_channel.upper()
    if repricing_status is not None:             payload["repricingStatus"]              = repricing_status
    if in_stock is not None:                     payload["inStock"]                      = in_stock
    if has_buy_box is not None:                  payload["hasBB"]                        = has_buy_box
    if active is not None:                       payload["active"]                       = active
    if search:                                   payload["search"]                       = search
    if advertise_period_start_date:              payload["advertisePeriodStartDate"]     = advertise_period_start_date
    if advertise_period_end_date:                payload["advertisePeriodEndDate"]       = advertise_period_end_date
    if advertising_metrics_days_back:            payload["advertisingMetricsDaysBack"]   = advertising_metrics_days_back

    try:
        result = _api_post(account_name, f"/external/{account_id}/report", payload)
        request_id = result.get("requestId")
        return json.dumps({
            "status":    "report_requested",
            "account":   account_name,
            "requestId": request_id,
            "next_step": f"Call get_report_status(account_name='{account_name}', request_id='{request_id}') to check when your report is ready.",
        }, indent=2)
    except requests.HTTPError as e:
        return f"API error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Error: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# TOOL: request_analytics_report
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def request_analytics_report(
    account_name: str,
    file_type: str = "XLSX",
    fulfillment_channel: str = None,
    in_stock: bool = None,
    has_buy_box: bool = None,
    active: bool = None,
    search: str = None,
) -> str:
    """
    Request a Product Analytics report from Feedvisor (Amazon accounts only).
    Returns a requestId — use get_report_status() to poll for completion.

    Parameters:
    - account_name        : Account to pull from (Amazon accounts only)
    - file_type           : 'XLSX' (default) or 'CSV'
    - fulfillment_channel : 'FBA' or 'FBM' (omit for all)
    - in_stock            : true/false
    - has_buy_box         : true/false
    - active              : true/false
    - search              : Search in product name, ASIN, or SKU
    """
    err = _validate_account(account_name)
    if err:
        return f"Error: {err}"

    account_id = ACCOUNTS[account_name]["account_id"]

    payload: dict = {"fileType": file_type}
    if fulfillment_channel:    payload["fulfillmentChannel"] = fulfillment_channel.upper()
    if in_stock is not None:   payload["inStock"]            = in_stock
    if has_buy_box is not None: payload["hasBB"]             = has_buy_box
    if active is not None:     payload["active"]             = active
    if search:                 payload["search"]             = search

    try:
        result = _api_post(account_name, f"/external/{account_id}/analytics/report", payload)
        request_id = result.get("requestId")
        return json.dumps({
            "status":    "analytics_report_requested",
            "account":   account_name,
            "requestId": request_id,
            "next_step": f"Call get_report_status(account_name='{account_name}', request_id='{request_id}') to check when your report is ready.",
        }, indent=2)
    except requests.HTTPError as e:
        return f"API error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Error: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# TOOL: get_report_status
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_report_status(account_name: str, request_id: str) -> str:
    """
    Check the status of a previously requested report and get its download URL
    when ready.

    Parameters:
    - account_name : The same account used when requesting the report
    - request_id   : The requestId returned by request_configuration_report()
                     or request_analytics_report()

    Returns the current status and a download URL when the report is complete.
    """
    err = _validate_account(account_name)
    if err:
        return f"Error: {err}"

    account_id = ACCOUNTS[account_name]["account_id"]
    try:
        result = _api_get(account_name, f"/external/{account_id}/report/{request_id}")
        return json.dumps(result, indent=2)
    except requests.HTTPError as e:
        return f"API error {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return f"Error: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Auth middleware  (remote / Railway deployment)
# ──────────────────────────────────────────────────────────────────────────────

class _APIKeyAuth:
    """
    Pure ASGI middleware that enforces Authorization: Bearer <MCP_API_KEY>.

    • If MCP_API_KEY env var is empty/unset, auth is skipped (local dev mode).
    • GET /health is always allowed — used by Railway's health-check system.
    """

    def __init__(self, app, api_key: str):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        # Let lifespan events pass through untouched
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return

        if scope["type"] == "http":
            path = scope.get("path", "")

            # Railway health-check endpoint — no auth required
            if path == "/health":
                await send({
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                })
                await send({"type": "http.response.body", "body": b"ok"})
                return

            # Enforce Bearer token when a key is configured
            if self.api_key:
                headers = {k.lower(): v for k, v in scope.get("headers", [])}
                auth = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
                if not (auth.startswith("Bearer ") and auth[7:] == self.api_key):
                    await send({
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    })
                    await send({
                        "type": "http.response.body",
                        "body": b'{"error":"Unauthorized","message":"Supply a valid key via: Authorization: Bearer <MCP_API_KEY>"}',
                    })
                    return

        await self.app(scope, receive, send)


# ──────────────────────────────────────────────────────────────────────────────
# Entry point — dual-mode: stdio (Claude Desktop) or HTTP (Railway / remote)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")

    if transport == "stdio":
        # ── Local Claude Desktop mode (original behaviour) ──────────────────
        mcp.run()
    else:
        # ── Remote mode: Railway / cloud ────────────────────────────────────
        import uvicorn

        port    = int(os.getenv("PORT", 8000))
        api_key = os.getenv("MCP_API_KEY", "")

        app = mcp.sse_app()

        if api_key:
            app = _APIKeyAuth(app, api_key)

        uvicorn.run(app, host="0.0.0.0", port=port, log_level="info",
                    proxy_headers=True, forwarded_allow_ips="*")
