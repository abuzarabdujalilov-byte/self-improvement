"""Server-checked cognitive drills. The answer stays in the session."""

from __future__ import annotations

import random

KINDS = ("memory", "focus", "observation", "arithmetic")


def make_round(kind: str, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    if kind == "memory":
        length = rng.randint(4, 7)
        digits = "".join(str(rng.randrange(10)) for _ in range(length))
        return {"kind": kind, "prompt": digits, "answer": digits}
    if kind == "focus":
        target = rng.randrange(16)
        return {"kind": kind, "answer": str(target), "size": 16}
    if kind == "observation":
        left = [rng.choice(("·", "○", "△")) for _ in range(8)]
        right = left.copy()
        index = rng.randrange(8)
        options = ["·", "○", "△", "□"]
        options.remove(left[index]) if left[index] in options else None
        right[index] = rng.choice([mark for mark in ("·", "○", "△", "□") if mark != left[index]])
        return {"kind": kind, "left": left, "right": right, "answer": str(index)}
    left = rng.randint(3, 12)
    choice = rng.choice(("multiply", "divide", "percent", "square"))
    if choice == "multiply":
        right = rng.randint(3, 12)
        return {"kind": kind, "prompt": f"{left} × {right}", "answer": str(left * right)}
    if choice == "divide":
        right = rng.randint(2, 9)
        return {"kind": kind, "prompt": f"{left * right} ÷ {right}", "answer": str(left)}
    if choice == "percent":
        percent = rng.choice((10, 20, 25, 50))
        base = rng.choice((40, 60, 80, 120, 200))
        return {"kind": kind, "prompt": f"{percent}% of {base}", "answer": str(base * percent // 100)}
    return {"kind": kind, "prompt": f"{left}²", "answer": str(left * left)}
