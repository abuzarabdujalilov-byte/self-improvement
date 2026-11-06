"""Clubs, games, training, lessons, and public profiles."""

from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import chess
from flask import flash, g, redirect, render_template, request, session, url_for

from lucid import matches
from lucid.drills import KINDS, make_round
from lucid.elo import AI_RATINGS
from lucid.records import ACHIEVEMENTS, Records, level_for, rank_for

CONTENT = Path(__file__).parent / "content"
CATEGORIES = ("chess", "training", "science", "philosophy", "university", "general")
EMBLEMS = ("seal", "crane", "fan", "torii")


def register(app) -> None:
    database = app.config["DATABASE"]
    openings = json.loads((CONTENT / "openings.json").read_text(encoding="utf-8"))
    lessons = json.loads((CONTENT / "lessons.json").read_text(encoding="utf-8"))
    university = json.loads((CONTENT / "university.json").read_text(encoding="utf-8"))
    opening_by_id = {item["id"]: item for item in openings}
    lesson_by_id = {item["id"]: item for item in lessons}

    def records() -> Records:
        return Records(database)

    @app.get("/chess")
    def play_home():
        return render_template(
            "play_home.html",
            games=records().games_for(g.user["id"]),
            openings=openings,
            elo=g.user["chess_elo"],
        )

    @app.post("/chess/games")
    def play_new():
        mode = request.form.get("mode", "ai")
        level = request.form.get("level", "medium")
        if level not in AI_RATINGS:
            level = "medium"
        try:
            minutes = int(request.form.get("minutes", "10"))
        except ValueError:
            minutes = 10
        minutes = 5 if minutes < 10 else 15 if minutes > 10 else 10
        code = secrets.token_hex(4)
        now = datetime.now(timezone.utc).isoformat()
        records().create_game(
            code=code,
            white_id=g.user["id"],
            black_id=g.user["id"] if mode == "pass" else None,
            mode=mode if mode in {"ai", "pass", "link"} else "ai",
            ai_level=level if mode == "ai" else None,
            fen=chess.STARTING_FEN,
            status="waiting" if mode == "link" else "active",
            white_ms=minutes * 60 * 1000,
            black_ms=minutes * 60 * 1000,
            last_tick=None if mode == "link" else now,
            white_elo=g.user["chess_elo"],
            black_elo=AI_RATINGS[level] if mode == "ai" else None,
        )
        return redirect(url_for("play_game", code=code))

    @app.get("/chess/games/<code>")
    def play_game(code):
        game = records().game(code)
        if game is None or not _can_see(game, g.user["id"]):
            flash("That game is not available.")
            return redirect(url_for("play_home"))
        names = _names(database, game)
        return render_template(
            "play.html",
            game=game,
            view=matches.view(game, g.user["id"]),
            names=names,
            waiting=game["status"] == "waiting",
        )

    @app.post("/chess/games/<code>/move")
    def play_move(code):
        store = records()
        game = store.game(code)
        if game is None or game["status"] != "active":
            return redirect(url_for("play_game", code=code))
        board = matches.replay(game)
        white_ms, black_ms = matches.clock_now(game)
        if white_ms <= 0 or black_ms <= 0:
            result = "0-1" if white_ms <= 0 else "1-0"
            _finish(store, game, result, "time")
            return redirect(url_for("play_game", code=code))
        if not matches.side_to_move(game, g.user["id"], board):
            flash("It is not your turn.")
            return redirect(url_for("play_game", code=code))
        outcome = matches.apply_player_move(game, request.form.get("uci", "").strip(), white_ms, black_ms)
        if outcome.get("error"):
            flash(outcome["error"])
            return redirect(url_for("play_game", code=code))
        store.save_game(code, **outcome["fields"])
        game = store.game(code)
        if outcome["result"]:
            _award_finish(store, game, outcome["result"])
            return redirect(url_for("play_game", code=code))
        if game["mode"] == "ai":
            board = matches.replay(game)
            reply = matches.ai_reply(board, game["ai_level"] or "medium")
            if reply is not None:
                board.push(reply)
                moves = (game["moves"] + " " + reply.uci()).strip()
                finished = matches.outcome(board)
                fields = {
                    "fen": board.fen(),
                    "moves": moves,
                    "last_tick": datetime.now(timezone.utc).isoformat(),
                }
                if finished:
                    result, reason = finished
                    fields.update(status="finished", result=result, reason=reason, finished_at=datetime.now(timezone.utc).isoformat())
                store.save_game(code, **fields)
                if finished:
                    _award_finish(store, store.game(code), finished[0])
        return redirect(url_for("play_game", code=code))

    @app.post("/chess/games/<code>/resign")
    def play_resign(code):
        store = records()
        game = store.game(code)
        board = matches.replay(game) if game else None
        if game is None or game["status"] != "active" or not matches.side_to_move(game, g.user["id"], board):
            return redirect(url_for("play_home"))
        result = "0-1" if board.turn == chess.WHITE else "1-0"
        _finish(store, game, result, "resignation")
        return redirect(url_for("play_game", code=code))

    @app.post("/chess/games/<code>/join")
    def play_join(code):
        store = records()
        game = store.game(code)
        if game is None or game["mode"] != "link" or game["status"] != "waiting":
            flash("That table is not open.")
            return redirect(url_for("play_home"))
        if game["white_id"] == g.user["id"]:
            flash("Share the page with the other player.")
            return redirect(url_for("play_game", code=code))
        store.save_game(
            code,
            black_id=g.user["id"],
            black_elo=g.user["chess_elo"],
            status="active",
            last_tick=datetime.now(timezone.utc).isoformat(),
        )
        return redirect(url_for("play_game", code=code))

    @app.get("/chess/games/<code>/pgn")
    def play_pgn(code):
        game = records().game(code)
        if game is None or not _can_see(game, g.user["id"]):
            return redirect(url_for("play_home"))
        names = _names(database, game)
        from flask import Response

        body = matches.to_pgn(game, names["white"], names["black"])
        return Response(body, mimetype="text/plain; charset=utf-8")

    @app.post("/chess/import")
    def play_import():
        parsed = matches.import_pgn(request.form.get("pgn", ""))
        if isinstance(parsed, str):
            flash(parsed)
            return redirect(url_for("play_home"))
        moves, result = parsed
        code = secrets.token_hex(4)
        records().create_game(
            code=code,
            white_id=g.user["id"],
            black_id=None,
            mode="import",
            fen=chess.STARTING_FEN,
            status="finished",
            white_ms=0,
            black_ms=0,
            white_elo=g.user["chess_elo"],
        )
        records().save_game(
            code,
            moves=moves,
            result=None if result == "*" else result,
            reason="imported",
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        flash("Imported for review. An imported game does not change your rating.")
        return redirect(url_for("play_game", code=code))

    @app.get("/chess/openings/<opening_id>")
    def opening(opening_id):
        item = opening_by_id.get(opening_id)
        if item is None:
            return redirect(url_for("play_home"))
        ply = records().opening_ply(g.user["id"], opening_id)
        board = chess.Board()
        for step in item["line"][:ply]:
            board.push_uci(step["uci"])
        return render_template(
            "opening.html",
            opening=item,
            ply=ply,
            done=ply >= len(item["line"]),
            fen_view=_opening_view(board),
            expected=item["line"][ply]["san"] if ply < len(item["line"]) else "",
        )

    @app.post("/chess/openings/<opening_id>")
    def opening_move(opening_id):
        item = opening_by_id.get(opening_id)
        if item is None:
            return redirect(url_for("play_home"))
        store = records()
        ply = store.opening_ply(g.user["id"], opening_id)
        if ply >= len(item["line"]):
            return redirect(url_for("opening", opening_id=opening_id))
        uci = request.form.get("uci", "").strip()
        if uci == item["line"][ply]["uci"]:
            store.set_opening_ply(g.user["id"], opening_id, ply + 1)
            if ply + 1 == len(item["line"]):
                store.add_xp(g.user["id"], 20)
            flash(item["line"][ply]["note"])
        else:
            flash(f"The line continues with {item['line'][ply]['san']}. {item['line'][ply]['note']}")
        return redirect(url_for("opening", opening_id=opening_id))

    @app.get("/training")
    def training_home():
        return render_template("training.html", stats=records().training_stats(g.user["id"]), kinds=KINDS)

    @app.get("/training/<kind>")
    def training_drill(kind):
        if kind not in KINDS:
            return redirect(url_for("training_home"))
        state = session.get("drill")
        if not state or state.get("kind") != kind:
            state = {"kind": kind, "rounds": [make_round(kind) for _ in range(5)], "index": 0, "correct": 0, "started": time.time()}
            session["drill"] = state
        if state["index"] >= len(state["rounds"]):
            return render_template("drill.html", kind=kind, done=True, correct=state["correct"], total=len(state["rounds"]))
        return render_template("drill.html", kind=kind, done=False, round=state["rounds"][state["index"]], index=state["index"], total=len(state["rounds"]))

    @app.post("/training/<kind>")
    def training_answer(kind):
        state = session.get("drill")
        if not state or state.get("kind") != kind or state["index"] >= len(state["rounds"]):
            return redirect(url_for("training_drill", kind=kind))
        current = state["rounds"][state["index"]]
        given = request.form.get("answer", "").strip().lower()
        if given == str(current["answer"]).lower():
            state["correct"] += 1
            flash("Correct.")
        else:
            flash(f"The answer was {current['answer']}.")
        state["index"] += 1
        if state["index"] >= len(state["rounds"]):
            records().record_training(
                g.user["id"],
                kind,
                state["correct"],
                len(state["rounds"]),
                int(time.time() - state["started"]),
            )
        session["drill"] = state
        return redirect(url_for("training_drill", kind=kind))

    @app.post("/training/<kind>/again")
    def training_again(kind):
        session.pop("drill", None)
        return redirect(url_for("training_drill", kind=kind))

    @app.get("/learn")
    def learn():
        query = request.args.get("q", "").strip().lower()
        category = request.args.get("category", "")
        chosen = lessons
        if category:
            chosen = [item for item in chosen if item["category"] == category]
        if query:
            chosen = [item for item in chosen if query in item["title"].lower() or query in item["category"].lower()]
        store = records()
        return render_template(
            "learn.html",
            lessons=chosen,
            categories=sorted({item["category"] for item in lessons}),
            finished=store.finished_lessons(g.user["id"]),
            bookmarks=store.bookmarks(g.user["id"]),
            query=query,
            category=category,
        )

    @app.get("/learn/<lesson_id>")
    def lesson(lesson_id):
        item = lesson_by_id.get(lesson_id)
        if item is None:
            return redirect(url_for("learn"))
        related = [other for other in lessons if other["category"] == item["category"] and other["id"] != item["id"]]
        store = records()
        return render_template(
            "lesson.html",
            lesson=item,
            related=related,
            bookmarked=lesson_id in store.bookmarks(g.user["id"]),
            finished=lesson_id in store.finished_lessons(g.user["id"]),
        )

    @app.post("/learn/<lesson_id>/bookmark")
    def lesson_bookmark(lesson_id):
        if lesson_id not in lesson_by_id:
            return redirect(url_for("learn"))
        store = records()
        store.bookmark(g.user["id"], lesson_id, lesson_id in store.bookmarks(g.user["id"]))
        return redirect(url_for("lesson", lesson_id=lesson_id))

    @app.post("/learn/<lesson_id>/finish")
    def lesson_finish(lesson_id):
        if lesson_id in lesson_by_id:
            records().complete_lesson(g.user["id"], lesson_id)
        return redirect(url_for("lesson", lesson_id=lesson_id))

    @app.get("/university")
    def university_home():
        return render_template(
            "university.html",
            materials=university["materials"],
            plan=university["plan"],
            done=records().plan_done(g.user["id"]),
        )

    @app.post("/university/plan")
    def university_plan():
        item_id = request.form.get("item_id", "")
        if any(item["id"] == item_id for item in university["plan"]):
            records().toggle_plan(g.user["id"], item_id)
        return redirect(url_for("university_home"))

    @app.get("/clubs")
    def clubs():
        return render_template("clubs.html", clubs=records().clubs())

    @app.post("/clubs")
    def club_create():
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        if len(name) < 3 or len(description) < 10:
            flash("Give the club a name and a short description.")
            return redirect(url_for("clubs"))
        slug = records().create_club(g.user["id"], name, description)
        return redirect(url_for("club", slug=slug))

    @app.get("/clubs/<slug>")
    def club(slug):
        item = records().club(slug)
        if item is None:
            return redirect(url_for("clubs"))
        store = records()
        return render_template(
            "club.html",
            club=item,
            members=store.members(item["id"]),
            threads=store.threads(club_id=item["id"]),
            joined=g.user["id"] in store.member_ids(item["id"]),
        )

    @app.post("/clubs/<slug>/join")
    def club_join(slug):
        item = records().club(slug)
        if item:
            records().join_club(item["id"], g.user["id"])
        return redirect(url_for("club", slug=slug))

    @app.post("/clubs/<slug>/threads")
    def club_thread(slug):
        item = records().club(slug)
        if item is None or g.user["id"] not in records().member_ids(item["id"]):
            return redirect(url_for("clubs"))
        _post_thread(records(), "chess", item["id"])
        return redirect(url_for("club", slug=slug))

    @app.get("/discussions")
    def discussions():
        category = request.args.get("category", "")
        if category not in CATEGORIES:
            category = ""
        return render_template(
            "discussions.html",
            threads=records().threads(category or None),
            categories=CATEGORIES,
            category=category,
        )

    @app.post("/discussions")
    def discussion_new():
        category = request.form.get("category", "general")
        if category not in CATEGORIES:
            category = "general"
        thread_id = _post_thread(records(), category, None)
        if thread_id is None:
            return redirect(url_for("discussions"))
        return redirect(url_for("discussion", thread_id=thread_id))

    @app.get("/discussions/<int:thread_id>")
    def discussion(thread_id):
        item = records().thread(thread_id)
        if item is None or item["club_id"] is not None:
            return redirect(url_for("discussions"))
        return render_template("discussion.html", thread=item, comments=records().comments(thread_id))

    @app.post("/discussions/<int:thread_id>/comment")
    def discussion_comment(thread_id):
        body = request.form.get("body", "").strip()
        if records().thread(thread_id) and body:
            records().add_comment(thread_id, g.user["id"], body)
        return redirect(url_for("discussion", thread_id=thread_id))

    @app.post("/discussions/<int:thread_id>/like")
    def discussion_like(thread_id):
        if records().thread(thread_id):
            records().like(g.user["id"], thread_id)
        return redirect(url_for("discussion", thread_id=thread_id))

    @app.get("/competitions")
    def competitions():
        return render_template("competitions.html", weekly=records().weekly_results(), elo=records().leaderboard("chess_elo"))

    @app.get("/profile")
    def profile():
        store = records()
        user = database.get_user(g.user["id"])
        return render_template("profile.html", user=user, view=_profile_view(store, user), emblems=EMBLEMS, own=True)

    @app.post("/profile")
    def profile_save():
        error = records().update_profile(
            g.user["id"],
            request.form.get("username", ""),
            request.form.get("bio", ""),
            request.form.get("emblem", "seal"),
        )
        flash(error or "Profile saved.")
        return redirect(url_for("profile"))

    @app.get("/u/<username>")
    def public_profile(username):
        user = records().public_user(username)
        if user is None or not user["age_confirmed"]:
            flash("That profile is not available.")
            return redirect(url_for("home"))
        return render_template(
            "profile.html",
            user=user,
            view=_profile_view(records(), user),
            emblems=EMBLEMS,
            own=g.user is not None and user["id"] == g.user["id"],
        )


def _post_thread(store: Records, category: str, club_id: int | None):
    title = request.form.get("title", "").strip()
    body = request.form.get("body", "").strip()
    if len(title) < 3 or len(body) < 5:
        flash("A discussion needs a title and a message.")
        return None
    return store.add_thread(g.user["id"], title, body, category, club_id)


def _finish(store: Records, game, result: str, reason: str) -> None:
    store.save_game(
        game["code"],
        status="finished",
        result=result,
        reason=reason,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    _award_finish(store, store.game(game["code"]), result)


def _award_finish(store: Records, game, result: str) -> None:
    store.finish_ratings(game, result)
    store.add_xp(game["white_id"], 25)
    store.grant(game["white_id"], "first_game")
    if game["black_id"] and game["black_id"] != game["white_id"]:
        store.add_xp(game["black_id"], 25)
        store.grant(game["black_id"], "first_game")


def _can_see(game, user_id: int) -> bool:
    if game["mode"] == "link" and game["status"] == "waiting":
        return True
    return user_id in {game["white_id"], game["black_id"]}


def _names(database, game) -> dict[str, str]:
    white = database.get_user(game["white_id"])
    black = database.get_user(game["black_id"]) if game["black_id"] else None
    black_name = "Lucid" if game["mode"] == "ai" else "Black"
    if black and black["username"]:
        black_name = black["username"]
    return {"white": white["username"] or white["name"], "black": black_name}


def _profile_view(store: Records, user) -> dict:
    return {
        "level": level_for(user["xp"] or 0),
        "rank": rank_for(user["xp"] or 0),
        "achievements": [(row["code"], ACHIEVEMENTS[row["code"]]) for row in store.achievements(user["id"])],
        "games": store.games_for(user["id"], 8),
        "training": store.training_stats(user["id"]),
        "clubs": store.user_clubs(user["id"]),
        "lessons": len(store.finished_lessons(user["id"])),
    }


def _opening_view(board: chess.Board) -> list[dict]:
    from lucid.chessplay import board_view

    return board_view(board.fen(), white_at_bottom=True)
