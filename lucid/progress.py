"""Rules for scores and for choosing the next exercise. No network and no UI."""

from __future__ import annotations

CHESS_STEP = 50
CHESS_FLOOR = 600
CHESS_CEILING = 2400
LOGIC_WINDOW = 20


def next_chess_target(current: int, correct: bool) -> int:
    if correct:
        return min(CHESS_CEILING, current + CHESS_STEP)
    return max(CHESS_FLOOR, current - CHESS_STEP)


def pick_puzzle(puzzles: list[dict], target: int, recent_ids: set[str]) -> dict | None:
    if not puzzles:
        return None
    fresh = [puzzle for puzzle in puzzles if puzzle["id"] not in recent_ids]
    pool = fresh or puzzles
    return min(pool, key=lambda puzzle: (abs(puzzle["rating"] - target), puzzle["id"]))


def logic_accuracy(correct_flags: list[bool]) -> int | None:
    recent = correct_flags[-LOGIC_WINDOW:]
    if not recent:
        return None
    return round(100 * sum(1 for flag in recent if flag) / len(recent))


def logic_band(accuracy: int | None) -> int:
    if accuracy is None or accuracy < 50:
        return 1
    if accuracy < 80:
        return 2
    return 3


def pick_logic_item(items: list[dict], recent_ids: set[str], short_results: list[bool], completed_count: int) -> dict | None:
    if not items:
        return None
    want_long = completed_count > 0 and completed_count % 3 == 0
    if want_long:
        chosen = _unused(items, recent_ids, kind="long")
        if chosen:
            return chosen
    band = logic_band(logic_accuracy(short_results))
    chosen = _unused(items, recent_ids, kind="short", difficulty=band)
    if chosen:
        return chosen
    return _unused(items, recent_ids, kind="short") or _unused(items, set(), kind="short")


def normalise_answer(value: str) -> str:
    return " ".join(value.strip().lower().replace("£", "").replace("%", "").split())


def answer_matches(given: str, accepted: list[str]) -> bool:
    cleaned = normalise_answer(given).rstrip(".")
    return any(cleaned == normalise_answer(option).rstrip(".") for option in accepted)


def _unused(items: list[dict], recent_ids: set[str], kind: str, difficulty: int | None = None) -> dict | None:
    pool = [
        item
        for item in items
        if item["kind"] == kind and item["id"] not in recent_ids and (difficulty is None or item.get("difficulty") == difficulty)
    ]
    if not pool and difficulty is not None:
        return None
    if not pool:
        pool = [item for item in items if item["kind"] == kind and (difficulty is None or item.get("difficulty") == difficulty)]
    if not pool:
        return None
    return sorted(pool, key=lambda item: item["id"])[0]
