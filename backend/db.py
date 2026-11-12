"""SQLite connection + schema init. Raw sqlite3, no ORM."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "mealplanner.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    area       TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    swiggy_key TEXT
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
    why_text        TEXT,                         -- cached "why this dish?" sentence
    -- Meal composition (see course.py). A curry is not a meal alone, so it
    -- carries a bread/rice accompaniment. `price` above stays the MAIN dish;
    -- total_price = price + side_price is what the meal actually costs.
    course              TEXT DEFAULT 'complete',  -- bread|staple|curry|complete|side
    side_dish_id        TEXT,
    side_dish_name      TEXT,
    side_qty            INTEGER DEFAULT 0,
    side_price          REAL DEFAULT 0,
    side_restaurant_name TEXT,
    side_image_url      TEXT,
    dish_kind TEXT DEFAULT 'meal',
    side2_dish_id TEXT,
    side2_dish_name TEXT,
    side2_qty INTEGER DEFAULT 0,
    side2_price REAL DEFAULT 0,
    side2_restaurant_name TEXT,
    side2_image_url TEXT,
    side_source TEXT DEFAULT '',
    side2_source TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_slot_plan ON meal_slots(plan_id);

-- ---- daily personalization (docs/SPEC-daily-personalization.md §3.3) ----
-- Keyed by user_id so a household can be layered on later.
CREATE TABLE IF NOT EXISTS user_profile (
    user_id           INTEGER PRIMARY KEY REFERENCES users(id),
    diet_type         TEXT NOT NULL DEFAULT 'veg',   -- veg|eggetarian|nonveg|jain|vegan
    weekday_overrides TEXT NOT NULL DEFAULT '{}',    -- {"1":"veg","3":"jain"} (Mon=0)
    allergies         TEXT NOT NULL DEFAULT '[]',    -- [{"name":"peanut","severe":true}]
    goal              TEXT NOT NULL DEFAULT 'maintain',  -- lose|maintain|gain|high_protein
    slots             TEXT NOT NULL DEFAULT '["breakfast","lunch","dinner"]',
    windows           TEXT NOT NULL DEFAULT '{}',    -- {"lunch":["12:00","15:00"]}
    monthly_budget    REAL NOT NULL DEFAULT 6000,
    city              TEXT,
    mode              TEXT NOT NULL DEFAULT 'dry_run',  -- live|dry_run
    updated_at        TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_menu (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    date         TEXT NOT NULL,
    slot         TEXT NOT NULL,
    generated_at TEXT DEFAULT (datetime('now')),
    refreshed_at TEXT,
    UNIQUE(user_id, date, slot)
);

CREATE TABLE IF NOT EXISTS menu_card (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    menu_id  INTEGER NOT NULL REFERENCES daily_menu(id) ON DELETE CASCADE,
    role     TEXT NOT NULL,          -- usual|gap|new|budget|chat
    position INTEGER NOT NULL DEFAULT 0,
    items    TEXT NOT NULL,          -- json [{source,id,name,restaurant_id,...,raw_variant}]
    price    REAL NOT NULL,
    nutrients TEXT NOT NULL DEFAULT '{}',
    score    REAL NOT NULL DEFAULT 0,
    reasons  TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS excluded_card (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    menu_id     INTEGER NOT NULL REFERENCES daily_menu(id) ON DELETE CASCADE,
    items       TEXT NOT NULL,
    allergen_hit TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consumption_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    date       TEXT NOT NULL,
    slot       TEXT NOT NULL,
    source     TEXT NOT NULL,        -- app_order|chat_log|nudge
    items      TEXT NOT NULL,        -- json [names]
    nutrients  TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback_event (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    ts        TEXT NOT NULL DEFAULT (datetime('now')),
    type      TEXT NOT NULL,          -- ordered|up|down|skip|not_today|never|off_plan|quiz|memory_edit
    dimension TEXT NOT NULL,          -- dish|cuisine|restaurant|ingredient|...
    key       TEXT NOT NULL,
    card_id   INTEGER,
    position  INTEGER,
    value     REAL NOT NULL DEFAULT 0  -- weight delta
);

CREATE TABLE IF NOT EXISTS pref_weight (
    user_id    INTEGER NOT NULL,
    dimension  TEXT NOT NULL,
    key        TEXT NOT NULL,
    weight     REAL NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now')),
    hard_block INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, dimension, key)
);

CREATE TABLE IF NOT EXISTS nutrition_ref (
    canonical  TEXT PRIMARY KEY,
    nutrients  TEXT NOT NULL,         -- per serving
    source     TEXT NOT NULL,         -- ifct|indb|llm|default
    confidence REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS order_record (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id    INTEGER NOT NULL,
    platform   TEXT NOT NULL,         -- food|instamart
    order_id   TEXT,
    status     TEXT NOT NULL,         -- placed|dry_run|failed
    mode       TEXT NOT NULL,
    amount     REAL NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_slot_id  INTEGER NOT NULL REFERENCES meal_slots(id),
    sent_at       TEXT DEFAULT (datetime('now')),
    user_response TEXT,                         -- yes|no|later|other
    resolved_at   TEXT
);
"""


def get_conn(db_path=DB_PATH):
    # timeout=30: FastAPI runs endpoints in a thread pool and every request
    # opens its own connection; without a busy timeout, one request's write
    # transaction made concurrent requests fail with "database is locked".
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # busy_timeout is the SQLite-level retry (distinct from Python's timeout);
    # synchronous=NORMAL is safe with WAL and faster.
    try:
        conn.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    try:
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    # WAL lets readers and a writer proceed concurrently instead of blocking.
    if str(db_path) != ":memory:":
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
    return conn


# Columns added after the original schema shipped. Existing dev DBs created with
# CREATE TABLE IF NOT EXISTS won't have them, so ALTER them in idempotently.
_MIGRATIONS = [
    # Swiggy account this user signed in with (auth: sign back in through Swiggy)
    ("users", "swiggy_key", "TEXT"),
    ("meal_slots", "restaurant_name", "TEXT"),
    ("meal_slots", "image_url", "TEXT"),
    ("meal_slots", "why_text", "TEXT"),
    # meal composition — curry + bread/rice pairing
    ("meal_slots", "course", "TEXT DEFAULT 'complete'"),
    ("meal_slots", "side_dish_id", "TEXT"),
    ("meal_slots", "side_dish_name", "TEXT"),
    ("meal_slots", "side_qty", "INTEGER DEFAULT 0"),
    ("meal_slots", "side_price", "REAL DEFAULT 0"),
    ("meal_slots", "side_restaurant_name", "TEXT"),
    ("meal_slots", "side_image_url", "TEXT"),
    ("meal_slots", "dish_kind", "TEXT DEFAULT 'meal'"),
    ("meal_slots", "side2_dish_id", "TEXT"),
    ("meal_slots", "side2_dish_name", "TEXT"),
    ("meal_slots", "side2_qty", "INTEGER DEFAULT 0"),
    ("meal_slots", "side2_price", "REAL DEFAULT 0"),
    ("meal_slots", "side2_restaurant_name", "TEXT"),
    ("meal_slots", "side2_image_url", "TEXT"),
    # Instamart pairing marker — "" = restaurant, "instamart" = grocery item
    # (see catalog.Dish.source). Display-only: the order executor never sends
    # side dishes to the restaurant cart.
    ("meal_slots", "side_source", "TEXT DEFAULT ''"),
    ("meal_slots", "side2_source", "TEXT DEFAULT ''"),
]


def migrate(conn):
    """Add any missing columns to existing tables. Idempotent; safe to re-run."""
    for table, col, coltype in _MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError as e:
            # "duplicate column name" -> already migrated; anything else re-raises
            # "no such table": SCHEMA creates it complete, nothing to add
            if "duplicate column" not in str(e).lower() and "no such table" not in str(e).lower():
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
