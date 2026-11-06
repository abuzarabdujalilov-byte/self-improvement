"""Stateless Gemini generateContent client.

The caller supplies the API key for a single request. This module does not
read GEMINI_API_KEY, does not store keys, and does not know about HTML.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

from gemini_client.models import ALLOWED_MODEL_IDS

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
Opener = Callable[..., object]


def send_message(
    *,
    api_key: str,
    model_id: str,
    messages: list[dict],
    system_instruction: str | None = None,
    opener: Opener | None = None,
    timeout: float = 60,
) -> dict:
    """Send one multi-turn chat request.

    Returns {"text", "modelId"} or {"modelId", "error": {"code", "message"}}.
    """
    model_id = (model_id or "").strip()
    if model_id not in ALLOWED_MODEL_IDS:
        return _failure(model_id, "model_unavailable", "That Gemini model is not available in this app.")

    key = (api_key or "").strip()
    if not key:
        return _failure(model_id, "invalid_key", "Add your Google AI Studio API key to start the conversation.")

    contents = []
    for message in messages:
        role = message.get("role")
        text = (message.get("text") or "").strip()
        if role not in {"user", "model"} or not text:
            return _failure(model_id, "unknown", "The conversation sent to Gemini was incomplete.")
        contents.append({"role": role, "parts": [{"text": text}]})
    if not contents:
        return _failure(model_id, "unknown", "There is no message to send.")

    body: dict = {"contents": contents}
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    url = f"{API_ROOT}/{model_id}:generateContent"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        },
        method="POST",
    )
    open_request = opener or urllib.request.urlopen
    try:
        with open_request(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        try:
            detail = _read_error(error)
            return _failure(model_id, *_map_http_error(error.code, detail, key))
        finally:
            error.close()
    except (urllib.error.URLError, TimeoutError, OSError):
        return _failure(
            model_id,
            "network",
            "The connection to Gemini failed. Check your network and try again.",
        )

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _failure(model_id, "unknown", "Gemini returned a response this app could not read.")

    blocked = _blocked_message(payload)
    if blocked:
        return _failure(model_id, "blocked", blocked)

    text = _visible_text(payload)
    if not text:
        return _failure(model_id, "unknown", "Gemini returned an empty reply. Try again.")
    return {"text": text, "modelId": model_id}


def _failure(model_id: str, code: str, message: str) -> dict:
    return {"modelId": model_id, "error": {"code": code, "message": message}}


def _read_error(error: urllib.error.HTTPError) -> dict:
    try:
        raw = error.read().decode("utf-8", errors="replace")
    except Exception:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": {"message": raw[:500]}}
    return parsed if isinstance(parsed, dict) else {}


def _map_http_error(status: int, payload: dict, api_key: str) -> tuple[str, str]:
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    message = str(error.get("message") or "")
    google_status = str(error.get("status") or "")
    lowered = f"{message} {google_status}".lower()

    if status in {401, 403} or "api key" in lowered or "api_key" in lowered:
        return "invalid_key", "That API key was rejected. Check it in Google AI Studio and paste it again."
    if status == 429 or "resource_exhausted" in lowered or "quota" in lowered:
        return (
            "quota",
            "This key has reached its current Gemini quota. Wait, or turn on billing for that Google project.",
        )
    model_missing = status == 404 or any(
        phrase in lowered
        for phrase in ("not found", "not supported", "unknown model", "invalid model", "is not available")
    )
    if model_missing and "api key" not in lowered:
        return (
            "model_unavailable",
            "Gemini does not currently offer that model for this key. Choose another model and try again.",
        )
    safe = _redact(message, api_key) or "Gemini could not complete that request."
    if status >= 500:
        return "network", "Gemini is unavailable right now. Try again in a moment."
    return "unknown", safe


def _blocked_message(payload: dict) -> str | None:
    feedback = payload.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        return "Gemini declined that message. Rephrase it and try again."
    candidates = payload.get("candidates") or []
    if candidates and isinstance(candidates[0], dict):
        reason = candidates[0].get("finishReason")
        if reason in {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
            return "Gemini declined that message. Rephrase it and try again."
    return None


def _visible_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    chunks = []
    for part in parts:
        if not isinstance(part, dict) or part.get("thought"):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return "\n\n".join(chunks).strip()


def _redact(message: str, api_key: str) -> str:
    if api_key:
        message = message.replace(api_key, "[redacted]")
    return " ".join(message.split())
