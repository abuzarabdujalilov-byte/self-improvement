"""Encrypt a student's Gemini key. This module never chooses a shared key."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def load_master_secret(path: Path) -> bytes:
    configured = os.environ.get("SERVER_SECRET", "").strip()
    if configured:
        secret = base64.urlsafe_b64decode(configured.encode("ascii"))
        if len(secret) < 32:
            raise RuntimeError("SERVER_SECRET must decode to at least 32 bytes.")
        return secret[:32]
    if path.exists():
        secret = base64.urlsafe_b64decode(path.read_text(encoding="ascii").strip().encode("ascii"))
        if len(secret) >= 32:
            return secret[:32]
    path.parent.mkdir(parents=True, exist_ok=True)
    secret = os.urandom(32)
    path.write_text(base64.urlsafe_b64encode(secret).decode("ascii"), encoding="ascii")
    return secret


def derive(master: bytes, purpose: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=purpose).derive(master)


def encrypt(key: bytes, plaintext: str) -> tuple[str, str]:
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return _b64(nonce), _b64(ciphertext)


def decrypt(key: bytes, nonce: str, ciphertext: str) -> str:
    return AESGCM(key).decrypt(_unb64(nonce), _unb64(ciphertext), None).decode("utf-8")


def fingerprint(api_key: str) -> str:
    trimmed = api_key.strip()
    return trimmed[-4:] if len(trimmed) >= 4 else trimmed


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))
