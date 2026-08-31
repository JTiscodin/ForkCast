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


class _TwoPageMCPClient:
    """Fake MCP client: search_menu page 1 carries a nextOffset, page 2 does
    not. Records every search_menu call so the test can assert the offset was
    echoed back on the second call."""

    def __init__(self):
        self.search_calls = []

    def call(self, tool, args):
        if tool == "search_menu":
            self.search_calls.append(dict(args))
            if "offset" not in args:
                return {"items": [
                    {"id": "p1a", "name": "Masala Dosa", "price": 90,
                     "is_veg": True, "rating": 4.4, "restaurant_id": "r1",
                     "restaurant_name": "Sri Udupi"},
                ], "nextOffset": "off-42"}
            return {"items": [
                {"id": "p2a", "name": "Paneer Butter Masala Thali", "price": 220,
                 "is_veg": True, "rating": 4.6, "restaurant_id": "r2",
                 "restaurant_name": "Punjabi Rasoi"},
            ]}  # no nextOffset -> pagination stops here
        if tool == "get_addresses":
            return {"addresses": [{"id": "addr1", "label": "Home"}]}
        return {"success": True}


def test_search_pagination_follows_next_offset():
    """fetch() must follow nextOffset to a second page, pass the offset back,
    and merge items from both pages into the pool."""
    from catalog_fetcher import SEARCH_PAGES

    assert SEARCH_PAGES >= 2, "SEARCH_PAGES default must fetch at least two pages"

    client = _TwoPageMCPClient()
    f = CatalogFetcher(mode="mcp", mcp_client=client, address_id="addr1")
    dishes = f.fetch()

    ids = {d.dish_id for d in dishes}
    assert "p1a" in ids, "page-1 item missing from merged pool"
    assert "p2a" in ids, "page-2 item missing — nextOffset was not followed"

    # The second call of a paginated query must echo back page 1's nextOffset.
    assert len(client.search_calls) >= 2, "expected at least two search_menu calls"
    first, second = client.search_calls[0], client.search_calls[1]
    assert "offset" not in first, "first page must not send an offset"
    assert second.get("offset") == "off-42", \
        f"second call did not pass back nextOffset: {second}"
    # And no call may invent an offset the server never sent.
    assert all(c.get("offset", "off-42") == "off-42" for c in client.search_calls), \
        f"a call used an offset never returned by the server: {client.search_calls}"


def test_slot_queries_have_enough_seeds():
    """Every meal must have >= 5 search seeds — the old 3-per-slot fan-out left
    the optimizer ~5 dishes per meal and recycling them across 30 days."""
    from catalog_fetcher import SLOT_QUERIES

    for meal, seeds in SLOT_QUERIES.items():
        assert len(seeds) >= 5, f"{meal} has only {len(seeds)} seeds: {seeds}"


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
