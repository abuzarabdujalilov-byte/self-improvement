"""Load the exercise banks shipped with Lucid."""

from __future__ import annotations

import json
from pathlib import Path

import chess

CONTENT = Path(__file__).resolve().parent / "content"


def load_puzzles(path: Path | None = None) -> list[dict]:
    file_path = path or CONTENT / "puzzles.json"
    if not file_path.exists():
        return []
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    puzzles = []
    for puzzle in payload.get("puzzles", []):
        if _legal(puzzle.get("fen", ""), puzzle.get("solution") or []):
            puzzles.append(
                {
                    "id": puzzle["id"],
                    "rating": int(puzzle["rating"]),
                    "fen": puzzle["fen"],
                    "solution": puzzle["solution"],
                    "themes": puzzle.get("themes") or [],
                }
            )
    return puzzles


def load_logic(path: Path | None = None) -> list[dict]:
    file_path = path or CONTENT / "logic.json"
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    return payload["items"]


def _legal(fen: str, solution: list[str]) -> bool:
    if not fen or not solution:
        return False
    try:
        board = chess.Board(fen)
        for uci in solution:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                return False
            board.push(move)
    except ValueError:
        return False
    return True
