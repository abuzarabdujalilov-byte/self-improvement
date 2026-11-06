"""Product HTTP API and pages. Gemini HTTP details stay in gemini_client."""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session

from gemini_client.client import send_message as gemini_send_message
from gemini_client.models import ALLOWED_MODEL_IDS, DEFAULT_MODEL_ID, MODELS, VERIFIED_ON
from server.vault import Record, Vault, fingerprint

ROOT = Path(__file__).resolve().parents[1]
MAX_MESSAGE_CHARS = 8000
MAX_STORED_MESSAGES = 200
HISTORY_SENT = 40
KEY_PATTERN = re.compile(r"^[^\s]{20,512}$")

SYSTEM_INSTRUCTION = (
    "You are AI Support Agent on a website about self-improvement, study, and university in Britain. "
    "Help the person with whatever they ask. When the topic is study or university, prefer clear, "
    "practical guidance relevant to Britain (for example UCAS-style applications, personal statements, "
    "student life, and revision habits) and say when a rule depends on the university or the current "
    "official guidance. For any other topic, answer directly. Ask a short follow-up when a better "
    "answer depends on it."
)


def create_app(
    *,
    secret_key: bytes,
    vault: Vault,
    send_message=gemini_send_message,
    system_instruction: str = SYSTEM_INSTRUCTION,
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
        SESSION_COOKIE_NAME="asa_session",
        MAX_CONTENT_LENGTH=32 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    app.config["VAULT"] = vault
    app.config["SEND_MESSAGE"] = send_message
    app.config["SYSTEM_INSTRUCTION"] = system_instruction
    app.config["RATE_BUCKETS"] = defaultdict(deque)

    @app.after_request
    def secure_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def home():
        return render_template(
            "index.html",
            models=MODELS,
            default_model_id=DEFAULT_MODEL_ID,
            verified_on=VERIFIED_ON,
        )

    @app.get("/chat")
    def chat_page():
        return render_template("chat.html", verified_on=VERIFIED_ON)

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/api/models")
    def models():
        return jsonify({"defaultModelId": DEFAULT_MODEL_ID, "verifiedOn": VERIFIED_ON, "models": MODELS})

    @app.get("/api/session")
    def get_session():
        record = vault.get(_user_id())
        return jsonify(_public_session(record))

    @app.post("/api/key")
    def save_key():
        _user_id()
        if not _allow(app, "key", limit=8, window_seconds=600):
            return _error("rate_limited", "Too many key checks. Wait a few minutes and try again.", 429)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("invalid_request", "The key form could not be read.", 400)

        api_key = str(payload.get("apiKey") or "").strip()
        model_id = str(payload.get("modelId") or DEFAULT_MODEL_ID).strip()
        remember = bool(payload.get("remember"))
        if not KEY_PATTERN.fullmatch(api_key):
            return _error(
                "invalid_key",
                "Paste the full API key from Google AI Studio, with no spaces.",
                400,
            )
        if model_id not in ALLOWED_MODEL_IDS:
            return _error("model_unavailable", "Choose Gemini 3.8 Flash, 3.6 Flash, or 3.5 Flash-Lite.", 400)

        result = app.config["SEND_MESSAGE"](
            api_key=api_key,
            model_id=model_id,
            messages=[{"role": "user", "text": "Reply with the single word ready."}],
            system_instruction="Reply with the single word ready.",
        )
        if result.get("error"):
            return _error(result["error"]["code"], result["error"]["message"], _status_for(result["error"]["code"]))

        user_id = _user_id()
        existing = vault.get(user_id)
        record = Record(
            api_key=api_key,
            model_id=model_id,
            remember=remember,
            fingerprint=fingerprint(api_key),
            messages=existing.messages if existing else [],
        )
        vault.save(user_id, record)
        session.permanent = remember
        session.modified = True
        body = _public_session(record)
        body["ok"] = True
        return jsonify(body)

    @app.delete("/api/key")
    def delete_key():
        user_id = session.get("user_id")
        if user_id:
            vault.delete(user_id)
        return jsonify(_public_session(None))

    @app.patch("/api/model")
    def update_model():
        payload = request.get_json(silent=True) or {}
        model_id = str(payload.get("modelId") or "").strip()
        if model_id not in ALLOWED_MODEL_IDS:
            return _error("model_unavailable", "Choose Gemini 3.8 Flash, 3.6 Flash, or 3.5 Flash-Lite.", 400)
        record = vault.get(_user_id())
        if record is None:
            return jsonify({"ok": True, "modelId": model_id, "hasKey": False})
        record.model_id = model_id
        vault.save(_user_id(), record)
        return jsonify(_public_session(record))

    @app.post("/api/chat/reset")
    def reset_chat():
        record = vault.get(_user_id())
        if record is None:
            return jsonify(_public_session(None))
        record.messages = []
        vault.save(_user_id(), record)
        return jsonify(_public_session(record))

    @app.post("/api/chat")
    def chat():
        _user_id()
        if not _allow(app, "chat", limit=20, window_seconds=60):
            return _error("rate_limited", "Too many messages were sent in a short time. Wait a moment and try again.", 429)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("invalid_request", "That message could not be read.", 400)
        text = str(payload.get("text") or "").strip()
        if not text:
            return _error("invalid_request", "Write a message before sending.", 400)
        if len(text) > MAX_MESSAGE_CHARS:
            return _error("invalid_request", f"Messages are limited to {MAX_MESSAGE_CHARS} characters.", 400)

        record = vault.get(_user_id())
        if record is None or not record.api_key:
            return _error("invalid_key", "Add your Google AI Studio API key before sending a message.", 400)
        if record.model_id not in ALLOWED_MODEL_IDS:
            return _error("model_unavailable", "Choose a supported Gemini model and try again.", 400)

        history = list(record.messages) + [{"role": "user", "text": text}]
        sent = history[-HISTORY_SENT:]
        result = app.config["SEND_MESSAGE"](
            api_key=record.api_key,
            model_id=record.model_id,
            messages=[{"role": item["role"], "text": item["text"]} for item in sent],
            system_instruction=app.config["SYSTEM_INSTRUCTION"],
        )
        if result.get("error"):
            return _error(result["error"]["code"], result["error"]["message"], _status_for(result["error"]["code"]))

        record.messages = history + [{"role": "model", "text": result["text"], "modelId": result["modelId"]}]
        if len(record.messages) > MAX_STORED_MESSAGES:
            record.messages = record.messages[-MAX_STORED_MESSAGES:]
        vault.save(_user_id(), record)
        body = _public_session(record)
        body["reply"] = result["text"]
        body["historyTruncated"] = len(history) > HISTORY_SENT
        return jsonify(body)

    return app


def _user_id() -> str:
    user_id = session.get("user_id")
    if not user_id:
        import secrets

        user_id = secrets.token_urlsafe(24)
        session["user_id"] = user_id
    return user_id


def _public_session(record: Record | None) -> dict:
    if record is None:
        return {
            "hasKey": False,
            "fingerprint": None,
            "modelId": DEFAULT_MODEL_ID,
            "remember": False,
            "messages": [],
        }
    safe_messages = []
    for message in record.messages:
        item = {"role": message.get("role"), "text": message.get("text", "")}
        if message.get("modelId"):
            item["modelId"] = message["modelId"]
        safe_messages.append(item)
    return {
        "hasKey": True,
        "fingerprint": record.fingerprint,
        "modelId": record.model_id,
        "remember": record.remember,
        "messages": safe_messages,
    }


def _error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _status_for(code: str) -> int:
    return {
        "invalid_key": 400,
        "quota": 429,
        "model_unavailable": 400,
        "blocked": 422,
        "network": 502,
        "rate_limited": 429,
    }.get(code, 502)


def _allow(app: Flask, bucket: str, *, limit: int, window_seconds: int) -> bool:
    user_id = session.get("user_id") or request.remote_addr or "anonymous"
    key = f"{bucket}:{user_id}"
    now = time.monotonic()
    stamps: deque = app.config["RATE_BUCKETS"][key]
    while stamps and now - stamps[0] > window_seconds:
        stamps.popleft()
    if len(stamps) >= limit:
        return False
    stamps.append(now)
    return True


def build_production_app() -> Flask:
    from server.secrets_store import derive, load_master_secret

    data_dir = ROOT / "data"
    master = load_master_secret(data_dir / "server.secret")
    vault = Vault(derive(master, b"ai-support-agent-vault"), data_dir / "vault.json")
    return create_app(secret_key=derive(master, b"ai-support-agent-cookie"), vault=vault)
