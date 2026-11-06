"""Check chess puzzle moves with the rules of chess. The model is not involved."""

from __future__ import annotations

import chess

GLYPHS = {
    "K": "♔",
    "Q": "♕",
    "R": "♖",
    "B": "♗",
    "N": "♘",
    "P": "♙",
    "k": "♚",
    "q": "♛",
    "r": "♜",
    "b": "♝",
    "n": "♞",
    "p": "♟",
}

PIECE_NAMES = {
    "K": "white king",
    "Q": "white queen",
    "R": "white rook",
    "B": "white bishop",
    "N": "white knight",
    "P": "white pawn",
    "k": "black king",
    "q": "black queen",
    "r": "black rook",
    "b": "black bishop",
    "n": "black knight",
    "p": "black pawn",
}


def position_after(fen: str, moves: list[str]) -> str:
    board = chess.Board(fen)
    for uci in moves:
        board.push_uci(uci)
    return board.fen()


def play_student_move(fen: str, solution: list[str], ply: int, uci: str) -> dict:
    """Apply one student move.

    Solution moves alternate: student, opponent, student, opponent.
    `ply` is the index of the move the student must find.
    """
    board = chess.Board(fen)
    for move in solution[:ply]:
        board.push_uci(move)
    try:
        candidate = chess.Move.from_uci(uci.strip().lower())
    except ValueError:
        return {"illegal": True, "fen": board.fen(), "ply": ply, "done": False, "correct": False}
    if candidate not in board.legal_moves:
        return {"illegal": True, "fen": board.fen(), "ply": ply, "done": False, "correct": False}
    expected = solution[ply]
    if candidate.uci() != expected:
        return {"illegal": False, "correct": False, "fen": board.fen(), "ply": ply, "done": True}
    board.push(candidate)
    ply += 1
    if ply >= len(solution):
        return {"illegal": False, "correct": True, "fen": board.fen(), "ply": ply, "done": True}
    board.push_uci(solution[ply])
    ply += 1
    return {
        "illegal": False,
        "correct": True,
        "fen": board.fen(),
        "ply": ply,
        "done": ply >= len(solution),
    }


def san_of(fen: str, moves_before: list[str], uci: str) -> str:
    board = chess.Board(fen)
    for move in moves_before:
        board.push_uci(move)
    return board.san(chess.Move.from_uci(uci))


def board_view(fen: str, *, white_at_bottom: bool | None = None) -> dict:
    board = chess.Board(fen)
    white_bottom = board.turn == chess.WHITE if white_at_bottom is None else white_at_bottom
    ranks = range(7, -1, -1) if white_bottom else range(8)
    files = range(8) if white_bottom else range(7, -1, -1)
    rows = []
    for rank in ranks:
        row = []
        for file in files:
            square = chess.square(file, rank)
            piece = board.piece_at(square)
            row.append(
                {
                    "name": chess.square_name(square),
                    "piece": piece.symbol() if piece else "",
                    "glyph": GLYPHS.get(piece.symbol(), "") if piece else "",
                    "label": PIECE_NAMES.get(piece.symbol(), "") if piece else "empty",
                    "dark": (chess.square_file(square) + chess.square_rank(square)) % 2 == 0,
                }
            )
        rows.append(row)
    return {"rows": rows, "turn": "white" if board.turn == chess.WHITE else "black", "fen": fen}
