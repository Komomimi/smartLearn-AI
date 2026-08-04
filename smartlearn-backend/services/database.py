"""SQLite persistence for SmartLearn sessions and chat history.

All database logic lives in this single module.  No ORM, no third-party
dependency — just Python's built-in ``sqlite3``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "smartlearn.db"


def _connect() -> sqlite3.Connection:
    """Open (or create) the database, enable WAL mode and foreign keys."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row  # allow dict-like access by column name
    return conn


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create tables and indexes if they don't already exist (idempotent).

    Call once on application startup.
    """
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            chat_id        TEXT PRIMARY KEY,
            filename       TEXT NOT NULL,
            file_path      TEXT NOT NULL,
            pages_json     TEXT NOT NULL,
            characters     INTEGER NOT NULL,
            model_name     TEXT,
            model_source   TEXT,
            artifacts_json TEXT,
            created_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     TEXT NOT NULL REFERENCES sessions(chat_id) ON DELETE CASCADE,
            question    TEXT NOT NULL,
            answer      TEXT NOT NULL,
            citations   TEXT,
            sources     TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id);

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------


def list_sessions() -> list[dict[str, Any]]:
    """Return all sessions, newest first.

    Returns lightweight summary dicts suitable for a sidebar list:
    ``{chat_id, filename, pages, characters, created_at}``.
    """
    conn = _connect()
    rows = conn.execute(
        "SELECT chat_id, filename, pages_json, characters, created_at "
        "FROM sessions ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    results: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        pages = json.loads(d.pop("pages_json", "[]"))
        d["pages"] = len(pages)
        results.append(d)
    return results


def get_session(chat_id: str) -> dict[str, Any] | None:
    """Return a full session row or ``None``.

    The returned dict includes parsed ``artifacts`` and ``pages`` ready for use
    by the retrieval pipeline.
    """
    conn = _connect()
    row = conn.execute("SELECT * FROM sessions WHERE chat_id = ?", (chat_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    # Decode JSON columns
    d["pages"] = json.loads(d.get("pages_json", "[]"))
    d["artifacts"] = json.loads(d.get("artifacts_json", "{}"))
    del d["pages_json"]
    if d.get("artifacts_json") is not None:
        del d["artifacts_json"]
    return d


def save_session(
    chat_id: str,
    filename: str,
    file_path: str,
    pages: list[dict[str, object]],
    characters: int,
    model_name: str | None = None,
    model_source: str | None = None,
    artifacts: dict[str, str] | None = None,
) -> None:
    """Insert or replace a session row (upsert by *chat_id*)."""
    conn = _connect()
    conn.execute(
        """INSERT OR REPLACE INTO sessions
           (chat_id, filename, file_path, pages_json, characters,
            model_name, model_source, artifacts_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            chat_id,
            filename,
            file_path,
            json.dumps(pages, ensure_ascii=False),
            characters,
            model_name,
            model_source,
            json.dumps(artifacts, ensure_ascii=False) if artifacts else None,
        ),
    )
    conn.commit()
    conn.close()


def delete_session(chat_id: str) -> bool:
    """Delete a session and its messages (cascade). Returns ``True`` if deleted."""
    conn = _connect()
    cursor = conn.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


# ---------------------------------------------------------------------------
# Messages (chat history)
# ---------------------------------------------------------------------------


def get_messages(chat_id: str) -> list[dict[str, Any]]:
    """Return all messages for a session, oldest first, as a list of dicts.

    Each dict has keys ``question``, ``answer``, ``citations`` (list[int]),
    and ``sources`` (list[dict]).
    """
    conn = _connect()
    rows = conn.execute(
        "SELECT question, answer, citations, sources, created_at "
        "FROM messages WHERE chat_id = ? ORDER BY id ASC",
        (chat_id,),
    ).fetchall()
    conn.close()
    messages: list[dict[str, Any]] = []
    for r in rows:
        msg = dict(r)
        msg["citations"] = json.loads(msg["citations"]) if msg.get("citations") else []
        msg["sources"] = json.loads(msg["sources"]) if msg.get("sources") else []
        messages.append(msg)
    return messages


def save_message(
    chat_id: str,
    question: str,
    answer: str,
    citations: list[int] | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> int:
    """Append a chat message. Returns the new row id."""
    conn = _connect()
    cursor = conn.execute(
        "INSERT INTO messages (chat_id, question, answer, citations, sources) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            chat_id,
            question,
            answer,
            json.dumps(citations, ensure_ascii=False) if citations else None,
            json.dumps(sources, ensure_ascii=False) if sources else None,
        ),
    )
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id


# ---------------------------------------------------------------------------
# Settings (key-value store)
# ---------------------------------------------------------------------------


def get_setting(key: str, default: str = "") -> str:
    """Return a setting value or *default*."""
    conn = _connect()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """Insert or update a setting."""
    conn = _connect()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()
    conn.close()


def get_all_settings() -> dict[str, str]:
    """Return all settings as a flat dict."""
    conn = _connect()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}
