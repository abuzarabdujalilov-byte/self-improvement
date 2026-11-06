"""Limited-depth chess search. Difficulty is search depth, not a fake label."""

from __future__ import annotations

import random

import chess

VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}
DEPTH = {"easy": 1, "medium": 2, "hard": 3}


def evaluate(board: chess.Board) -> int:
    if board.is_checkmate():
        return -100_000 if board.turn == chess.WHITE else 100_000
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    score = 0
    for square, piece in board.piece_map().items():
        value = VALUES[piece.piece_type] + _placement(piece, square)
        score += value if piece.color == chess.WHITE else -value
    return score


def _placement(piece: chess.Piece, square: int) -> int:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    center = 3 - max(abs(file - 3.5), abs(rank - 3.5))
    if piece.piece_type == chess.KNIGHT:
        bonus = int(center * 8)
        if file in {0, 7}:
            bonus -= 20
        return bonus
    if piece.piece_type == chess.BISHOP:
        return int(center * 4)
    if piece.piece_type == chess.PAWN:
        advanced = rank if piece.color == chess.WHITE else 7 - rank
        return advanced * 2
    return 0


def _ordered(board: chess.Board) -> list[chess.Move]:
    moves = list(board.legal_moves)
    moves.sort(key=lambda move: board.is_capture(move) or board.gives_check(move), reverse=True)
    return moves


def _search(board: chess.Board, depth: int, alpha: int, beta: int) -> int:
    if depth == 0 or board.is_game_over():
        return evaluate(board)
    if board.turn == chess.WHITE:
        best = -1_000_000
        for move in _ordered(board):
            board.push(move)
            best = max(best, _search(board, depth - 1, alpha, beta))
            board.pop()
            alpha = max(alpha, best)
            if beta <= alpha:
                break
        return best
    best = 1_000_000
    for move in _ordered(board):
        board.push(move)
        best = min(best, _search(board, depth - 1, alpha, beta))
        board.pop()
        beta = min(beta, best)
        if beta <= alpha:
            break
    return best


def choose_move(board: chess.Board, level: str, rng: random.Random | None = None) -> chess.Move:
    rng = rng or random.Random()
    depth = DEPTH.get(level, 2)
    legal = _ordered(board)
    if level == "easy":
        captures = [move for move in legal if board.is_capture(move)]
        pool = captures or legal
        return rng.choice(pool)
    white = board.turn == chess.WHITE
    best_move = legal[0]
    best_score = -1_000_000 if white else 1_000_000
    scored = []
    for move in legal:
        board.push(move)
        score = _search(board, depth - 1, -1_000_000, 1_000_000)
        board.pop()
        scored.append((score, move))
        if (white and score > best_score) or (not white and score < best_score):
            best_score = score
            best_move = move
    best_moves = [move for score, move in scored if score == best_score]
    return rng.choice(best_moves or [best_move])
