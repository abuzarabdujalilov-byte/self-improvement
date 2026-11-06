"""Full games on top of python-chess. Puzzle practice stays separate."""

from __future__ import annotations

import io
from datetime import datetime, timezone

import chess
import chess.pgn

from lucid import chessplay
from lucid.elo import AI_RATINGS
from lucid.engine import choose_move

START = chess.STARTING_FEN


def clock_now(game) -> tuple[int, int]:
    white_ms = game["white_ms"]
    black_ms = game["black_ms"]
    if game["status"] != "active" or not game["last_tick"]:
        return white_ms, black_ms
    elapsed = int((datetime.now(timezone.utc) - datetime.fromisoformat(game["last_tick"])).total_seconds() * 1000)
    elapsed = max(0, elapsed)
    if chess.Board(game["fen"]).turn == chess.WHITE:
        white_ms -= elapsed
    else:
        black_ms -= elapsed
    return white_ms, black_ms


def replay(game) -> chess.Board:
    board = chess.Board()
    for uci in filter(None, (game["moves"] or "").split()):
        board.push_uci(uci)
    return board


def history(game) -> list[dict]:
    board = chess.Board()
    rows = []
    for uci in filter(None, (game["moves"] or "").split()):
        move = chess.Move.from_uci(uci)
        rows.append({"uci": uci, "san": board.san(move)})
        board.push(move)
    return rows


def captured(board: chess.Board) -> dict[str, list[str]]:
    initial = {chess.PAWN: 8, chess.KNIGHT: 2, chess.BISHOP: 2, chess.ROOK: 2, chess.QUEEN: 1}
    names = {chess.QUEEN: "Q", chess.ROOK: "R", chess.BISHOP: "B", chess.KNIGHT: "N", chess.PAWN: "P"}
    taken = {"white": [], "black": []}
    for color, key in ((chess.WHITE, "white"), (chess.BLACK, "black")):
        counts: dict[int, int] = {}
        for piece in board.piece_map().values():
            if piece.color == color and piece.piece_type != chess.KING:
                counts[piece.piece_type] = counts.get(piece.piece_type, 0) + 1
        for piece_type, total in initial.items():
            missing = total - counts.get(piece_type, 0)
            taken[key].extend([names[piece_type]] * missing)
    return {"by_white": taken["black"], "by_black": taken["white"]}


def legal_map(board: chess.Board) -> dict[str, list[str]]:
    squares: dict[str, list[str]] = {}
    for move in board.legal_moves:
        origin = chess.square_name(move.from_square)
        squares.setdefault(origin, []).append(move.uci())
    return squares


def outcome(board: chess.Board) -> tuple[str, str] | None:
    if board.is_checkmate():
        result = "0-1" if board.turn == chess.WHITE else "1-0"
        return result, "checkmate"
    if board.is_stalemate():
        return "1/2-1/2", "stalemate"
    if board.is_insufficient_material() or board.can_claim_fifty_moves() or board.is_repetition(3):
        reason = "insufficient material" if board.is_insufficient_material() else "draw"
        return "1/2-1/2", reason
    return None


def to_pgn(game, white_name: str, black_name: str) -> str:
    board = chess.Board()
    exporter = chess.pgn.Game()
    exporter.headers["White"] = white_name
    exporter.headers["Black"] = black_name
    exporter.headers["Result"] = game["result"] or "*"
    node = exporter
    for uci in filter(None, (game["moves"] or "").split()):
        move = chess.Move.from_uci(uci)
        node = node.add_variation(move)
        board.push(move)
    return str(exporter)


def import_pgn(text: str) -> tuple[str, str] | str:
    parsed = chess.pgn.read_game(io.StringIO(text))
    if parsed is None:
        return "That file is not a readable PGN game."
    board = parsed.board()
    moves = []
    for move in parsed.mainline_moves():
        if move not in board.legal_moves:
            return "The PGN contains a move that is not legal."
        moves.append(move.uci())
        board.push(move)
    result = parsed.headers.get("Result", "*")
    if result not in {"1-0", "0-1", "1/2-1/2", "*"}:
        result = "*"
    return " ".join(moves), result


def side_to_move(game, user_id: int, board: chess.Board) -> bool:
    if game["status"] != "active":
        return False
    if game["mode"] == "ai":
        return board.turn == chess.WHITE and user_id == game["white_id"]
    if game["mode"] == "pass":
        return user_id == game["white_id"]
    if board.turn == chess.WHITE:
        return user_id == game["white_id"]
    return user_id == game["black_id"]


def apply_player_move(game, uci: str, white_ms: int, black_ms: int):
    board = replay(game)
    try:
        move = chess.Move.from_uci(uci)
    except chess.InvalidMoveError:
        return {"error": "That is not a chess move."}
    if move not in board.legal_moves:
        # Allow a queen promotion when the client omits the piece.
        if len(uci) == 4:
            promoted = chess.Move.from_uci(uci + "q")
            if promoted in board.legal_moves:
                move = promoted
            else:
                return {"error": "That move is not legal in this position."}
        else:
            return {"error": "That move is not legal in this position."}
    board.push(move)
    moves = (game["moves"] + " " + move.uci()).strip()
    finished = outcome(board)
    fields = {
        "fen": board.fen(),
        "moves": moves,
        "white_ms": max(0, white_ms),
        "black_ms": max(0, black_ms),
        "last_tick": datetime.now(timezone.utc).isoformat(),
    }
    if white_ms <= 0 or black_ms <= 0:
        result = "0-1" if white_ms <= 0 else "1-0"
        fields.update(status="finished", result=result, reason="time", finished_at=datetime.now(timezone.utc).isoformat())
        return {"fields": fields, "board": board, "result": result}
    if finished:
        result, reason = finished
        fields.update(status="finished", result=result, reason=reason, finished_at=datetime.now(timezone.utc).isoformat())
        return {"fields": fields, "board": board, "result": result}
    return {"fields": fields, "board": board, "result": None}


def ai_reply(board: chess.Board, level: str):
    if board.is_game_over() or board.turn != chess.BLACK:
        return None
    move = choose_move(board, level)
    return move


def view(game, user_id: int) -> dict:
    board = replay(game)
    white_ms, black_ms = clock_now(game)
    last = (game["moves"] or "").split()[-1] if game["moves"] else ""
    last_squares = []
    if last:
        last_squares = [last[:2], last[2:4]]
    check_square = ""
    if board.is_check():
        king = board.king(board.turn)
        check_square = chess.square_name(king) if king is not None else ""
    return {
        "board": chessplay.board_view(board.fen(), white_at_bottom=True),
        "fen": board.fen(),
        "legal": legal_map(board) if side_to_move(game, user_id, board) else {},
        "history": history(game),
        "captured": captured(board),
        "last": last_squares,
        "check": check_square,
        "turn": "white" if board.turn == chess.WHITE else "black",
        "can_move": side_to_move(game, user_id, board),
        "white_ms": max(0, white_ms),
        "black_ms": max(0, black_ms),
        "over": game["status"] == "finished" or board.is_game_over(),
    }


def ai_rating(level: str) -> int:
    return AI_RATINGS.get(level, AI_RATINGS["medium"])
