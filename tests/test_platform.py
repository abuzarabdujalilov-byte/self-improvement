"""Games, ratings, clubs, and training."""

import unittest

import chess

from lucid.elo import update
from lucid.engine import choose_move
from tests.test_lucid import AppTests


class RuleTests(unittest.TestCase):
    def test_equal_players_move_sixteen_points(self):
        self.assertEqual(update(1200, 1200, 1), 1216)
        self.assertEqual(update(1200, 1200, 0), 1184)

    def test_easy_search_returns_a_legal_move(self):
        board = chess.Board()
        move = choose_move(board, "easy")
        self.assertIn(move, board.legal_moves)


class PlatformTests(AppTests):
    def test_a_game_move_is_checked_and_the_ai_replies(self):
        self.sign_in()
        created = self.client.post("/chess/games", data={"mode": "ai", "level": "easy", "minutes": "5"})
        self.assertEqual(created.status_code, 302)
        code = created.location.rsplit("/", 1)[-1]
        played = self.client.post(f"/chess/games/{code}/move", data={"uci": "e2e4"}, follow_redirects=True)
        page = played.get_data(as_text=True)
        self.assertIn("e4", page)
        self.assertNotIn("dev-key", page)

    def test_opening_line_and_training_are_recorded(self):
        self.sign_in()
        wrong = self.client.post("/chess/openings/italian", data={"uci": "a2a3"}, follow_redirects=True)
        self.assertIn("e4", wrong.get_data(as_text=True))
        right = self.client.post("/chess/openings/italian", data={"uci": "e2e4"}, follow_redirects=True)
        self.assertIn("claims space", right.get_data(as_text=True))
        self.client.get("/training/arithmetic")
        with self.client.session_transaction() as flask_session:
            answer = flask_session["drill"]["rounds"][0]["answer"]
        self.client.post("/training/arithmetic", data={"answer": answer})
        stats = self.client.get("/training").get_data(as_text=True)
        self.assertIn("Arithmetic", stats)

    def test_club_discussion_and_profile(self):
        self.sign_in()
        created = self.client.post("/clubs", data={"name": "Night Study", "description": "A quiet club for long games."})
        self.assertIn("/clubs/", created.location)
        page = self.client.get("/clubs/night-study", follow_redirects=True).get_data(as_text=True)
        self.assertIn("Night Study", page)
        posted = self.client.post("/discussions", data={"category": "philosophy", "title": "What is a reason?", "body": "A reason is support for a conclusion."})
        self.assertEqual(posted.status_code, 302)
        thread = self.client.get(posted.location).get_data(as_text=True)
        self.assertIn("What is a reason?", thread)
        profile = self.client.get("/profile").get_data(as_text=True)
        self.assertIn("Chess rating", profile)
        self.assertIn("1200", profile)


if __name__ == "__main__":
    unittest.main()
