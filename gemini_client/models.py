"""Selectable Gemini text models.

Checked against Google's Gemini API models, deprecations, and pricing pages
on 6 November 2026. `gemini-3.5-flash` is deprecated and is intentionally absent:
Google routes that ID to `gemini-3.6-flash`.
"""

VERIFIED_ON = "6 November 2026"

MODELS = [
    {
        "id": "gemini-3.8-flash",
        "label": "Gemini 3.8 Flash",
        "tag": "Highest quality",
        "blurb": "Best when the question is long or needs careful reasoning.",
        "price": "Input $0.75 and output $3.75 per 1M tokens through 31 December 2026, then $1.50 and $7.50.",
    },
    {
        "id": "gemini-3.6-flash",
        "label": "Gemini 3.6 Flash",
        "tag": "Default",
        "blurb": "The everyday balance of speed and quality.",
        "price": "Same introductory Standard price as Gemini 3.8 Flash through 31 December 2026.",
    },
    {
        "id": "gemini-3.5-flash-lite",
        "label": "Gemini 3.5 Flash-Lite",
        "tag": "Faster, lower cost",
        "blurb": "The selectable Gemini 3.5 text model. Suited to short questions and high volume.",
        "price": "Input $0.30 and output $2.50 per 1M tokens.",
    },
]

DEFAULT_MODEL_ID = "gemini-3.6-flash"
ALLOWED_MODEL_IDS = frozenset(model["id"] for model in MODELS)
