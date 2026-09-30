"""STIP backend — additive schema migrations.

Fresh databases get everything from models' create_all(). Existing
databases (from earlier releases) get the v3 additions applied here:
new columns via ALTER TABLE ADD COLUMN, new uniqueness via CREATE UNIQUE
INDEX, then data backfills. Never drops or rewrites — always additive,
and idempotent (safe to run on every startup).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# table -> [(column, ddl)]
NEW_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "users": [("identifier_verified", "BOOLEAN DEFAULT 0")],
    "devices": [
        ("platform", "VARCHAR(64)"),
        ("trusted", "BOOLEAN DEFAULT 0"),
        ("verified_at", "DATETIME"),
    ],
    "conversations": [("seq", "INTEGER DEFAULT 0")],
    "conversation_members": [("hidden", "BOOLEAN DEFAULT 0")],
    "messages": [
        ("client_msg_id", "VARCHAR(64)"),
        ("hidden", "BOOLEAN DEFAULT 0"),
        ("ciphertext", "TEXT"),
    ],
    "cosmetics": [
        ("status", "VARCHAR(16) DEFAULT 'live'"),
        ("publish_at", "DATETIME"),
    ],
}


def ensure_additive_schema(engine) -> None:
    """Add missing v3 columns / indexes to an existing database. No-op on
    fresh databases (create_all already created them)."""
    with engine.begin() as conn:
        tables = {r[0] for r in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'").all()}
        for table, cols in NEW_COLUMNS.items():
            if table not in tables:
                continue  # create_all covers truly new tables
            existing = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})").all()}
            for name, ddl in cols:
                if name not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        # idempotent-send dedupe key (partial NULLs are distinct in SQLite,
        # so sends without a client_msg_id are unaffected)
        if "messages" in tables:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_msg_client_id "
                "ON messages(conversation_id, sender_id, client_msg_id)")


def backfill_v3(db: Session) -> None:
    """Data backfills for databases created before v3."""
    # existing (non-shell) users are grandfathered as verified (ADR-002)
    db.execute(text(
        "UPDATE users SET identifier_verified = 1 "
        "WHERE identifier_verified = 0 AND username NOT GLOB 'pending_*'"))
    # conversation seq from historical max server_sequence
    db.execute(text(
        "UPDATE conversations SET seq = COALESCE("
        "(SELECT MAX(server_sequence) FROM messages "
        "WHERE messages.conversation_id = conversations.id), 0) "
        "WHERE seq = 0"))
    db.commit()
