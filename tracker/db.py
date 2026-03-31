"""
SQLite schema and helpers for the cache efficiency tracker.

Database lives at tracker/cache_tracker.db by default.
"""

import sqlite3
from pathlib import Path
from typing import Any

# Default DB path relative to this file's directory
_DEFAULT_DB = Path(__file__).parent / "cache_tracker.db"

# Sonnet pricing (per token, converted from per-MTok rates)
_PRICE_INPUT = 3.00 / 1_000_000       # $3.00 / MTok
_PRICE_CACHE_READ = 0.30 / 1_000_000  # $0.30 / MTok
_PRICE_CACHE_CREATE = 3.75 / 1_000_000  # $3.75 / MTok
_PRICE_OUTPUT = 15.00 / 1_000_000     # $15.00 / MTok


_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id              INTEGER PRIMARY KEY,
    session_id      TEXT    UNIQUE NOT NULL,
    start_time      TEXT,
    mode            TEXT    CHECK(mode IN ('stock', 'patched', 'unknown')) DEFAULT 'unknown',
    claude_version  TEXT
);

CREATE TABLE IF NOT EXISTS turns (
    id                          INTEGER PRIMARY KEY,
    session_id                  TEXT    NOT NULL REFERENCES sessions(session_id),
    turn_number                 INTEGER NOT NULL,
    timestamp                   TEXT,
    cache_read_input_tokens     INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
    input_tokens                INTEGER NOT NULL DEFAULT 0,
    output_tokens               INTEGER NOT NULL DEFAULT 0,
    cost_estimate               REAL    NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
"""


def get_db(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (or create) the SQLite database and ensure schema exists.

    Args:
        path: Path to the .db file. Defaults to tracker/cache_tracker.db.

    Returns:
        An open sqlite3.Connection with WAL journal mode and row_factory set.
    """
    db_path = Path(path) if path else _DEFAULT_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_DDL)
    conn.commit()

    return conn


def upsert_session(
    conn: sqlite3.Connection,
    session_id: str,
    mode: str,
    version: str | None = None,
    start_time: str | None = None,
) -> None:
    """Insert a new session or update mode/version on an existing one.

    Args:
        conn: Active database connection.
        session_id: Unique Claude session identifier.
        mode: One of 'stock', 'patched', or 'unknown'.
        version: Optional Claude version string.
        start_time: Optional ISO-8601 timestamp for session start.
    """
    conn.execute(
        """
        INSERT INTO sessions (session_id, mode, claude_version, start_time)
        VALUES (:sid, :mode, :ver, :ts)
        ON CONFLICT(session_id) DO UPDATE SET
            mode          = excluded.mode,
            claude_version = COALESCE(excluded.claude_version, sessions.claude_version),
            start_time    = COALESCE(sessions.start_time, excluded.start_time)
        """,
        {"sid": session_id, "mode": mode, "ver": version, "ts": start_time},
    )
    conn.commit()


def insert_turn(
    conn: sqlite3.Connection,
    session_id: str,
    turn_number: int,
    timestamp: str,
    cache_read: int,
    cache_creation: int,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Record a single assistant turn with token usage and computed cost.

    Skips silently if this (session_id, turn_number) pair already exists,
    so the collector can safely re-process lines on restart.

    Args:
        conn: Active database connection.
        session_id: Claude session identifier (must exist in sessions table).
        turn_number: Sequential turn index within the session (1-based).
        timestamp: ISO-8601 timestamp string from the JSONL line.
        cache_read: cache_read_input_tokens from the usage dict.
        cache_creation: cache_creation_input_tokens from the usage dict.
        input_tokens: Regular (non-cached) input_tokens.
        output_tokens: output_tokens from the usage dict.
    """
    cost = (
        input_tokens * _PRICE_INPUT
        + cache_read * _PRICE_CACHE_READ
        + cache_creation * _PRICE_CACHE_CREATE
        + output_tokens * _PRICE_OUTPUT
    )

    conn.execute(
        """
        INSERT OR IGNORE INTO turns
            (session_id, turn_number, timestamp,
             cache_read_input_tokens, cache_creation_input_tokens,
             input_tokens, output_tokens, cost_estimate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id, turn_number, timestamp,
            cache_read, cache_creation,
            input_tokens, output_tokens,
            cost,
        ),
    )
    conn.commit()


def get_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return aggregate cache stats grouped by session mode.

    The 'estimated_savings_vs_no_cache' field is the difference between
    what the cache_read tokens would have cost at full input price vs the
    discounted cache_read price.

    Returns:
        Dict keyed by mode ('stock', 'patched', 'unknown'), each value being
        a dict with: total_sessions, total_turns, avg_cache_read_ratio,
        total_cache_read, total_cache_creation, total_input, total_output,
        estimated_total_cost, estimated_savings_vs_no_cache.
    """
    rows = conn.execute(
        """
        SELECT
            s.mode,
            COUNT(DISTINCT s.session_id)              AS total_sessions,
            COUNT(t.id)                               AS total_turns,
            -- ratio: cache_read / (cache_read + cache_creation + input), per turn avg
            AVG(
                CASE
                    WHEN (t.cache_read_input_tokens + t.cache_creation_input_tokens + t.input_tokens) > 0
                    THEN CAST(t.cache_read_input_tokens AS REAL)
                         / (t.cache_read_input_tokens + t.cache_creation_input_tokens + t.input_tokens)
                    ELSE 0.0
                END
            )                                         AS avg_cache_read_ratio,
            SUM(t.cache_read_input_tokens)            AS total_cache_read,
            SUM(t.cache_creation_input_tokens)        AS total_cache_creation,
            SUM(t.input_tokens)                       AS total_input,
            SUM(t.output_tokens)                      AS total_output,
            SUM(t.cost_estimate)                      AS estimated_total_cost,
            -- savings = cache_read tokens billed at input price minus what was actually paid
            SUM(t.cache_read_input_tokens * (? - ?))  AS estimated_savings_vs_no_cache
        FROM sessions s
        LEFT JOIN turns t ON t.session_id = s.session_id
        GROUP BY s.mode
        """,
        (_PRICE_INPUT, _PRICE_CACHE_READ),
    ).fetchall()

    result: dict[str, Any] = {}
    for row in rows:
        mode = row["mode"] or "unknown"
        result[mode] = {
            "total_sessions": row["total_sessions"],
            "total_turns": row["total_turns"],
            "avg_cache_read_ratio": row["avg_cache_read_ratio"] or 0.0,
            "total_cache_read": row["total_cache_read"] or 0,
            "total_cache_creation": row["total_cache_creation"] or 0,
            "total_input": row["total_input"] or 0,
            "total_output": row["total_output"] or 0,
            "estimated_total_cost": row["estimated_total_cost"] or 0.0,
            "estimated_savings_vs_no_cache": row["estimated_savings_vs_no_cache"] or 0.0,
        }

    return result
