"""Lucid HTTP application."""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, session, url_for

from gemini_client.client import send_message as gemini_send_message
from gemini_client.models import ALLOWED_MODEL_IDS, DEFAULT_MODEL_ID, MODELS
from lucid import chessplay, progress
from lucid.crypto import decrypt, encrypt, fingerprint
from lucid.google_login import authorization_url, fetch_profile

ROOT = Path(__file__).resolve().parents[1]
KEY_PATTERN = re.compile(r"^[^\s]{20,512}$")
BASE_INSTRUCTION = (
    "You are the Lucid assistant for a student aged 16 or over who is practising thinking. "
    "Answer the question they actually ask. When the topic is an exercise, use the exercise "
    "details you are given and do not invent a different position or a different problem. "
    "The site marks clear-answer chess puzzles and short logic challenges. You explain; you do not award those marks. "
    "For a longer reasoning problem, help the student improve their own reasoning. "
    "There is no single official paragraph they must have written. "
    "You may also discuss science, philosophy, and any other subject they raise. "
    "If a puzzle is still unsolved, give a hint before the full answer unless they explicitly ask for the answer."
)


def create_app(
    *,
    database,
    secret_key: bytes,
    aes_key: bytes,
    puzzles: list[dict],
    logic_items: list[dict],
    send_message=gemini_send_message,
    google_client_id: str = "",
    google_client_secret: str = "",
    redirect_uri: str = "http://127.0.0.1:3000/auth/callback",
    dev_login: bool = False,
    fetch_google_profile=fetch_profile,
) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )
    app.config.update(
        SECRET_KEY=secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_NAME="lucid_session",
        MAX_CONTENT_LENGTH=32 * 1024,
        DATABASE=database,
        AES_KEY=aes_key,
        PUZZLES={puzzle["id"]: puzzle for puzzle in puzzles},
        PUZZLE_LIST=puzzles,
        LOGIC={item["id"]: item for item in logic_items},
        LOGIC_LIST=logic_items,
        SEND_MESSAGE=send_message,
        GOOGLE_CLIENT_ID=google_client_id,
        GOOGLE_CLIENT_SECRET=google_client_secret,
        REDIRECT_URI=redirect_uri,
        DEV_LOGIN=dev_login,
        FETCH_GOOGLE_PROFILE=fetch_google_profile,
    )

    @app.context_processor
    def inject_nav():
        from lucid.records import level_for, rank_for

        user = getattr(g, "user", None)
        progress_view = None
        if user is not None and user["age_confirmed"]:
            progress_view = {"level": level_for(user["xp"] or 0), "rank": rank_for(user["xp"] or 0)}
        recent = []
        if user is not None and getattr(g, "key", None):
            recent = database.messages(user["id"])[-8:]
        return {
            "models": MODELS,
            "default_model_id": DEFAULT_MODEL_ID,
            "progress_view": progress_view,
            "has_key": bool(getattr(g, "key", None)),
            "ai_messages": recent,
        }

    @app.before_request
    def load_user():
        if request.endpoint in {None, "static"}:
            return None
        user_id = session.get("user_id")
        g.user = database.get_user(user_id) if user_id else None
        g.key = _key_for(app, g.user["id"]) if g.user else None
        if g.user is not None and g.user["age_confirmed"]:
            from lucid.records import Records
            Records(database).ensure_username(g.user)
            Records(database).touch(g.user["id"])
            g.user = database.get_user(g.user["id"])
        open_endpoints = {"home", "login", "callback", "dev_login", "public_profile"}
        if request.endpoint in open_endpoints:
            return None
        if g.user is None:
            return redirect(url_for("home"))
        if request.endpoint not in {"age", "logout"} and not g.user["age_confirmed"]:
            return redirect(url_for("age"))
        ai_only = {"assistant", "assistant_send", "assistant_reset", "use_context"}
        if request.endpoint in ai_only and g.key is None:
            flash("AI Support is currently unavailable. Please configure your Gemini API key to unlock your personal AI assistant.")
            return redirect(url_for("account"))
        return None

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.path.startswith("/practice") or request.path.startswith("/assistant") or request.path.startswith("/account"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def home():
        return render_template(
            "home.html",
            google_ready=bool(google_client_id and google_client_secret),
            dev_login=dev_login,
            signed_in=g.user is not None,
        )

    @app.get("/login")
    def login():
        if not google_client_id or not google_client_secret:
            flash("Google sign-in is not configured on this server yet.")
            return redirect(url_for("home"))
        state = secrets.token_urlsafe(24)
        session["oauth_state"] = state
        return redirect(authorization_url(client_id=google_client_id, redirect_uri=redirect_uri, state=state))

    @app.get("/auth/callback")
    def callback():
        if request.args.get("state") != session.get("oauth_state"):
            flash("The Google sign-in session did not match. Try again.")
            return redirect(url_for("home"))
        code = request.args.get("code", "")
        if not code:
            flash("Google did not return a sign-in code.")
            return redirect(url_for("home"))
        try:
            profile = fetch_google_profile(
                client_id=google_client_id,
                client_secret=google_client_secret,
                redirect_uri=redirect_uri,
                code=code,
            )
        except Exception:
            flash("Google sign-in could not be completed. Try again.")
            return redirect(url_for("home"))
        user = _upsert_google_user(database, profile)
        session["user_id"] = user["id"]
        session.pop("oauth_state", None)
        return redirect(url_for("dashboard" if user["age_confirmed"] else "age"))

    @app.post("/dev-login")
    def dev_login():
        if not dev_login:
            return redirect(url_for("home"))
        user = database.get_user_by_sub("dev-local")
        if user is None:
            user = database.create_user("dev-local", "student@localhost", "Local student")
        session["user_id"] = user["id"]
        return redirect(url_for("dashboard" if user["age_confirmed"] else "age"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("home"))

    @app.route("/age", methods=["GET", "POST"])
    def age():
        if request.method == "POST":
            if request.form.get("confirm") == "yes":
                database.confirm_age(g.user["id"])
                return redirect(url_for("account"))
            flash("Lucid is for students aged 16 and over.")
        return render_template("age.html")

    @app.get("/dashboard")
    def dashboard():
        summary = _summary(app, g.user)
        return render_template("dashboard.html", summary=summary, key=g.key)

    @app.route("/account", methods=["GET", "POST"])
    def account():
        if request.method == "POST":
            api_key = request.form.get("api_key", "").strip()
            model_id = request.form.get("model_id", "").strip()
            if not model_id and g.key:
                model_id = g.key["model_id"]
            if not model_id:
                model_id = DEFAULT_MODEL_ID
            if model_id not in ALLOWED_MODEL_IDS:
                flash("Choose Gemini 3.8 Flash, 3.6 Flash, or 3.5 Flash-Lite.")
                return redirect(url_for("account"))
            if not KEY_PATTERN.fullmatch(api_key):
                flash("Paste the full API key from Google AI Studio, with no spaces.")
                return redirect(url_for("account"))
            if dev_login and api_key == "dev-key-dev-key-dev-key":
                result = {"text": "ready", "modelId": model_id}
            else:
                result = send_message(
                    api_key=api_key,
                    model_id=model_id,
                    messages=[{"role": "user", "text": "Reply with the single word ready."}],
                    system_instruction="Reply with the single word ready.",
                )
            if result.get("error"):
                flash(result["error"]["message"])
                return redirect(url_for("account"))
            nonce, ciphertext = encrypt(aes_key, api_key)
            database.save_key(g.user["id"], nonce, ciphertext, fingerprint(api_key), model_id)
            flash("Your key is saved for this account. Only the last four characters are shown.")
            return redirect(url_for("dashboard"))
        return render_template("account.html", key=g.key, selected=g.key["model_id"] if g.key else DEFAULT_MODEL_ID)

    @app.post("/account/model")
    def update_model():
        model_id = request.form.get("model_id", "").strip()
        if model_id not in ALLOWED_MODEL_IDS or g.key is None:
            flash("Choose one of the three Gemini models.")
            return redirect(url_for("account"))
        database.set_model(g.user["id"], model_id)
        flash("The next reply will use the model you selected.")
        return redirect(url_for("account"))

    @app.post("/account/key/delete")
    def delete_key():
        database.delete_key(g.user["id"])
        flash("The saved key has been removed.")
        return redirect(url_for("account"))

    @app.get("/practice/chess")
    def chess():
        puzzle, chess_session, view, message = _chess_state(app, g.user)
        return render_template(
            "chess.html",
            puzzle=puzzle,
            chess_session=chess_session,
            board=view,
            notice=message,
        )

    @app.post("/practice/chess/move")
    def chess_move():
        chess_session = database.get_chess_session(g.user["id"])
        puzzle = app.config["PUZZLES"].get(chess_session["puzzle_id"]) if chess_session else None
        if chess_session is None or puzzle is None or chess_session["status"] != "active":
            return redirect(url_for("chess"))
        outcome = chessplay.play_student_move(
            puzzle["fen"], puzzle["solution"], chess_session["ply"], request.form.get("uci", "")
        )
        if outcome["illegal"]:
            flash("That is not a legal move in this position. Try another square.")
            return redirect(url_for("chess"))
        if not outcome["correct"]:
            database.save_chess_session(g.user["id"], puzzle["id"], chess_session["ply"], "failed")
            target = progress.next_chess_target(g.user["chess_target"], False)
            database.set_chess_target(g.user["id"], target)
            database.add_attempt(g.user["id"], "chess", puzzle["id"], 0)
            expected = chessplay.san_of(puzzle["fen"], puzzle["solution"][: chess_session["ply"]], puzzle["solution"][chess_session["ply"]])
            flash(f"Not that move. One move that works here is {expected}.")
            return redirect(url_for("chess"))
        status = "solved" if outcome["done"] else "active"
        database.save_chess_session(g.user["id"], puzzle["id"], outcome["ply"], status)
        if status == "solved":
            target = progress.next_chess_target(g.user["chess_target"], True)
            database.set_chess_target(g.user["id"], target)
            database.add_attempt(g.user["id"], "chess", puzzle["id"], 1)
            from lucid.records import Records
            Records(database).add_xp(g.user["id"], 15)
            Records(database).grant(g.user["id"], "first_puzzle")
            flash("Solved. Your puzzle target moved up.")
        else:
            flash("Correct. Your opponent has replied.")
        return redirect(url_for("chess"))

    @app.post("/practice/chess/next")
    def chess_next():
        _start_chess(app, g.user)
        return redirect(url_for("chess"))

    @app.get("/practice/logic")
    def logic():
        item, logic_session = _logic_state(app, g.user)
        return render_template(
            "logic.html",
            item=item,
            logic_session=logic_session,
            reply=session.get("logic_reply", ""),
        )

    @app.post("/practice/logic/answer")
    def logic_answer():
        logic_session = database.get_logic_session(g.user["id"])
        item = app.config["LOGIC"].get(logic_session["item_id"]) if logic_session else None
        if logic_session is None or item is None or logic_session["status"] != "active":
            return redirect(url_for("logic"))
        answer = request.form.get("answer", "").strip()
        if not answer:
            flash("Write an answer before checking.")
            return redirect(url_for("logic"))
        if item["kind"] == "short":
            correct = progress.answer_matches(answer, item["answers"])
            database.save_logic_session(g.user["id"], item["id"], "solved" if correct else "failed")
            database.add_attempt(g.user["id"], "logic_short", item["id"], 1 if correct else 0, answer)
            flash("Correct." if correct else f"Not quite. One accepted answer is: {item['answers'][0]}")
            return redirect(url_for("logic"))
        key = _key_for(app, g.user["id"])
        if key is None:
            flash("Add your Gemini key before sending a longer problem to the assistant.")
            return redirect(url_for("account"))
        history = [{"role": "user", "text": f"Problem:\n{item['prompt']}\n\nMy reasoning:\n{answer}"}]
        result = send_message(
            api_key=key["api_key"],
            model_id=key["model_id"],
            messages=history,
            system_instruction=(
                f"{BASE_INSTRUCTION}\n\nCoaching notes for this problem, for you only: {item['coach_notes']}"
            ),
        )
        if result.get("error"):
            flash(result["error"]["message"])
            return redirect(url_for("logic"))
        database.save_logic_session(g.user["id"], item["id"], "complete")
        database.add_attempt(g.user["id"], "logic_long", item["id"], None, answer)
        database.add_message(g.user["id"], "user", answer)
        database.add_message(g.user["id"], "model", result["text"])
        database.set_context(
            g.user["id"],
            f"The student just answered a longer logic problem ({item['id']}). Problem: {item['prompt']} Their reasoning: {answer}",
        )
        flash("Your reasoning was sent to the assistant. It does not change your logic percentage.")
        session["logic_reply"] = result["text"]
        return redirect(url_for("logic"))

    @app.post("/practice/logic/next")
    def logic_next():
        _start_logic(app, g.user)
        session.pop("logic_reply", None)
        return redirect(url_for("logic"))

    @app.get("/assistant")
    def assistant():
        return render_template(
            "assistant.html",
            messages=database.messages(g.user["id"]),
            context=database.get_context(g.user["id"]),
            key=g.key,
            draft=session.get("draft", ""),
        )

    @app.post("/assistant")
    def assistant_send():
        text = request.form.get("text", "").strip()
        if not text:
            flash("Write a message before sending.")
            return redirect(url_for("assistant"))
        if len(text) > 8000:
            flash("Messages are limited to 8000 characters.")
            return redirect(url_for("assistant"))
        key = _key_for(app, g.user["id"])
        prior = database.messages(g.user["id"])[-39:]
        messages = [{"role": row["role"], "text": row["text"]} for row in prior]
        messages.append({"role": "user", "text": text})
        context = database.get_context(g.user["id"])
        instruction = BASE_INSTRUCTION if not context else f"{BASE_INSTRUCTION}\n\nExercise context:\n{context}"
        place = request.form.get("place", "").strip()[:80]
        if place:
            instruction += f"\n\nThe student is currently looking at: {place}"
        result = send_message(
            api_key=key["api_key"],
            model_id=key["model_id"],
            messages=messages,
            system_instruction=instruction,
        )
        if result.get("error"):
            flash(result["error"]["message"])
            session["draft"] = text
            return redirect(_safe_next())
        database.add_message(g.user["id"], "user", text)
        database.add_message(g.user["id"], "model", result["text"])
        session.pop("draft", None)
        return redirect(_safe_next())

    @app.post("/assistant/reset")
    def assistant_reset():
        database.clear_messages(g.user["id"])
        return redirect(url_for("assistant"))

    @app.post("/assistant/context")
    def use_context():
        kind = request.form.get("kind", "")
        item_id = request.form.get("item_id", "")
        text = _context_text(app, g.user["id"], kind, item_id)
        if not text:
            flash("That exercise is not available.")
            return redirect(url_for("assistant"))
        database.set_context(g.user["id"], text)
        flash("The assistant can see the exercise you were working on.")
        return redirect(url_for("assistant"))

    from lucid.platform_routes import register

    register(app)
    return app


def _upsert_google_user(database, profile: dict):
    user = database.get_user_by_sub(profile["id"])
    if user:
        return user
    return database.create_user(profile["id"], profile.get("email") or "", profile.get("name") or "Student")


def _key_for(app: Flask, user_id: int) -> dict | None:
    row = app.config["DATABASE"].get_key_row(user_id)
    if row is None:
        return None
    try:
        api_key = decrypt(app.config["AES_KEY"], row["nonce"], row["ciphertext"])
    except Exception:
        return None
    return {"api_key": api_key, "fingerprint": row["fingerprint"], "model_id": row["model_id"]}


def _summary(app: Flask, user) -> dict:
    database = app.config["DATABASE"]
    chess_rows = database.attempts(user["id"], "chess")
    short_rows = database.attempts(user["id"], "logic_short")
    flags = [bool(row["correct"]) for row in short_rows]
    chess_session = database.get_chess_session(user["id"])
    logic_session = database.get_logic_session(user["id"])
    next_puzzle = None
    if chess_session and chess_session["status"] == "active":
        next_puzzle = app.config["PUZZLES"].get(chess_session["puzzle_id"])
    else:
        next_puzzle = progress.pick_puzzle(
            app.config["PUZZLE_LIST"],
            user["chess_target"],
            database.recent_item_ids(user["id"], "chess"),
        )
    recent_logic = database.recent_item_ids(user["id"], "logic_short") | database.recent_item_ids(user["id"], "logic_long")
    if logic_session and logic_session["status"] == "active":
        next_logic = app.config["LOGIC"].get(logic_session["item_id"])
    else:
        next_logic = progress.pick_logic_item(
            app.config["LOGIC_LIST"],
            recent_logic,
            flags,
            len(short_rows) + len(database.attempts(user["id"], "logic_long")),
        )
    return {
        "chess_score": user["chess_target"],
        "logic_score": progress.logic_accuracy(flags),
        "chess_done": len(chess_rows),
        "logic_done": len(short_rows),
        "next_puzzle": next_puzzle,
        "next_logic": next_logic,
        "chess_active": bool(chess_session and chess_session["status"] == "active"),
        "logic_active": bool(logic_session and logic_session["status"] == "active"),
    }


def _start_chess(app: Flask, user) -> None:
    database = app.config["DATABASE"]
    puzzle = progress.pick_puzzle(
        app.config["PUZZLE_LIST"],
        user["chess_target"],
        database.recent_item_ids(user["id"], "chess"),
    )
    if puzzle is None:
        database.clear_chess_session(user["id"])
        return
    database.save_chess_session(user["id"], puzzle["id"], 0, "active")


def _chess_state(app: Flask, user):
    database = app.config["DATABASE"]
    chess_session = database.get_chess_session(user["id"])
    if chess_session is None:
        _start_chess(app, user)
        chess_session = database.get_chess_session(user["id"])
    if chess_session is None:
        return None, None, None, "The chess puzzle bank is empty."
    puzzle = app.config["PUZZLES"].get(chess_session["puzzle_id"])
    if puzzle is None:
        return None, chess_session, None, "That puzzle is no longer in the bank."
    fen = chessplay.position_after(puzzle["fen"], puzzle["solution"][: chess_session["ply"]])
    return puzzle, chess_session, chessplay.board_view(fen), None


def _start_logic(app: Flask, user) -> None:
    database = app.config["DATABASE"]
    short_rows = database.attempts(user["id"], "logic_short")
    flags = [bool(row["correct"]) for row in short_rows]
    recent = database.recent_item_ids(user["id"], "logic_short") | database.recent_item_ids(user["id"], "logic_long")
    item = progress.pick_logic_item(
        app.config["LOGIC_LIST"],
        recent,
        flags,
        len(short_rows) + len(database.attempts(user["id"], "logic_long")),
    )
    if item:
        database.save_logic_session(user["id"], item["id"], "active")


def _logic_state(app: Flask, user):
    database = app.config["DATABASE"]
    logic_session = database.get_logic_session(user["id"])
    if logic_session is None or logic_session["status"] != "active":
        if logic_session is None:
            _start_logic(app, user)
            logic_session = database.get_logic_session(user["id"])
    if logic_session is None:
        return None, None
    return app.config["LOGIC"].get(logic_session["item_id"]), logic_session


def _safe_next() -> str:
    next_url = request.form.get("next", "")
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return url_for("assistant")


def _context_text(app: Flask, user_id: int, kind: str, item_id: str) -> str:
    if kind == "chess":
        puzzle = app.config["PUZZLES"].get(item_id)
        chess_session = app.config["DATABASE"].get_chess_session(user_id)
        if puzzle is None:
            return ""
        status = chess_session["status"] if chess_session and chess_session["puzzle_id"] == item_id else "unknown"
        if status == "active":
            return (
                f"Unsolved Lichess puzzle {puzzle['id']}. Themes: {', '.join(puzzle['themes'])}. "
                f"Current FEN: {chessplay.position_after(puzzle['fen'], puzzle['solution'][: chess_session['ply']])}. "
                "The puzzle is not finished. Hint before giving the full line unless the student asks for the answer."
            )
        return (
            f"Finished Lichess puzzle {puzzle['id']} with result {status}. "
            f"Start FEN: {puzzle['fen']}. Solution: {' '.join(puzzle['solution'])}."
        )
    item = app.config["LOGIC"].get(item_id)
    if item is None:
        return ""
    if item["kind"] == "short":
        return f"Short logic challenge {item['id']}. Prompt: {item['prompt']} Accepted answer: {item['answers'][0]}."
    return f"Longer logic problem {item['id']}. Prompt: {item['prompt']}"


def build_production_app() -> Flask:
    from lucid.content_loader import load_logic, load_puzzles
    from lucid.crypto import derive, load_master_secret
    from lucid.db import Database

    data_dir = ROOT / "data"
    master = load_master_secret(data_dir / "lucid.secret")
    return create_app(
        database=Database(data_dir / "lucid.db"),
        secret_key=derive(master, b"lucid-cookie"),
        aes_key=derive(master, b"lucid-vault"),
        puzzles=load_puzzles(),
        logic_items=load_logic(),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
        redirect_uri=os.environ.get("GOOGLE_REDIRECT_URI", "http://127.0.0.1:3000/auth/callback").strip(),
        dev_login=os.environ.get("LUCID_DEV_LOGIN", "").strip() == "1",
    )
