"""
SQLite storage. Deliberately boring — one file, no ORM, no migrations
framework. The whole schema is visible below in one screen.

Connection discipline: every caller uses `with get_conn() as c:` and
finishes its transaction before starting another one. Nested connections
while a write transaction is open cause "database is locked" under
SQLite, which is a genuinely confusing error to debug later.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id            TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    stored_path   TEXT NOT NULL,
    origin        TEXT NOT NULL,          -- k5 | drive | upload
    origin_detail TEXT,                   -- source URL / drive link / '-'
    page_count    INTEGER,
    extracted_text TEXT,
    added_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    grade       INTEGER,               -- NULL = suits any grade
    stored_path TEXT NOT NULL,
    file_kind   TEXT NOT NULL,         -- pdf | docx
    added_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches (
    id             TEXT PRIMARY KEY,
    source_id      TEXT NOT NULL,
    grade          INTEGER NOT NULL,
    difficulty     TEXT NOT NULL,
    variant_count  INTEGER NOT NULL,
    question_count INTEGER,
    vary_dimensions TEXT NOT NULL,        -- JSON list
    closing_message TEXT,
    extra_instructions TEXT,
    status         TEXT NOT NULL,         -- generating | ready | failed
    error          TEXT,
    created_at     TEXT NOT NULL,
    mode           TEXT NOT NULL DEFAULT 'reframe',  -- comma-separated: reframe,expand
    template_id    TEXT,                             -- NULL = Bhanzu house style
    FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS worksheets (
    id            TEXT PRIMARY KEY,
    batch_id      TEXT NOT NULL,
    variant_index INTEGER NOT NULL,
    title         TEXT NOT NULL,
    skill         TEXT,
    questions     TEXT NOT NULL,          -- JSON list
    closing_note  TEXT,
    review_status TEXT NOT NULL,          -- draft | approved | rejected
    validation    TEXT,                   -- JSON verdict from app/validate.py
    export_path   TEXT,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES batches(id)
);

CREATE TABLE IF NOT EXISTS revisions (
    id           TEXT PRIMARY KEY,
    worksheet_id TEXT NOT NULL,
    instruction  TEXT NOT NULL,
    scope        TEXT NOT NULL,           -- images | questions | both
    created_at   TEXT NOT NULL,
    FOREIGN KEY (worksheet_id) REFERENCES worksheets(id)
);

CREATE TABLE IF NOT EXISTS canva_connection (
    -- Single row (id always 'default'). Canva's Autofill API needs a real
    -- person to authorize once via OAuth (Authorization Code + PKCE) --
    -- this is NOT a static API key, it's a live connection that can expire
    -- or be revoked, hence a table rather than a .env value.
    id             TEXT PRIMARY KEY DEFAULT 'default',
    access_token   TEXT NOT NULL,   -- encrypted at rest, see providers/canva.py
    refresh_token  TEXT NOT NULL,   -- encrypted at rest
    expires_at     TEXT NOT NULL,   -- ISO timestamp
    connected_by   TEXT,            -- whatever Canva's /users/me returns, if available
    connected_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_state (
    -- Short-lived PKCE state for the in-flight authorization request.
    -- Deleted once the callback completes; a leftover row just means an
    -- attempt was abandoned, not a security issue since it's single-use.
    state          TEXT PRIMARY KEY,
    code_verifier  TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
    id         TEXT PRIMARY KEY,
    action     TEXT NOT NULL,
    detail     TEXT,
    created_at TEXT NOT NULL
);
"""


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as c:
        c.executescript(SCHEMA)
        # Lightweight migration for databases created before a column
        # existed. Cheaper than a migration framework at this size, and
        # it means an existing library survives an upgrade.
        existing = {r["name"] for r in c.execute("PRAGMA table_info(batches)")}
        if "mode" not in existing:
            c.execute("ALTER TABLE batches ADD COLUMN mode TEXT NOT NULL "
                       "DEFAULT 'reframe'")
        if "template_id" not in existing:
            c.execute("ALTER TABLE batches ADD COLUMN template_id TEXT")
        ws_cols = {r["name"] for r in c.execute("PRAGMA table_info(worksheets)")}
        if "validation" not in ws_cols:
            c.execute("ALTER TABLE worksheets ADD COLUMN validation TEXT")


def log_activity(action: str, detail: str = "") -> None:
    """Plain-English activity trail shown in the UI.

    `action` must already be human-readable ("Worksheets written"), never
    an internal code — nothing backend-shaped should reach the screen.
    """
    with get_conn() as c:
        c.execute(
            "INSERT INTO activity (id, action, detail, created_at) VALUES (?,?,?,?)",
            (new_id(), action, detail, now()),
        )


# ── Row helpers ────────────────────────────────────────────────────
def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def worksheet_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["questions"] = json.loads(d["questions"])
    d["validation"] = json.loads(d["validation"]) if d.get("validation") else None
    return d
