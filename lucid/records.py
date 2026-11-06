"""Saved games, clubs, discussions, progress, and ratings."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from lucid.db import utc_now
from lucid.elo import update

LEVEL_SIZE = 100
RANKS = (
    (1, "Initiate"),
    (3, "Disciple"),
    (6, "Strategist"),
    (10, "Scholar"),
    (15, "Master"),
)
ACHIEVEMENTS = {
    "first_game": "Played a complete game",
    "first_puzzle": "Solved a chess puzzle",
    "streak_3": "Trained three days in a row",
    "club_founder": "Created a club",
    "ten_training": "Finished ten training sessions",
    "first_lesson": "Finished a lesson",
}


def level_for(xp: int) -> int:
    return 1 + max(0, xp) // LEVEL_SIZE


def rank_for(xp: int) -> str:
    level = level_for(xp)
    name = RANKS[0][1]
    for minimum, title in RANKS:
        if level >= minimum:
            name = title
    return name


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:40] or "club"


class Records:
    def __init__(self, database):
        self.db = database

    def ensure_username(self, user) -> str:
        if user["username"]:
            return user["username"]
        base = re.sub(r"[^a-z0-9]", "", (user["name"] or "student").lower()) or "student"
        candidate = base
        number = 1
        while self.username_owner(candidate):
            number += 1
            candidate = f"{base}{number}"
        with self.db.connect() as connection:
            connection.execute("UPDATE users SET username = ? WHERE id = ?", (candidate, user["id"]))
        return candidate

    def username_owner(self, username: str):
        with self.db.connect() as connection:
            return connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    def public_user(self, username: str):
        return self.username_owner(username)

    def update_profile(self, user_id: int, username: str, bio: str, emblem: str) -> str | None:
        username = re.sub(r"[^a-z0-9]", "", username.lower())
        if len(username) < 3 or len(username) > 20:
            return "Usernames are 3 to 20 letters or numbers."
        owner = self.username_owner(username)
        if owner and owner["id"] != user_id:
            return "That username is already taken."
        if emblem not in {"seal", "crane", "fan", "torii"}:
            emblem = "seal"
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE users SET username = ?, bio = ?, emblem = ? WHERE id = ?",
                (username, bio[:280], emblem, user_id),
            )
        return None

    def touch(self, user_id: int) -> None:
        today = date.today().isoformat()
        with self.db.connect() as connection:
            row = connection.execute("SELECT streak, longest_streak, last_active FROM users WHERE id = ?", (user_id,)).fetchone()
            last = (row["last_active"] or "")[:10]
            streak = row["streak"] or 0
            if last == today:
                return
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            streak = streak + 1 if last == yesterday else 1
            longest = max(row["longest_streak"] or 0, streak)
            connection.execute(
                "UPDATE users SET streak = ?, longest_streak = ?, last_active = ? WHERE id = ?",
                (streak, longest, today, user_id),
            )
        if streak >= 3:
            self.grant(user_id, "streak_3")

    def add_xp(self, user_id: int, amount: int) -> None:
        if amount <= 0:
            return
        with self.db.connect() as connection:
            connection.execute("UPDATE users SET xp = xp + ? WHERE id = ?", (amount, user_id))

    def grant(self, user_id: int, code: str) -> None:
        if code not in ACHIEVEMENTS:
            return
        with self.db.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO achievements (user_id, code, earned_at) VALUES (?, ?, ?)",
                (user_id, code, utc_now()),
            )

    def achievements(self, user_id: int) -> list:
        with self.db.connect() as connection:
            return connection.execute(
                "SELECT code, earned_at FROM achievements WHERE user_id = ? ORDER BY earned_at",
                (user_id,),
            ).fetchall()

    def set_elo(self, user_id: int, rating: int) -> None:
        with self.db.connect() as connection:
            connection.execute("UPDATE users SET chess_elo = ? WHERE id = ?", (rating, user_id))

    def create_game(self, **fields) -> str:
        code = fields["code"]
        with self.db.connect() as connection:
            connection.execute(
                """
                INSERT INTO games (
                    code, white_id, black_id, mode, ai_level, fen, moves, status,
                    white_ms, black_ms, last_tick, white_elo, black_elo, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    fields["white_id"],
                    fields.get("black_id"),
                    fields["mode"],
                    fields.get("ai_level"),
                    fields["fen"],
                    fields["status"],
                    fields["white_ms"],
                    fields["black_ms"],
                    fields.get("last_tick"),
                    fields.get("white_elo"),
                    fields.get("black_elo"),
                    utc_now(),
                ),
            )
        return code

    def game(self, code: str):
        with self.db.connect() as connection:
            return connection.execute("SELECT * FROM games WHERE code = ?", (code,)).fetchone()

    def save_game(self, code: str, **fields) -> None:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self.db.connect() as connection:
            connection.execute(
                f"UPDATE games SET {assignments} WHERE code = ?",
                (*fields.values(), code),
            )

    def games_for(self, user_id: int, limit: int = 20) -> list:
        with self.db.connect() as connection:
            return connection.execute(
                """
                SELECT * FROM games
                WHERE white_id = ? OR black_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (user_id, user_id, limit),
            ).fetchall()

    def finish_ratings(self, game, result: str) -> None:
        if game["mode"] not in {"ai", "link"}:
            return
        score = {"1-0": 1.0, "1/2-1/2": 0.5, "0-1": 0.0}[result]
        if game["mode"] == "ai":
            player_id = game["white_id"]
            player = self.db.get_user(player_id)
            new_rating = update(player["chess_elo"], game["black_elo"], score)
            self.set_elo(player_id, new_rating)
            return
        white = self.db.get_user(game["white_id"])
        black = self.db.get_user(game["black_id"])
        if white is None or black is None:
            return
        self.set_elo(white["id"], update(white["chess_elo"], black["chess_elo"], score))
        self.set_elo(black["id"], update(black["chess_elo"], white["chess_elo"], 1 - score))

    def create_club(self, owner_id: int, name: str, description: str) -> str:
        base = slugify(name)
        slug = base
        number = 1
        while self.club(slug):
            number += 1
            slug = f"{base}-{number}"
        with self.db.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO clubs (name, slug, description, owner_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (name[:60], slug, description[:500], owner_id, utc_now()),
            )
            connection.execute(
                "INSERT INTO club_members (club_id, user_id, role) VALUES (?, ?, 'owner')",
                (cursor.lastrowid, owner_id),
            )
        self.grant(owner_id, "club_founder")
        self.add_xp(owner_id, 20)
        return slug

    def clubs(self) -> list:
        with self.db.connect() as connection:
            return connection.execute(
                """
                SELECT clubs.*, COUNT(club_members.user_id) AS members
                FROM clubs LEFT JOIN club_members ON clubs.id = club_members.club_id
                GROUP BY clubs.id ORDER BY clubs.id DESC
                """
            ).fetchall()

    def club(self, slug: str):
        with self.db.connect() as connection:
            return connection.execute("SELECT * FROM clubs WHERE slug = ?", (slug,)).fetchone()

    def members(self, club_id: int) -> list:
        with self.db.connect() as connection:
            return connection.execute(
                """
                SELECT users.username, users.chess_elo, users.xp, club_members.role
                FROM club_members JOIN users ON users.id = club_members.user_id
                WHERE club_members.club_id = ?
                ORDER BY users.chess_elo DESC
                """,
                (club_id,),
            ).fetchall()

    def member_ids(self, club_id: int) -> set[int]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT user_id FROM club_members WHERE club_id = ?", (club_id,)).fetchall()
        return {row["user_id"] for row in rows}

    def join_club(self, club_id: int, user_id: int) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO club_members (club_id, user_id, role) VALUES (?, ?, 'member')",
                (club_id, user_id),
            )

    def user_clubs(self, user_id: int) -> list:
        with self.db.connect() as connection:
            return connection.execute(
                """
                SELECT clubs.* FROM clubs
                JOIN club_members ON clubs.id = club_members.club_id
                WHERE club_members.user_id = ?
                """,
                (user_id,),
            ).fetchall()

    def add_thread(self, author_id: int, title: str, body: str, category: str, club_id: int | None) -> int:
        with self.db.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO threads (club_id, category, title, body, author_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (club_id, category, title[:120], body[:4000], author_id, utc_now()),
            )
            return cursor.lastrowid

    def threads(self, category: str | None = None, club_id: int | None = None) -> list:
        query = """
            SELECT threads.*, users.username,
                   (SELECT COUNT(*) FROM comments WHERE comments.thread_id = threads.id) AS replies,
                   (SELECT COUNT(*) FROM reactions WHERE reactions.thread_id = threads.id) AS likes
            FROM threads JOIN users ON users.id = threads.author_id
            WHERE 1 = 1
        """
        values: list = []
        if category:
            query += " AND threads.category = ?"
            values.append(category)
        if club_id is None:
            query += " AND threads.club_id IS NULL"
        else:
            query += " AND threads.club_id = ?"
            values.append(club_id)
        query += " ORDER BY threads.id DESC"
        with self.db.connect() as connection:
            return connection.execute(query, values).fetchall()

    def thread(self, thread_id: int):
        with self.db.connect() as connection:
            return connection.execute(
                """
                SELECT threads.*, users.username,
                       (SELECT COUNT(*) FROM reactions WHERE reactions.thread_id = threads.id) AS likes
                FROM threads JOIN users ON users.id = threads.author_id
                WHERE threads.id = ?
                """,
                (thread_id,),
            ).fetchone()

    def comments(self, thread_id: int) -> list:
        with self.db.connect() as connection:
            return connection.execute(
                """
                SELECT comments.*, users.username FROM comments
                JOIN users ON users.id = comments.author_id
                WHERE comments.thread_id = ? ORDER BY comments.id
                """,
                (thread_id,),
            ).fetchall()

    def add_comment(self, thread_id: int, author_id: int, body: str) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO comments (thread_id, author_id, body, created_at) VALUES (?, ?, ?, ?)",
                (thread_id, author_id, body[:2000], utc_now()),
            )
        self.add_xp(author_id, 4)

    def like(self, user_id: int, thread_id: int) -> None:
        with self.db.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO reactions (user_id, thread_id) VALUES (?, ?)",
                (user_id, thread_id),
            )

    def bookmark(self, user_id: int, lesson_id: str, present: bool) -> None:
        with self.db.connect() as connection:
            if present:
                connection.execute("DELETE FROM bookmarks WHERE user_id = ? AND lesson_id = ?", (user_id, lesson_id))
            else:
                connection.execute("INSERT OR IGNORE INTO bookmarks (user_id, lesson_id) VALUES (?, ?)", (user_id, lesson_id))

    def bookmarks(self, user_id: int) -> set[str]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT lesson_id FROM bookmarks WHERE user_id = ?", (user_id,)).fetchall()
        return {row["lesson_id"] for row in rows}

    def complete_lesson(self, user_id: int, lesson_id: str) -> None:
        with self.db.connect() as connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO lesson_progress (user_id, lesson_id) VALUES (?, ?)",
                (user_id, lesson_id),
            ).rowcount
        if inserted:
            self.add_xp(user_id, 12)
            self.grant(user_id, "first_lesson")

    def finished_lessons(self, user_id: int) -> set[str]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT lesson_id FROM lesson_progress WHERE user_id = ?", (user_id,)).fetchall()
        return {row["lesson_id"] for row in rows}

    def opening_ply(self, user_id: int, opening_id: str) -> int:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT ply FROM opening_progress WHERE user_id = ? AND opening_id = ?",
                (user_id, opening_id),
            ).fetchone()
        return row["ply"] if row else 0

    def set_opening_ply(self, user_id: int, opening_id: str, ply: int) -> None:
        with self.db.connect() as connection:
            connection.execute(
                """
                INSERT INTO opening_progress (user_id, opening_id, ply) VALUES (?, ?, ?)
                ON CONFLICT(user_id, opening_id) DO UPDATE SET ply = excluded.ply
                """,
                (user_id, opening_id, ply),
            )

    def record_training(self, user_id: int, kind: str, correct: int, total: int, seconds: int) -> None:
        with self.db.connect() as connection:
            connection.execute(
                """
                INSERT INTO training_sessions (user_id, kind, correct, total, seconds, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, kind, correct, total, max(1, seconds), utc_now()),
            )
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM training_sessions WHERE user_id = ?",
                (user_id,),
            ).fetchone()["n"]
        self.add_xp(user_id, 8 + correct * 2)
        if count >= 10:
            self.grant(user_id, "ten_training")

    def training_stats(self, user_id: int) -> dict:
        with self.db.connect() as connection:
            rows = connection.execute(
                """
                SELECT kind, SUM(correct) AS correct, SUM(total) AS total, COUNT(*) AS sessions
                FROM training_sessions WHERE user_id = ? GROUP BY kind
                """,
                (user_id,),
            ).fetchall()
        return {row["kind"]: dict(row) for row in rows}

    def toggle_plan(self, user_id: int, item_id: str) -> None:
        added = False
        with self.db.connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM plans WHERE user_id = ? AND item_id = ?",
                (user_id, item_id),
            ).fetchone()
            if existing:
                connection.execute("DELETE FROM plans WHERE user_id = ? AND item_id = ?", (user_id, item_id))
            else:
                connection.execute("INSERT INTO plans (user_id, item_id) VALUES (?, ?)", (user_id, item_id))
                added = True
        if added:
            self.add_xp(user_id, 6)

    def plan_done(self, user_id: int) -> set[str]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT item_id FROM plans WHERE user_id = ?", (user_id,)).fetchall()
        return {row["item_id"] for row in rows}

    def leaderboard(self, field: str, limit: int = 20) -> list:
        if field not in {"chess_elo", "xp"}:
            field = "chess_elo"
        with self.db.connect() as connection:
            return connection.execute(
                f"""
                SELECT username, name, chess_elo, xp, streak FROM users
                WHERE age_confirmed = 1 AND username IS NOT NULL
                ORDER BY {field} DESC, id ASC LIMIT ?
                """,
                (limit,),
            ).fetchall()

    def weekly_results(self, member_ids: set[int] | None = None) -> list:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        with self.db.connect() as connection:
            games = connection.execute(
                """
                SELECT white_id, black_id, result FROM games
                WHERE status = 'finished' AND finished_at >= ? AND mode IN ('ai', 'link')
                """,
                (cutoff,),
            ).fetchall()
            training = connection.execute(
                "SELECT user_id FROM training_sessions WHERE created_at >= ?",
                (cutoff,),
            ).fetchall()
        scores: dict[int, int] = {}
        for game in games:
            for user_id, points in _game_points(game):
                if member_ids is None or user_id in member_ids:
                    scores[user_id] = scores.get(user_id, 0) + points
        for row in training:
            if member_ids is None or row["user_id"] in member_ids:
                scores[row["user_id"]] = scores.get(row["user_id"], 0) + 1
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:20]
        return [{"user": self.db.get_user(user_id), "points": points} for user_id, points in ranked]


def _game_points(game) -> list[tuple[int, int]]:
    if game["result"] == "1-0":
        return [(game["white_id"], 3)]
    if game["result"] == "0-1":
        return [(game["black_id"], 3)] if game["black_id"] else []
    if game["result"] == "1/2-1/2":
        points = [(game["white_id"], 1)]
        if game["black_id"] and game["black_id"] != game["white_id"]:
            points.append((game["black_id"], 1))
        return points
    return []
