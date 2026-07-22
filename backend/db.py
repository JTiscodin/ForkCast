"""SQLite connection + schema init. Raw sqlite3, no ORM."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "mealplanner.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    area       TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS budget_cycles (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    month            TEXT NOT NULL,               -- "2026-07"
    budget_allocated REAL NOT NULL DEFAULT 0,
    rolled_in        REAL NOT NULL DEFAULT 0,
    total_spent      REAL NOT NULL DEFAULT 0,     -- cached, recomputable
    rolled_out       REAL NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'active',  -- active | closed
    created_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, month)
);

CREATE TABLE IF NOT EXISTS ledger_transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    cycle_id     INTEGER NOT NULL REFERENCES budget_cycles(id),
    meal_slot_id INTEGER,                          -- nullable, links to meal
    amount       REAL NOT NULL,                    -- always positive magnitude
    type         TEXT NOT NULL,                    -- deposit|rollover|debit|credit
    note         TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_txn_cycle ON ledger_transactions(cycle_id);
CREATE INDEX IF NOT EXISTS idx_txn_user  ON ledger_transactions(user_id);

CREATE TABLE IF NOT EXISTS appetite_profiles (
    user_id         INTEGER PRIMARY KEY REFERENCES users(id),
    appetite_level  TEXT NOT NULL DEFAULT 'moderate',
    base_multiplier REAL NOT NULL DEFAULT 1.0,
    roti_per_meal   INTEGER,
    rice_katori     INTEGER,
    per_slot_json   TEXT                    -- {"breakfast":..,"lunch":..,"dinner":..}
);

CREATE TABLE IF NOT EXISTS plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    month       TEXT NOT NULL,
    budget      REAL NOT NULL,
    total_cost  REAL NOT NULL DEFAULT 0,
    feasible    INTEGER NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'draft',  -- draft|approved|active|done
    message     TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meal_slots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL REFERENCES plans(id),
    day             INTEGER NOT NULL,             -- 1..days
    meal_type       TEXT NOT NULL,                -- breakfast|lunch|dinner
    dish_id         TEXT NOT NULL,
    dish_name       TEXT,
    restaurant_id   TEXT,
    restaurant_name TEXT,
    image_url       TEXT,
    price           REAL NOT NULL,                -- portion-adjusted planned price
    rating          REAL,
    variant         TEXT,
    status          TEXT NOT NULL DEFAULT 'planned',  -- planned|confirmed|skipped|rescheduled
    order_id        TEXT,
    why_text        TEXT                          -- cached "why this dish?" sentence
);

CREATE INDEX IF NOT EXISTS idx_slot_plan ON meal_slots(plan_id);

CREATE TABLE IF NOT EXISTS notifications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_slot_id  INTEGER NOT NULL REFERENCES meal_slots(id),
    sent_at       TEXT DEFAULT (datetime('now')),
    user_response TEXT,                         -- yes|no|later|other
    resolved_at   TEXT
);
"""


def get_conn(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Columns added after the original schema shipped. Existing dev DBs created with
# CREATE TABLE IF NOT EXISTS won't have them, so ALTER them in idempotently.
_MIGRATIONS = [
    ("meal_slots", "restaurant_name", "TEXT"),
    ("meal_slots", "image_url", "TEXT"),
    ("meal_slots", "why_text", "TEXT"),
]


def migrate(conn):
    """Add any missing columns to existing tables. Idempotent; safe to re-run."""
    for table, col, coltype in _MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError as e:
            # "duplicate column name" -> already migrated; anything else re-raises
            if "duplicate column" not in str(e).lower():
                raise
    conn.commit()


def init_db(db_path=DB_PATH):
    conn = get_conn(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    migrate(conn)
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {DB_PATH}")
