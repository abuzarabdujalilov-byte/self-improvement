import os
import tempfile
import unittest
from pathlib import Path

import chess

from lucid.app import create_app
from lucid.chessplay import play_student_move
from lucid.crypto import decrypt, encrypt
from lucid.db import Database
from lucid.progress import answer_matches, logic_accuracy, next_chess_target, pick_logic_item, pick_puzzle

SECRET = "student-owned-gemini-key-123456"


def mate_puzzle():
    fen = "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"
    board = chess.Board(fen)
    move = chess.Move.from_uci("f7g7")
    assert move in board.legal_moves
    board.push(move)
    assert board.is_checkmate()
    return {"id": "mate1", "rating": 1000, "fen": fen, "solution": ["f7g7"], "themes": ["mateIn1"]}


LOGIC = [
    {"id": "s1", "kind": "short", "difficulty": 1, "prompt": "Next? 2, 4, 8", "answers": ["16"]},
    {"id": "s2", "kind": "short", "difficulty": 1, "prompt": "Yes or no?", "answers": ["yes"]},
    {"id": "s3", "kind": "short", "difficulty": 2, "prompt": "Harder", "answers": ["3"]},
    {"id": "l1", "kind": "long", "prompt": "Why?", "coach_notes": "Look for a reason."},
]


class RuleTests(unittest.TestCase):
    def test_chess_target_moves_with_the_result(self):
        self.assertEqual(next_chess_target(1200, True), 1250)
        self.assertEqual(next_chess_target(1200, False), 1150)
        self.assertEqual(next_chess_target(600, False), 600)

    def test_puzzle_pick_prefers_the_nearest_unseen_rating(self):
        puzzles = [
            {"id": "a", "rating": 900},
            {"id": "b", "rating": 1200},
            {"id": "c", "rating": 1210},
        ]
        self.assertEqual(pick_puzzle(puzzles, 1200, set())["id"], "b")
        self.assertEqual(pick_puzzle(puzzles, 1200, {"b"})["id"], "c")

    def test_logic_score_ignores_nothing_and_uses_recent_accuracy(self):
        self.assertIsNone(logic_accuracy([]))
        self.assertEqual(logic_accuracy([True, False]), 50)

    def test_answer_matching_is_tolerant_of_case_and_space(self):
        self.assertTrue(answer_matches("  Yes. ", ["yes"]))
        self.assertFalse(answer_matches("no", ["yes"]))

    def test_long_problems_are_offered_after_three_completed_items(self):
        chosen = pick_logic_item(LOGIC, set(), [True, True, False], 3)
        self.assertEqual(chosen["kind"], "long")

    def test_a_wrong_puzzle_move_does_not_change_the_position(self):
        puzzle = mate_puzzle()
        missed = play_student_move(puzzle["fen"], puzzle["solution"], 0, "f7f8")
        self.assertTrue(missed["done"])
        self.assertFalse(missed["correct"])
        self.assertEqual(missed["fen"], puzzle["fen"])
        solved = play_student_move(puzzle["fen"], puzzle["solution"], 0, "f7g7")
        self.assertTrue(solved["correct"])
        self.assertTrue(solved["done"])


class AppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.calls = []

        def fake_send(**kwargs):
            self.calls.append(kwargs)
            if kwargs["api_key"].endswith("bad"):
                return {"modelId": kwargs["model_id"], "error": {"code": "invalid_key", "message": "That API key was rejected."}}
            return {"text": "A generated reply", "modelId": kwargs["model_id"]}

        self.db = Database(Path(self.directory.name) / "lucid.db")
        self.aes = os.urandom(32)
        self.app = create_app(
            database=self.db,
            secret_key=os.urandom(32),
            aes_key=self.aes,
            puzzles=[mate_puzzle(), {"id": "other", "rating": 1400, "fen": mate_puzzle()["fen"], "solution": ["f7g7"], "themes": []}],
            logic_items=LOGIC,
            send_message=fake_send,
            dev_login=True,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.directory.cleanup()

    def sign_in(self):
        self.client.post("/dev-login")
        self.client.post("/age", data={"confirm": "yes"})

    def save_key(self, key=SECRET):
        response = self.client.post("/account", data={"api_key": key, "model_id": "gemini-3.6-flash"})
        self.calls.clear()
        return response

    def test_practice_is_closed_until_a_personal_key_is_accepted(self):
        self.sign_in()
        page = self.client.get("/practice/chess")
        self.assertEqual(page.status_code, 200)
        assistant = self.client.get("/assistant")
        self.assertEqual(assistant.status_code, 302)
        self.assertIn("/account", assistant.location)
        rejected = self.save_key("rejected-key-value-xxxxbad")
        self.assertEqual(rejected.status_code, 302)
        self.assertIsNone(self.db.get_key_row(1))
        saved = self.save_key()
        self.assertEqual(saved.status_code, 302)
        row = self.db.get_key_row(1)
        self.assertNotIn(SECRET, row["ciphertext"])
        self.assertEqual(decrypt(self.aes, row["nonce"], row["ciphertext"]), SECRET)
        page = self.client.get("/account").get_data(as_text=True)
        self.assertNotIn(SECRET, page)
        self.assertIn("3456", page)

    def test_chess_result_changes_the_score_and_the_next_puzzle(self):
        self.sign_in()
        self.save_key()
        self.client.get("/practice/chess")
        wrong = self.client.post("/practice/chess/move", data={"uci": "f7f8"})
        self.assertEqual(wrong.status_code, 302)
        self.assertEqual(self.db.get_user(1)["chess_target"], 1350)
        self.client.post("/practice/chess/next")
        solved = self.client.post("/practice/chess/move", data={"uci": "f7g7"})
        self.assertEqual(solved.status_code, 302)
        self.assertEqual(self.db.get_user(1)["chess_target"], 1400)
        self.assertEqual(self.calls, [])

    def test_short_logic_is_marked_by_the_site_and_long_logic_uses_gemini(self):
        self.sign_in()
        self.save_key()
        self.client.get("/practice/logic")
        self.client.post("/practice/logic/answer", data={"answer": "16"})
        self.assertEqual(logic_accuracy([True]), 100)
        self.assertEqual(self.db.attempts(1, "logic_short")[0]["correct"], 1)
        self.assertEqual(self.calls, [])
        self.client.post("/practice/logic/next")
        self.client.post("/practice/logic/answer", data={"answer": "no"})
        self.client.post("/practice/logic/next")
        self.client.post("/practice/logic/answer", data={"answer": "3"})
        self.client.post("/practice/logic/next")
        page = self.client.get("/practice/logic")
        self.assertIn("Why?", page.get_data(as_text=True))
        sent = self.client.post("/practice/logic/answer", data={"answer": "Because the club members may already have been strong students."})
        self.assertEqual(sent.status_code, 302)
        self.assertEqual(self.calls[-1]["model_id"], "gemini-3.6-flash")
        self.assertEqual(self.calls[-1]["api_key"], SECRET)
        self.assertIsNone(self.db.attempts(1, "logic_long")[0]["correct"])
        dashboard = self.client.get("/dashboard").get_data(as_text=True)
        self.assertIn("67%", dashboard)
        self.assertNotIn(SECRET, dashboard)

    def test_assistant_keeps_context_and_rejects_an_unknown_model(self):
        self.sign_in()
        self.save_key()
        self.client.get("/practice/chess")
        puzzle_id = self.db.get_chess_session(1)["puzzle_id"]
        self.client.post("/assistant/context", data={"kind": "chess", "item_id": puzzle_id})
        self.client.post("/assistant", data={"text": "What should I look at first?"})
        self.assertIn("Unsolved", self.calls[-1]["system_instruction"])
        self.client.post("/assistant", data={"text": "And then?"})
        self.assertEqual(len(self.calls[-1]["messages"]), 3)
        os.environ["GEMINI_API_KEY"] = "shared-key-should-not-be-used-0000"
        try:
            self.client.post("/assistant", data={"text": "Who pays for this?"})
        finally:
            os.environ.pop("GEMINI_API_KEY", None)
        self.assertNotEqual(self.calls[-1]["api_key"], "shared-key-should-not-be-used-0000")
        changed = self.client.post("/account/model", data={"model_id": "gemini-3.5-flash"})
        follow = self.client.get("/account")
        self.assertIn("gemini-3.6-flash", follow.get_data(as_text=True))
        self.assertEqual(changed.status_code, 302)

    def test_age_confirmation_is_required(self):
        self.client.post("/dev-login")
        blocked = self.client.get("/dashboard")
        self.assertIn("/age", blocked.location)
        self.client.post("/age", data={"confirm": "yes"})
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_home_lists_the_real_model_ids(self):
        page = self.client.get("/").get_data(as_text=True)
        for model_id in ("gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"):
            self.assertIn(model_id, page)


if __name__ == "__main__":
    unittest.main()
