"""Encrypted per-user storage for API keys and chat history.

Session-only records stay in memory. Remembered records are AES-256-GCM
ciphertext on disk. The plaintext key is never written to the vault file.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass
class Record:
    api_key: str
    model_id: str
    remember: bool
    fingerprint: str
    messages: list[dict] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)


class Vault:
    def __init__(self, aes_key: bytes, path: Path):
        if len(aes_key) != 32:
            raise ValueError("The vault key must be 32 bytes.")
        self._aes_key = aes_key
        self._path = path
        self._lock = threading.Lock()
        self._records: dict[str, Record] = {}
        self._load()

    def get(self, user_id: str) -> Record | None:
        with self._lock:
            self._expire_session_records()
            record = self._records.get(user_id)
            return _copy(record) if record else None

    def save(self, record_id: str, record: Record) -> None:
        with self._lock:
            record.updated_at = time.time()
            self._records[record_id] = _copy(record)
            self._persist()

    def delete(self, user_id: str) -> None:
        with self._lock:
            self._records.pop(user_id, None)
            self._persist()

    def _expire_session_records(self) -> None:
        cutoff = time.time() - 12 * 60 * 60
        expired = [
            user_id
            for user_id, record in self._records.items()
            if not record.remember and record.updated_at < cutoff
        ]
        if not expired:
            return
        for user_id in expired:
            del self._records[user_id]

    def _persist(self) -> None:
        stored = {}
        for user_id, record in self._records.items():
            if not record.remember:
                continue
            stored[user_id] = {
                "fingerprint": record.fingerprint,
                "modelId": record.model_id,
                "blob": _encrypt(
                    self._aes_key,
                    json.dumps({"apiKey": record.api_key, "messages": record.messages}),
                ),
            }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({"version": 1, "users": stored}, indent=2), encoding="utf-8")
        temporary.replace(self._path)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        users = payload.get("users") if isinstance(payload, dict) else None
        if not isinstance(users, dict):
            return
        for user_id, entry in users.items():
            if not isinstance(entry, dict):
                continue
            try:
                decoded = json.loads(_decrypt(self._aes_key, entry["blob"]))
            except Exception:
                continue
            api_key = decoded.get("apiKey")
            if not isinstance(api_key, str) or not api_key:
                continue
            messages = decoded.get("messages")
            self._records[user_id] = Record(
                api_key=api_key,
                model_id=str(entry.get("modelId") or ""),
                remember=True,
                fingerprint=str(entry.get("fingerprint") or fingerprint(api_key)),
                messages=messages if isinstance(messages, list) else [],
            )


def fingerprint(api_key: str) -> str:
    trimmed = api_key.strip()
    return trimmed[-4:] if len(trimmed) >= 4 else trimmed


def _copy(record: Record) -> Record:
    return Record(
        api_key=record.api_key,
        model_id=record.model_id,
        remember=record.remember,
        fingerprint=record.fingerprint,
        messages=[dict(message) for message in record.messages],
        updated_at=record.updated_at,
    )


def _encrypt(key: bytes, plaintext: str) -> dict:
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return {"nonce": _b64(nonce), "ct": _b64(ciphertext)}


def _decrypt(key: bytes, blob: dict) -> str:
    nonce = _unb64(blob["nonce"])
    ciphertext = _unb64(blob["ct"])
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")


def _b64(value: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    import base64

    return base64.urlsafe_b64decode(value.encode("ascii"))
