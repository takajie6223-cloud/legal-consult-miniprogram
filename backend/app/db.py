import sqlite3
import threading
import uuid
from pathlib import Path

from .config import DB_PATH

_local = threading.local()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        _local.conn = c
    return c


def init_db() -> None:
    conn().executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
          id TEXT PRIMARY KEY, openid TEXT UNIQUE, nickname TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS sessions(
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
          created_at TEXT DEFAULT (datetime('now')),
          updated_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS messages(
          id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
          role TEXT NOT NULL, content TEXT NOT NULL, intent TEXT,
          citations TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS feedback(
          id TEXT PRIMARY KEY, message_id INTEGER NOT NULL, user_id TEXT NOT NULL,
          rating INTEGER NOT NULL, comment TEXT, created_at TEXT DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);
        """
    )
    conn().commit()


def new_id() -> str:
    return uuid.uuid4().hex
