"""Reusable Gemini client. No user interface and no shared API key."""

from gemini_client.client import send_message
from gemini_client.models import ALLOWED_MODEL_IDS, DEFAULT_MODEL_ID, MODELS, VERIFIED_ON

__all__ = [
    "ALLOWED_MODEL_IDS",
    "DEFAULT_MODEL_ID",
    "MODELS",
    "VERIFIED_ON",
    "send_message",
]
