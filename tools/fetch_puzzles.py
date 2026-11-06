"""Download a reusable sample of Lichess puzzles and keep only legal solutions.

The Lichess puzzle database is CC0. This script stores a small local bank so
practice does not call Lichess during a student's session.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "lucid" / "content" / "puzzles.json"
TARGET = 48


def fetch_one() -> dict:
    request = urllib.request.Request(
        "https://lichess.org/api/puzzle/next",
        headers={
            "Accept": "application/json",
            "User-Agent": "Lucid/0.1 (educational practice; local puzzle bank)",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def legal(fen: str, solution: list[str]) -> bool:
    board = chess.Board(fen)
    if not solution:
        return False
    for uci in solution:
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return False
        if move not in board.legal_moves:
            return False
        board.push(move)
    return True


def main() -> None:
    puzzles = []
    seen = set()
    attempts = 0
    while len(puzzles) < TARGET and attempts < TARGET * 4:
        attempts += 1
        try:
            payload = fetch_one()
        except Exception as error:
            print(f"skip request: {error}")
            time.sleep(1)
            continue
        puzzle = payload.get("puzzle") or {}
        puzzle_id = puzzle.get("id")
        fen = puzzle.get("fen")
        solution = puzzle.get("solution") or []
        if not puzzle_id or puzzle_id in seen or not fen or not legal(fen, solution):
            time.sleep(0.3)
            continue
        seen.add(puzzle_id)
        puzzles.append(
            {
                "id": puzzle_id,
                "rating": int(puzzle.get("rating") or 0),
                "fen": fen,
                "solution": solution,
                "themes": puzzle.get("themes") or [],
            }
        )
        print(f"{len(puzzles):02d} {puzzle_id} {puzzle.get('rating')}")
        time.sleep(0.35)
    puzzles.sort(key=lambda item: item["rating"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "source": "Lichess puzzle database",
                "url": "https://lichess.org",
                "license": "CC0",
                "puzzles": puzzles,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(puzzles)} puzzles to {OUT}")


if __name__ == "__main__":
    main()
