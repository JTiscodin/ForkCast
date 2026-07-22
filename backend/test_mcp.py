"""Tests for the Swiggy MCP integration using MockMCPClient (no network).

Verifies the real-schema code paths: catalog_fetcher._mcp_fetch, order_executor
_mcp_place (update_food_cart -> get_food_cart -> place_food_order), guardrails,
and MCP response unwrapping.
"""
from swiggy_mcp import MockMCPClient, _parse_mcp_response, _unwrap_tool_result
from catalog_fetcher import CatalogFetcher
from order_executor import OrderExecutor, _cart_total


def test_unwrap_structured_content():
    r = _unwrap_tool_result({"structuredContent": {"a": 1}})
    assert r == {"a": 1}


def test_unwrap_text_json():
    r = _unwrap_tool_result({"content": [{"type": "text", "text": '{"x":2}'}]})
    assert r == {"x": 2}


def test_parse_sse_response():
    sse = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    assert _parse_mcp_response(sse) == {"ok": True}


def test_fetcher_mcp_mode_returns_dishes():
    f = CatalogFetcher(mode="mcp", mcp_client=MockMCPClient(), address_id="addr1")
    dishes = f.fetch()
    assert len(dishes) >= 1
    d = dishes[0]
    assert d.price > 0 and d.name


def test_fetcher_resolves_address_when_missing():
    f = CatalogFetcher(mode="mcp", mcp_client=MockMCPClient())  # no address_id
    dishes = f.fetch()  # should call get_addresses internally
    assert isinstance(dishes, list)


def test_executor_mcp_place_flow():
    ex = OrderExecutor(mode="mcp", mcp_client=MockMCPClient(), address_id="addr1")
    res = ex.place("m1", "r1", 90, "regular")
    assert res["status"] == "confirmed"
    assert res["order_id"].startswith("SWG")


def test_cart_total_shapes():
    assert _cart_total({"cart": {"total": 250}}) == 250
    assert _cart_total({"grandTotal": 400}) == 400
    assert _cart_total({"nope": 1}) is None


def test_guardrail_blocks_over_1000():
    class BigCart(MockMCPClient):
        def call(self, tool, args):
            if tool == "get_food_cart":
                return {"cart": {"total": 1200}, "availablePaymentMethods": ["COD"]}
            return super().call(tool, args)
    ex = OrderExecutor(mode="mcp", mcp_client=BigCart(), address_id="addr1")
    try:
        ex.place("m1", "r1", 1200)
        assert False, "expected guardrail ValueError"
    except ValueError as e:
        assert "1000" in str(e)


if __name__ == "__main__":
    import sys
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1; print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
