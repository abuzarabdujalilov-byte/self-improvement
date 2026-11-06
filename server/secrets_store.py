"""Server secret used only to encrypt vault data and sign the session cookie.

This is not a Gemini API key. End users never share one.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def load_master_secret(path: Path) -> bytes:
    configured = os.environ.get("SERVER_SECRET", "").strip()
    if configured:
        try:
            secret = base64.urlsafe_b64decode(configured.encode("ascii"))
        except Exception as error:
            raise RuntimeError("SERVER_SECRET must be URL-safe base64.") from error
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
