"""Standard Elo for finished games. Puzzle targets stay on a separate field."""

START = 1200
K = 32
AI_RATINGS = {"easy": 800, "medium": 1200, "hard": 1600}


def expected(player: int, opponent: int) -> float:
    return 1 / (1 + 10 ** ((opponent - player) / 400))


def update(player: int, opponent: int, score: float) -> int:
    return round(player + K * (score - expected(player, opponent)))
