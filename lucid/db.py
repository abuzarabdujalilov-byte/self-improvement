"""SQLite storage for accounts, attempts, keys, and conversations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    google_sub TEXT UNIQUE NOT NULL,
                    email TEXT,
                    name TEXT,
                    age_confirmed INTEGER NOT NULL DEFAULT 0,
                    chess_target INTEGER NOT NULL DEFAULT 1400,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS api_keys (
                    user_id INTEGER PRIMARY KEY,
                    nonce TEXT NOT NULL,
                    ciphertext TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    model_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    correct INTEGER,
                    answer_text TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assistant_context (
                    user_id INTEGER PRIMARY KEY,
                    text TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chess_sessions (
                    user_id INTEGER PRIMARY KEY,
                    puzzle_id TEXT NOT NULL,
                    ply INTEGER NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS logic_sessions (
                    user_id INTEGER PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY,
                    code TEXT UNIQUE NOT NULL,
                    white_id INTEGER,
                    black_id INTEGER,
                    mode TEXT NOT NULL,
                    ai_level TEXT,
                    fen TEXT NOT NULL,
                    moves TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    result TEXT,
                    reason TEXT,
                    white_ms INTEGER NOT NULL,
                    black_ms INTEGER NOT NULL,
                    last_tick TEXT,
                    white_elo INTEGER,
                    black_elo INTEGER,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS clubs (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    description TEXT NOT NULL,
                    owner_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS club_members (
                    club_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    PRIMARY KEY (club_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS threads (
                    id INTEGER PRIMARY KEY,
                    club_id INTEGER,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    author_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY,
                    thread_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reactions (
                    user_id INTEGER NOT NULL,
                    thread_id INTEGER NOT NULL,
                    PRIMARY KEY (user_id, thread_id)
                );
                CREATE TABLE IF NOT EXISTS bookmarks (
                    user_id INTEGER NOT NULL,
                    lesson_id TEXT NOT NULL,
                    PRIMARY KEY (user_id, lesson_id)
                );
                CREATE TABLE IF NOT EXISTS lesson_progress (
                    user_id INTEGER NOT NULL,
                    lesson_id TEXT NOT NULL,
                    PRIMARY KEY (user_id, lesson_id)
                );
                CREATE TABLE IF NOT EXISTS opening_progress (
                    user_id INTEGER NOT NULL,
                    opening_id TEXT NOT NULL,
                    ply INTEGER NOT NULL,
                    PRIMARY KEY (user_id, opening_id)
                );
                CREATE TABLE IF NOT EXISTS training_sessions (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    correct INTEGER NOT NULL,
                    total INTEGER NOT NULL,
                    seconds INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plans (
                    user_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    PRIMARY KEY (user_id, item_id)
                );
                CREATE TABLE IF NOT EXISTS achievements (
                    user_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    earned_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, code)
                );
                """
            )
            self._migrate(connection)

    def _migrate(self, connection) -> None:
        existing = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        additions = {
            "username": "TEXT",
            "bio": "TEXT NOT NULL DEFAULT ''",
            "emblem": "TEXT NOT NULL DEFAULT 'seal'",
            "chess_elo": "INTEGER NOT NULL DEFAULT 1200",
            "xp": "INTEGER NOT NULL DEFAULT 0",
            "streak": "INTEGER NOT NULL DEFAULT 0",
            "longest_streak": "INTEGER NOT NULL DEFAULT 0",
            "last_active": "TEXT",
        }
        for name, ddl in additions.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS users_username ON users(username) WHERE username IS NOT NULL"
        )

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def get_user(self, user_id: int) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def get_user_by_sub(self, google_sub: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub,)).fetchone()

    def create_user(self, google_sub: str, email: str, name: str) -> sqlite3.Row:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO users (google_sub, email, name, created_at) VALUES (?, ?, ?, ?)",
                (google_sub, email, name, utc_now()),
            )
            user_id = cursor.lastrowid
        return self.get_user(user_id)

    def confirm_age(self, user_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE users SET age_confirmed = 1 WHERE id = ?", (user_id,))
            connection.commit()

    def set_chess_target(self, user_id: int, target: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE users SET chess_target = ? WHERE id = ?", (target, user_id))
            connection.commit()

    def save_key(self, user_id: int, nonce: str, ciphertext: str, fingerprint: str, model_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO api_keys (user_id, nonce, ciphertext, fingerprint, model_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    nonce = excluded.nonce,
                    ciphertext = excluded.ciphertext,
                    fingerprint = excluded.fingerprint,
                    model_id = excluded.model_id
                """,
                (user_id, nonce, ciphertext, fingerprint, model_id),
            )
            connection.commit()

    def get_key_row(self, user_id: int) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM api_keys WHERE user_id = ?", (user_id,)).fetchone()

    def delete_key(self, user_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
            connection.commit()

    def set_model(self, user_id: int, model_id: str) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE api_keys SET model_id = ? WHERE user_id = ?", (model_id, user_id))
            connection.commit()

    def add_attempt(self, user_id: int, kind: str, item_id: str, correct: int | None, answer_text: str = "") -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO attempts (user_id, kind, item_id, correct, answer_text, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, kind, item_id, correct, answer_text, utc_now()),
            )
            connection.commit()

    def attempts(self, user_id: int, kind: str | None = None) -> list[sqlite3.Row]:
        with self.connect() as connection:
            if kind is None:
                rows = connection.execute(
                    "SELECT * FROM attempts WHERE user_id = ? ORDER BY id", (user_id,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM attempts WHERE user_id = ? AND kind = ? ORDER BY id",
                    (user_id, kind),
                ).fetchall()
        return rows

    def recent_item_ids(self, user_id: int, kind: str, limit: int = 12) -> set[str]:
        rows = self.attempts(user_id, kind)
        return {row["item_id"] for row in rows[-limit:]}

    def messages(self, user_id: int) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM messages WHERE user_id = ? ORDER BY id", (user_id,)
            ).fetchall()

    def add_message(self, user_id: int, role: str, text: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO messages (user_id, role, text, created_at) VALUES (?, ?, ?, ?)",
                (user_id, role, text, utc_now()),
            )
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE user_id = ?", (user_id,)
            ).fetchone()["n"]
            if count > 200:
                connection.execute(
                    """
                    DELETE FROM messages WHERE id IN (
                        SELECT id FROM messages WHERE user_id = ? ORDER BY id LIMIT ?
                    )
                    """,
                    (user_id, count - 200),
                )
            connection.commit()

    def clear_messages(self, user_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            connection.execute("DELETE FROM assistant_context WHERE user_id = ?", (user_id,))
            connection.commit()

    def set_context(self, user_id: int, text: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO assistant_context (user_id, text) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET text = excluded.text
                """,
                (user_id, text),
            )
            connection.commit()

    def get_context(self, user_id: int) -> str:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT text FROM assistant_context WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["text"] if row else ""

    def get_chess_session(self, user_id: int) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM chess_sessions WHERE user_id = ?", (user_id,)
            ).fetchone()

    def save_chess_session(self, user_id: int, puzzle_id: str, ply: int, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO chess_sessions (user_id, puzzle_id, ply, status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    puzzle_id = excluded.puzzle_id,
                    ply = excluded.ply,
                    status = excluded.status
                """,
                (user_id, puzzle_id, ply, status),
            )
            connection.commit()

    def clear_chess_session(self, user_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM chess_sessions WHERE user_id = ?", (user_id,))
            connection.commit()

    def get_logic_session(self, user_id: int) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM logic_sessions WHERE user_id = ?", (user_id,)
            ).fetchone()

    def save_logic_session(self, user_id: int, item_id: str, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO logic_sessions (user_id, item_id, status)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    item_id = excluded.item_id,
                    status = excluded.status
                """,
                (user_id, item_id, status),
            )
            connection.commit()
