"""Real Swiggy MCP client (Food vertical).

Endpoint: https://mcp.swiggy.com/food  (HTTP, OAuth)
Tools (verified from mcp.swiggy.com/builders/docs/reference/food):
    get_addresses()
    search_restaurants(addressId, query, offset?)
    search_menu(addressId, query, restaurantIdOfAddedItem?, vegFilter?, offset?)
    update_food_cart(restaurantId, cartItems[], addressId, restaurantName?)
    get_food_cart()
    place_food_order(addressId, paymentMethod?)
    track_food_order(...)

Transport = MCP Streamable HTTP (JSON-RPC 2.0 over POST). Standard MCP method
"tools/call" with {name, arguments}. Auth = Bearer OAuth token.

The rest of the app depends only on .call(tool, args) -> dict. Swapping this for a
mock (MockMCPClient) needs no changes upstream. That's why catalog_fetcher /
order_executor take an injected client.
"""
import os
import json
import urllib.request
import urllib.error

SWIGGY_MCP_URL = os.environ.get("SWIGGY_MCP_URL", "https://mcp.swiggy.com/food")

# Swiggy food ordering hard guardrails (from docs).
MAX_CART_TOTAL = 1000          # ₹ — place_food_order refuses above this
COD_ONLY = True               # only COD supported currently


class SwiggyMCPError(Exception):
    pass


class SwiggyMCPClient:
    """JSON-RPC 2.0 client over MCP Streamable HTTP.

    token: OAuth access token. Obtain via the OAuth flow (linking Swiggy account).
           For local dev, set SWIGGY_MCP_TOKEN env var after linking in the
           MCP inspector / Claude / Postman (localhost redirect is whitelisted).
    """

    def __init__(self, token=None, url=SWIGGY_MCP_URL, timeout=12):
        self.url = url
        self.token = token or os.environ.get("SWIGGY_MCP_TOKEN")
        if not self.token:
            raise SwiggyMCPError(
                "No OAuth token. Link Swiggy account and set SWIGGY_MCP_TOKEN.")
        self._id = 0
        self.timeout = timeout

    def _rpc(self, method, params):
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {self.token}",
            },
            method="POST",
        )
        # Shorter timeout + one retry: Swiggy occasionally stalls a request;
        # a fresh connection usually succeeds, and we'd rather fail a single
        # query fast than hang the whole catalog build.
        last_err = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode()
                return _parse_mcp_response(raw)
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")
                raise SwiggyMCPError(f"HTTP {e.code}: {body}") from e
            except (TimeoutError, OSError) as e:
                last_err = e
                continue
        raise SwiggyMCPError(f"request failed after retry: {last_err}")

    def call(self, tool, arguments):
        """Standard MCP tools/call. Returns the tool result payload (dict)."""
        result = self._rpc("tools/call", {"name": tool, "arguments": arguments})
        return _unwrap_tool_result(result)

    def list_tools(self):
        return self._rpc("tools/list", {})

    # ---- thin typed wrappers (exact param names from docs) ----
    def get_addresses(self):
        return self.call("get_addresses", {})

    def search_restaurants(self, address_id, query, offset=0):
        return self.call("search_restaurants",
                         {"addressId": address_id, "query": query, "offset": offset})

    def search_menu(self, address_id, query, restaurant_id=None, veg_only=False, offset=0):
        args = {"addressId": address_id, "query": query, "offset": offset}
        if restaurant_id:
            args["restaurantIdOfAddedItem"] = restaurant_id
        if veg_only:
            args["vegFilter"] = 1
        return self.call("search_menu", args)

    def update_food_cart(self, restaurant_id, cart_items, address_id, restaurant_name=None):
        args = {"restaurantId": restaurant_id, "cartItems": cart_items,
                "addressId": address_id}
        if restaurant_name:
            args["restaurantName"] = restaurant_name
        return self.call("update_food_cart", args)

    def get_food_cart(self):
        return self.call("get_food_cart", {})

    def place_food_order(self, address_id, payment_method=None):
        args = {"addressId": address_id}
        if payment_method:
            args["paymentMethod"] = payment_method
        return self.call("place_food_order", args)

    def track_food_order(self, order_id=None):
        args = {"orderId": order_id} if order_id else {}
        return self.call("track_food_order", args)


def _parse_mcp_response(raw):
    """MCP HTTP may return plain JSON or SSE (text/event-stream). Handle both."""
    raw = raw.strip()
    if raw.startswith("{"):
        obj = json.loads(raw)
    else:
        # SSE: pull last 'data:' line
        data_lines = [ln[5:].strip() for ln in raw.splitlines()
                      if ln.startswith("data:")]
        if not data_lines:
            raise SwiggyMCPError(f"unparseable MCP response: {raw[:200]}")
        obj = json.loads(data_lines[-1])
    if "error" in obj:
        raise SwiggyMCPError(f"RPC error: {obj['error']}")
    return obj.get("result", obj)


def _unwrap_tool_result(result):
    """MCP tools/call result -> {content:[{type:'text',text:...}], structuredContent?}.
    Prefer structuredContent; else parse the first text block as JSON; else raw text."""
    if isinstance(result, dict):
        if "structuredContent" in result:
            return result["structuredContent"]
        content = result.get("content")
        if isinstance(content, list) and content:
            block = content[0]
            text = block.get("text", "")
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return {"text": text}
    return result


# ---- mock client for demo/tests (same .call interface) ----
class MockMCPClient:
    """Stand-in with the same .call(tool, args) contract. Returns canned shapes."""
    def call(self, tool, arguments):
        if tool == "get_addresses":
            return {"addresses": [{"id": "addr1", "label": "Home"}]}
        if tool == "search_restaurants":
            return {"restaurants": [
                {"id": "r1", "name": "Sri Udupi", "availabilityStatus": "OPEN",
                 "distanceKm": 1.2, "cuisine": "south_indian"}]}
        if tool == "search_menu":
            return {"items": [
                {"id": "m1", "name": "Masala Dosa", "price": 90, "is_veg": True,
                 "rating": 4.4, "category": "breakfast"}]}
        if tool == "get_food_cart":
            return {"cart": {"total": 90}, "availablePaymentMethods": ["COD"]}
        if tool == "update_food_cart":
            return {"success": True, "cart": {"total": 90}}
        if tool == "place_food_order":
            return {"success": True, "data": {"order_id": "SWG-MOCK-1"},
                    "message": "ordered"}
        if tool == "track_food_order":
            return {"status": "on_the_way", "eta_min": 20}
        return {"success": True}
