"""Wallet / ledger service. Virtual budget model (Option 1) — no real money custody.

Source of truth = ledger_transactions (append-only).
Balance + total_spent are derived on demand (recompute-cheap for MVP scale).

Transaction type signs:
    deposit  +   user sets monthly budget
    rollover +   leftover carried in from previous month
    credit   +   meal skipped, money returned
    debit    -   meal ordered/confirmed
"""
from db import get_conn

CREDIT_TYPES = ("deposit", "rollover", "credit")
DEBIT_TYPES = ("debit",)
VALID_TYPES = CREDIT_TYPES + DEBIT_TYPES


def next_month(month: str) -> str:
    """'2026-07' -> '2026-08', wraps year."""
    y, m = map(int, month.split("-"))
    m += 1
    if m > 12:
        m = 1
        y += 1
    return f"{y:04d}-{m:02d}"


class WalletService:
    def __init__(self, conn=None):
        self.conn = conn or get_conn()

    # ---- users ----
    def create_user(self, name: str, area: str = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO users (name, area) VALUES (?, ?)", (name, area)
        )
        self.conn.commit()
        return cur.lastrowid

    # ---- cycles ----
    def get_or_create_cycle(self, user_id: int, month: str) -> int:
        row = self.conn.execute(
            "SELECT id FROM budget_cycles WHERE user_id=? AND month=?",
            (user_id, month),
        ).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO budget_cycles (user_id, month) VALUES (?, ?)",
            (user_id, month),
        )
        self.conn.commit()
        return cur.lastrowid

    def _cycle(self, cycle_id: int):
        return self.conn.execute(
            "SELECT * FROM budget_cycles WHERE id=?", (cycle_id,)
        ).fetchone()

    # ---- core transaction write ----
    def _add_txn(self, user_id, cycle_id, ttype, amount, meal_slot_id=None, note=None):
        if ttype not in VALID_TYPES:
            raise ValueError(f"bad txn type: {ttype}")
        if amount < 0:
            raise ValueError("amount must be positive magnitude")
        self.conn.execute(
            "INSERT INTO ledger_transactions "
            "(user_id, cycle_id, meal_slot_id, amount, type, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, cycle_id, meal_slot_id, amount, ttype, note),
        )
        # keep cached total_spent in sync
        if ttype in DEBIT_TYPES:
            self.conn.execute(
                "UPDATE budget_cycles SET total_spent = total_spent + ? WHERE id=?",
                (amount, cycle_id),
            )
        elif ttype == "credit":
            self.conn.execute(
                "UPDATE budget_cycles SET total_spent = total_spent - ? WHERE id=?",
                (amount, cycle_id),
            )
        if ttype == "deposit":
            self.conn.execute(
                "UPDATE budget_cycles SET budget_allocated = budget_allocated + ? WHERE id=?",
                (amount, cycle_id),
            )
        elif ttype == "rollover":
            self.conn.execute(
                "UPDATE budget_cycles SET rolled_in = rolled_in + ? WHERE id=?",
                (amount, cycle_id),
            )
        self.conn.commit()

    # ---- public ops ----
    def deposit(self, user_id, month, amount, note="monthly budget"):
        cid = self.get_or_create_cycle(user_id, month)
        self._add_txn(user_id, cid, "deposit", amount, note=note)

    def debit(self, user_id, month, amount, meal_slot_id=None, note="meal ordered"):
        cid = self.get_or_create_cycle(user_id, month)
        self._add_txn(user_id, cid, "debit", amount, meal_slot_id, note)

    def credit(self, user_id, month, amount, meal_slot_id=None, note="meal skipped"):
        cid = self.get_or_create_cycle(user_id, month)
        self._add_txn(user_id, cid, "credit", amount, meal_slot_id, note)

    # ---- balances (derived, source of truth = transactions) ----
    def get_balance(self, user_id, month) -> float:
        """Spendable balance for a given cycle."""
        cid = self.get_or_create_cycle(user_id, month)
        rows = self.conn.execute(
            "SELECT type, SUM(amount) AS s FROM ledger_transactions "
            "WHERE cycle_id=? GROUP BY type",
            (cid,),
        ).fetchall()
        bal = 0.0
        for r in rows:
            bal += r["s"] if r["type"] in CREDIT_TYPES else -r["s"]
        return round(bal, 2)

    def get_summary(self, user_id, month) -> dict:
        c = self._cycle(self.get_or_create_cycle(user_id, month))
        return {
            "month": c["month"],
            "budget_allocated": c["budget_allocated"],
            "rolled_in": c["rolled_in"],
            "total_spent": c["total_spent"],
            "balance": self.get_balance(user_id, month),
            "status": c["status"],
        }

    # ---- month close + rollover ----
    def close_cycle(self, user_id, month) -> float:
        """Close cycle, carry leftover into next month as rollover. Returns rolled amount."""
        cid = self.get_or_create_cycle(user_id, month)
        c = self._cycle(cid)
        if c["status"] == "closed":
            raise ValueError(f"cycle {month} already closed")
        leftover = round(c["budget_allocated"] + c["rolled_in"] - c["total_spent"], 2)
        rolled = max(0.0, leftover)
        self.conn.execute(
            "UPDATE budget_cycles SET rolled_out=?, status='closed' WHERE id=?",
            (rolled, cid),
        )
        self.conn.commit()
        if rolled > 0:
            nm = next_month(month)
            ncid = self.get_or_create_cycle(user_id, nm)
            self._add_txn(user_id, ncid, "rollover", rolled,
                          note=f"rolled from {month}")
        return rolled

    def close(self):
        self.conn.close()
