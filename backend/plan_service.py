"""Plan persistence + notification state machine (Docs section 8).

Ties optimizer output -> DB -> wallet -> order executor. This is the runtime
that fires per meal slot and handles the yes/no/later/other reply.

State machine per slot:
    planned --notify--> awaiting reply
        yes   -> place order, debit wallet, status=confirmed
        no    -> credit wallet (Swiggy Cash back), status=skipped
        later -> reschedule (new day/meal kept, status=rescheduled), re-notify
        other -> swap engine returns alternatives (handled in swap_service)
"""
import json
from wallet_service import WalletService
from order_executor import OrderExecutor


class PlanService:
    def __init__(self, conn, wallet: WalletService = None, executor: OrderExecutor = None):
        self.conn = conn
        self.wallet = wallet or WalletService(conn)
        self.executor = executor or OrderExecutor(mode="mock")

    # ---- persist a PlanResult from optimizer ----
    def save_plan(self, user_id, month, plan_result):
        import sqlite3 as _sqlite3
        import time as _time
        last_err = None
        for attempt in range(3):
            try:
                cur = self.conn.execute(
                    "INSERT INTO plans (user_id, month, budget, total_cost, feasible, status, message) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (user_id, month, plan_result.budget, plan_result.total_cost,
                     int(plan_result.feasible), "draft", plan_result.message),
                )
                plan_id = cur.lastrowid
                rows = [
                    (plan_id, s.day, s.meal_type, s.dish_id, s.dish_name, s.restaurant_id,
                     getattr(s, "restaurant_name", ""), getattr(s, "image_url", ""),
                     s.price, s.rating, s.variant, "planned",
                     getattr(s, "course", "complete"),
                     getattr(s, "side_dish_id", ""), getattr(s, "side_dish_name", ""),
                     getattr(s, "side_qty", 0), getattr(s, "side_price", 0.0),
                     getattr(s, "side_restaurant_name", ""),
                     getattr(s, "side_image_url", ""),
                     getattr(s, "dish_kind", "meal"),
                     getattr(s, "side2_dish_id", ""),
                     getattr(s, "side2_dish_name", ""),
                     getattr(s, "side2_qty", 0),
                     getattr(s, "side2_price", 0.0),
                     getattr(s, "side2_restaurant_name", ""),
                     getattr(s, "side2_image_url", ""))
                    for s in plan_result.slots
                ]
                self.conn.executemany(
                    "INSERT INTO meal_slots "
                    "(plan_id, day, meal_type, dish_id, dish_name, restaurant_id, "
                    "restaurant_name, image_url, price, rating, variant, status, "
                    "course, side_dish_id, side_dish_name, side_qty, side_price, "
                    "side_restaurant_name, side_image_url, dish_kind, side2_dish_id, "
                    "side2_dish_name, side2_qty, side2_price, side2_restaurant_name, "
                    "side2_image_url) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows,
                )
                self.conn.commit()
                return plan_id
            except _sqlite3.OperationalError as e:
                last_err = e
                msg = str(e).lower()
                if ("locked" in msg or "busy" in msg) and attempt < 2:
                    try:
                        self.conn.rollback()
                    except Exception:
                        pass
                    _time.sleep(0.15 * (attempt + 1))
                    continue
                raise
        raise last_err  # pragma: no cover — loop always returns or raises above

    def get_plan(self, plan_id):
        p = self.conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        slots = self.conn.execute(
            "SELECT * FROM meal_slots WHERE plan_id=? ORDER BY day, "
            "CASE meal_type WHEN 'breakfast' THEN 0 WHEN 'lunch' THEN 1 ELSE 2 END",
            (plan_id,),
        ).fetchall()
        return dict(p), [dict(s) for s in slots]

    def approve_plan(self, plan_id):
        """One upfront approval (Docs). Deposits budget into wallet cycle."""
        p = self.conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not p:
            raise ValueError("plan not found")
        if p["status"] != "draft":
            raise ValueError("plan not in draft")
        # An over-budget plan must never be activatable — the UI shows the
        # feasibility fixes for a reason. Force the user to adjust first.
        if not p["feasible"]:
            raise ValueError(
                "plan is over budget — apply a suggested fix or raise the budget first")
        # Deposit the month budget as spendable. If a previous plan already
        # funded this cycle, top up only the difference (a bigger replacement
        # plan adds funds; a smaller one never withdraws).
        summary = self.wallet.get_summary(p["user_id"], p["month"])
        delta = round(p["budget"] - summary["budget_allocated"], 2)
        if delta > 0:
            self.wallet.deposit(p["user_id"], p["month"], delta,
                                note=f"plan {plan_id} approved")
        self.conn.execute(
            "UPDATE plans SET status='active' WHERE id=?", (plan_id,))
        self.conn.commit()
        return self.wallet.get_summary(p["user_id"], p["month"])

    # ---- notification state machine ----
    @staticmethod
    def _slot_total(s):
        """Full cost of a slot — main dish plus any bread/rice accompaniment.

        `price` holds the main dish alone, so anything that moves money (wallet
        debits, order totals, the notification prompt) must use this instead or
        it silently undercharges every paired curry.
        """
        try:
            side = float(s["side_price"] or 0)
        except (KeyError, IndexError, TypeError):
            side = 0.0
        try:
            side2 = float(s["side2_price"] or 0)
        except (KeyError, IndexError, TypeError):
            side2 = 0.0
        return round(float(s["price"]) + side + side2, 2)

    def notify(self, slot_id):
        """Simulate T-30 notification. Returns the prompt payload for UI."""
        s = self._slot(slot_id)
        self.conn.execute(
            "INSERT INTO notifications (meal_slot_id) VALUES (?)", (slot_id,))
        self.conn.commit()
        dish = s["dish_name"]
        if s["side_dish_name"]:
            dish += f" with {s['side_dish_name']}"
            if (s["side_qty"] or 0) > 1:
                dish += f" x{s['side_qty']}"
        try:
            _side2_name = s["side2_dish_name"]
        except (KeyError, IndexError):
            _side2_name = None
        if _side2_name:
            dish += f" + {_side2_name}"
            try:
                _side2_qty = s["side2_qty"] or 0
            except (KeyError, IndexError):
                _side2_qty = 0
            if _side2_qty and _side2_qty > 1:
                dish += f" x{_side2_qty}"
        return {
            "slot_id": slot_id,
            "prompt": f"Should I get your {s['meal_type']} — "
                      f"{dish}, Rs {self._slot_total(s)}?",
            "options": ["yes", "no", "later", "other"],
        }

    def respond(self, slot_id, answer, new_day=None, new_meal_type=None):
        """Handle yes/no/later/other."""
        answer = answer.lower()
        s = self._slot(slot_id)
        p = self.conn.execute("SELECT * FROM plans WHERE id=?", (s["plan_id"],)).fetchone()
        user_id, month = p["user_id"], p["month"]

        if answer == "yes":
            # A confirmed slot already has an order + a debit. Answering "yes"
            # again (double-tap, retry, stale notification) must NOT place a
            # second order or debit twice.
            if s["status"] == "confirmed":
                raise ValueError("this meal is already ordered — no double debit")
            # Charge the whole meal — curry + its bread/rice — not just the main.
            cost = self._slot_total(s)
            order = self.executor.place(s["dish_id"], s["restaurant_id"],
                                        cost, s["variant"])
            self.wallet.debit(user_id, month, cost, meal_slot_id=slot_id,
                              note=f"{s['dish_name']}")
            self._set_slot(slot_id, status="confirmed", order_id=order["order_id"])
            self._resolve_notif(slot_id, "yes")
            return {"result": "ordered", "order": order}

        if answer == "no":
            # Virtual-budget model: full budget was deposited at approval, so an
            # unspent (never-debited) slot needs NO wallet move — the money is
            # already sitting in the balance.
            if s["status"] == "confirmed":
                # An order is already placed on Swiggy. We have no cancel API,
                # so refunding here would credit money back while the order (and
                # the real COD charge) still stands. Refuse loudly instead of
                # silently minting a phantom refund.
                raise ValueError(
                    "order already placed — it can't be cancelled from here, "
                    "so no refund was issued")
            self._set_slot(slot_id, status="skipped")
            self._resolve_notif(slot_id, "no")
            bal = self.wallet.get_balance(user_id, month)
            return {"result": "skipped", "swiggy_cash_balance": bal}

        if answer == "later":
            if new_day:
                # Keep the day inside the plan's actual range — day 9999 on a
                # 30-day plan is a corrupt slot, not a reschedule.
                max_day = self.conn.execute(
                    "SELECT MAX(day) FROM meal_slots WHERE plan_id=?",
                    (s["plan_id"],)).fetchone()[0] or 1
                if not (1 <= int(new_day) <= max_day):
                    raise ValueError(f"new_day must be between 1 and {max_day}")
            if new_meal_type and new_meal_type not in ("breakfast", "lunch", "dinner"):
                raise ValueError(f"bad meal_type: {new_meal_type}")
            if new_day:
                self.conn.execute(
                    "UPDATE meal_slots SET day=?, meal_type=COALESCE(?, meal_type), "
                    "status='rescheduled' WHERE id=?",
                    (new_day, new_meal_type, slot_id))
            else:
                self._set_slot(slot_id, status="rescheduled")
            self.conn.commit()
            self._resolve_notif(slot_id, "later")
            return {"result": "rescheduled", "slot_id": slot_id}

        if answer == "other":
            self._resolve_notif(slot_id, "other")
            return {"result": "needs_swap", "slot_id": slot_id}

        raise ValueError(f"bad answer: {answer}")

    # ---- helpers ----
    def _slot(self, slot_id):
        r = self.conn.execute("SELECT * FROM meal_slots WHERE id=?", (slot_id,)).fetchone()
        if not r:
            raise ValueError(f"no slot {slot_id}")
        return r

    def _set_slot(self, slot_id, **fields):
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE meal_slots SET {cols} WHERE id=?",
                          (*fields.values(), slot_id))
        self.conn.commit()

    def _resolve_notif(self, slot_id, answer):
        self.conn.execute(
            "UPDATE notifications SET user_response=?, resolved_at=datetime('now') "
            "WHERE meal_slot_id=? AND resolved_at IS NULL", (answer, slot_id))
        self.conn.commit()
