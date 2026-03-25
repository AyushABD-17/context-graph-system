"""
memory.py — Persistent conversation memory for the SAP Graph chat.

Uses a separate SQLite DB file (memory.db) so it doesn't collide with graph.db.
Provides save/load operations for conversation turns with session IDs.
"""

import sqlite3
import json
import os
from datetime import datetime

MEMORY_DB = os.path.join(os.path.dirname(__file__), "memory.db")


def get_conn():
    conn = sqlite3.connect(MEMORY_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_memory_db():
    """Create the conversations table if it doesn't exist."""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            text TEXT NOT NULL,
            sql_query TEXT,
            row_count INTEGER DEFAULT 0,
            highlighted_node_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON conversations(session_id, id)")
    conn.commit()
    conn.close()


def save_turn(session_id: str, role: str, text: str,
              sql_query: str = None, row_count: int = 0,
              highlighted_node_count: int = 0):
    """Append a single conversation turn to memory."""
    conn = get_conn()
    conn.execute(
        """INSERT INTO conversations
           (session_id, role, text, sql_query, row_count, highlighted_node_count, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session_id, role, text, sql_query, row_count,
         highlighted_node_count, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()


def load_history(session_id: str, limit: int = 30) -> list:
    """Load the most recent `limit` turns for a session."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT role, text, sql_query, row_count, highlighted_node_count, created_at
           FROM conversations
           WHERE session_id = ?
           ORDER BY id DESC LIMIT ?""",
        (session_id, limit)
    ).fetchall()
    conn.close()
    # Reverse so oldest is first (chronological order)
    turns = []
    for r in reversed(rows):
        turn = {
            "role": r["role"],
            "text": r["text"],
            "created_at": r["created_at"],
        }
        if r["sql_query"]:
            turn["sql"] = r["sql_query"]
        if r["row_count"]:
            turn["row_count"] = r["row_count"]
        if r["highlighted_node_count"]:
            turn["highlighted_node_count"] = r["highlighted_node_count"]
        turns.append(turn)
    return turns


def list_sessions(limit: int = 50) -> list:
    """Return recent unique sessions with message count."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT session_id, COUNT(*) as msg_count, MAX(created_at) as last_active
           FROM conversations
           GROUP BY session_id
           ORDER BY last_active DESC
           LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return [{"session_id": r["session_id"], "msg_count": r["msg_count"],
             "last_active": r["last_active"]} for r in rows]
