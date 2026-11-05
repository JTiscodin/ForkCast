"""Order Executor (Docs section 9). Places orders via Swiggy MCP.

Demo: mode='mock' -> simulates order id + tracking, no real order, no money.
Prototype: mode='mcp' -> update_food_cart -> get_food_cart -> place_food_order
           -> track_food_order (verified Swiggy Food schema).

Order lifecycle wired to wallet: on confirmed order -> debit ledger.
"""


class OrderExecutor:
    def __init__(self, mode="mock", mcp_client=None, address_id=None):
        assert mode in ("mock", "mcp")
        if mode == "mcp" and mcp_client is None:
            raise ValueError("mcp mode needs mcp_client")
        self.mode = mode
        self.mcp = mcp_client
        self.address_id = address_id
        self._mock_seq = 0

    def place(self, dish_id, restaurant_id, price, portion_variant="regular",
              raw_variant=None, dry_run=False, extra_items=None):
        """Returns {order_id, status, eta_min, amount}. Does NOT touch wallet;
        caller debits ledger on success to keep money logic in one place.
        dry_run builds the real cart and stops before place_food_order.
        extra_items: more lines for the SAME restaurant cart, e.g. a curry's roti
        [{"id", "quantity", "raw_variant"}]."""
        if self.mode == "mock":
            res = self._mock_place(dish_id, price)
            if dry_run:
                res.update(order_id=None, status="dry_run")
            return res
        return self._mcp_place(dish_id, restaurant_id, portion_variant, price,
                               raw_variant, dry_run, extra_items)

    def track(self, order_id):
        if self.mode == "mock":
            return {"order_id": order_id, "status": "on_the_way", "eta_min": 18}
        return self.mcp.call("track_food_order", {"orderId": order_id})

    # ---- mock ----
    def _mock_place(self, dish_id, price):
        self._mock_seq += 1
        return {
            "order_id": f"MOCK-{self._mock_seq:04d}",
            "status": "confirmed",
            "eta_min": 25,
            "amount": price,
            "dish_id": dish_id,
        }

    # ---- live MCP (verified Swiggy Food schema) ----
    def _mcp_place(self, dish_id, restaurant_id, variant, price, raw_variant=None,
                   dry_run=False, extra_items=None):
        """Real workflow: update_food_cart -> get_food_cart -> validate -> place.

        Swiggy guardrails enforced here (docs):
          - cart total must be < ₹1000
          - only COD supported currently
          - order placed against a saved addressId (resolved from get_addresses)
        cartItems echoes the item's own variant format ('variations'|'variantsV2');
        raw_variant carries whatever search_menu returned so we don't invent a shape.
        """
        address_id = self._address_id()

        cart_items = [_cart_line(dish_id, 1, raw_variant)] + [
            _cart_line(x["id"], x.get("quantity", 1), x.get("raw_variant"))
            for x in extra_items or ()]

        self.mcp.call("update_food_cart", {
            "restaurantId": restaurant_id,
            "cartItems": cart_items,
            "addressId": address_id,
        })

        # MUST fetch cart after update (no UI render on update); validate before order
        cart = self.mcp.call("get_food_cart", {"addressId": address_id})  # live server requires it
        total = _cart_total(cart)
        pay_methods = cart.get("availablePaymentMethods") or []
        if total is not None and total >= 1000:
            raise ValueError(
                f"Swiggy blocks orders >= ₹1000 (cart ₹{total}). Split the order.")
        if dry_run:
            return {"order_id": None, "status": "dry_run", "eta_min": None,
                    "amount": total if total is not None else price,
                    "dish_id": dish_id, "message": "cart built, order not placed"}
        # live API names cash-on-delivery "Cash"; the user confirmed cash in the UI
        if pay_methods and not {"Cash", "COD"} & set(pay_methods):
            raise ValueError("Cash on delivery not offered for this cart; only cash is supported")
        payment = "Cash"

        res = self.mcp.call("place_food_order", {
            "addressId": address_id,
            "paymentMethod": payment,
        })
        data = res.get("data") or {}
        return {
            "order_id": str(data.get("order_id") or data.get("orderId") or "SWG-?"),
            "status": "confirmed" if res.get("success", True) else "failed",
            "eta_min": data.get("eta_min", 30),
            "amount": total if total is not None else price,
            "dish_id": dish_id,
            "message": res.get("message", ""),
        }

    def _address_id(self):
        if self.address_id:
            return self.address_id
        resp = self.mcp.call("get_addresses", {})
        addrs = resp.get("addresses") or resp.get("data") or []
        if not addrs:
            raise ValueError("no saved Swiggy address")
        self.address_id = str(addrs[0].get("id") or addrs[0].get("addressId"))
        return self.address_id


def _cart_line(item_id, quantity, raw_variant=None):
    # live schema: {menu_item_id, quantity, variants|variantsV2: [{group_id, variation_id}]}.
    # shortcut: search_menu returns no variant data, so lines go without a variant
    # selection; an item that requires one fails at update_food_cart and the order
    # falls back to the Swiggy deep link. Upgrade via get_restaurant_menu variants.
    return {"menu_item_id": str(item_id), "quantity": quantity}


def _cart_total(cart):
    """Pull numeric cart total from various possible Swiggy cart shapes."""
    if not isinstance(cart, dict):
        return None
    # live: data.pricing.to_pay = items + delivery + taxes (what the user pays)
    for path in (("data", "pricing", "to_pay"), ("cart", "total"), ("data", "total"),
                 ("bill", "grandTotal")):
        node = cart
        ok = True
        for k in path:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                ok = False
                break
        if ok:
            try:
                return float(node)
            except (ValueError, TypeError):
                pass
    for k in ("total", "grandTotal", "finalAmount"):
        if k in cart:
            try:
                return float(cart[k])
            except (ValueError, TypeError):
                pass
    return None
