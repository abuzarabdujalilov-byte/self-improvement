import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path

from gemini_client.client import send_message
from gemini_client.models import ALLOWED_MODEL_IDS, DEFAULT_MODEL_ID
from server.app import create_app
from server.vault import Record, Vault

SECRET = "user-owned-key-value-1234567890"


class Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def success_opener(text="A useful reply"):
    def opener(request, timeout):
        opener.last_request = request
        return Response({"candidates": [{"content": {"parts": [{"thought": True, "text": "hidden"}, {"text": text}]}}]})

    return opener


class GeminiClientTests(unittest.TestCase):
    def test_allow_list_matches_the_documented_models(self):
        self.assertEqual(
            ALLOWED_MODEL_IDS,
            frozenset({"gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"}),
        )
        self.assertNotIn("gemini-3.5-flash", ALLOWED_MODEL_IDS)
        self.assertEqual(DEFAULT_MODEL_ID, "gemini-3.6-flash")

    def test_rejects_deprecated_and_invented_ids_without_a_request(self):
        def opener(request, timeout):
            raise AssertionError("deprecated models must not be sent to Google")

        for model_id in ("gemini-3.5-flash", "gemini-3.5", "gemini-3.8"):
            result = send_message(
                api_key=SECRET,
                model_id=model_id,
                messages=[{"role": "user", "text": "Hello"}],
                opener=opener,
            )
            self.assertEqual(result["error"]["code"], "model_unavailable")

    def test_sends_history_and_hides_the_key_from_the_url(self):
        opener = success_opener("Ready when you are")
        result = send_message(
            api_key=SECRET,
            model_id="gemini-3.8-flash",
            messages=[
                {"role": "user", "text": "First question"},
                {"role": "model", "text": "First answer"},
                {"role": "user", "text": "Follow up"},
            ],
            system_instruction="Be concise.",
            opener=opener,
        )
        self.assertEqual(result["text"], "Ready when you are")
        body = json.loads(opener.last_request.data.decode())
        self.assertEqual([item["role"] for item in body["contents"]], ["user", "model", "user"])
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "Be concise.")
        self.assertNotIn(SECRET, opener.last_request.full_url)
        self.assertEqual(opener.last_request.get_header("X-goog-api-key"), SECRET)

    def test_maps_invalid_key_quota_and_network_errors(self):
        def http_error(status, payload):
            def opener(request, timeout):
                raise urllib.error.HTTPError(
                    request.full_url,
                    status,
                    "error",
                    {},
                    io.BytesIO(json.dumps(payload).encode()),
                )

            return opener

        invalid = send_message(
            api_key=SECRET,
            model_id="gemini-3.6-flash",
            messages=[{"role": "user", "text": "Hello"}],
            opener=http_error(400, {"error": {"message": f"API key not valid {SECRET}", "status": "INVALID_ARGUMENT"}}),
        )
        self.assertEqual(invalid["error"]["code"], "invalid_key")
        self.assertNotIn(SECRET, invalid["error"]["message"])

        quota = send_message(
            api_key=SECRET,
            model_id="gemini-3.6-flash",
            messages=[{"role": "user", "text": "Hello"}],
            opener=http_error(429, {"error": {"message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}),
        )
        self.assertEqual(quota["error"]["code"], "quota")

        def network(request, timeout):
            raise urllib.error.URLError("offline")

        offline = send_message(
            api_key=SECRET,
            model_id="gemini-3.6-flash",
            messages=[{"role": "user", "text": "Hello"}],
            opener=network,
        )
        self.assertEqual(offline["error"]["code"], "network")

    def test_maps_a_safety_block(self):
        def opener(request, timeout):
            return Response({"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]})

        result = send_message(
            api_key=SECRET,
            model_id="gemini-3.5-flash-lite",
            messages=[{"role": "user", "text": "Hello"}],
            opener=opener,
        )
        self.assertEqual(result["error"]["code"], "blocked")


class VaultTests(unittest.TestCase):
    def test_remembered_key_is_encrypted_and_reloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.json"
            aes_key = os.urandom(32)
            vault = Vault(aes_key, path)
            vault.save(
                "person",
                Record(
                    api_key=SECRET,
                    model_id="gemini-3.6-flash",
                    remember=True,
                    fingerprint="7890",
                    messages=[{"role": "user", "text": "Plan my revision"}],
                ),
            )
            stored = path.read_text(encoding="utf-8")
            self.assertNotIn(SECRET, stored)
            reloaded = Vault(aes_key, path).get("person")
            self.assertEqual(reloaded.api_key, SECRET)
            self.assertEqual(reloaded.messages[0]["text"], "Plan my revision")

    def test_session_key_is_not_written(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "vault.json"
            aes_key = os.urandom(32)
            vault = Vault(aes_key, path)
            vault.save(
                "visitor",
                Record(api_key=SECRET, model_id="gemini-3.6-flash", remember=False, fingerprint="7890"),
            )
            self.assertNotIn(SECRET, path.read_text(encoding="utf-8"))
            self.assertIsNone(Vault(aes_key, path).get("visitor"))
            self.assertEqual(vault.get("visitor").api_key, SECRET)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.calls = []

        def fake_send(**kwargs):
            self.calls.append(kwargs)
            if kwargs["api_key"] == "invalid-key-value-0000000000":
                return {"modelId": kwargs["model_id"], "error": {"code": "invalid_key", "message": "That API key was rejected."}}
            return {"text": f"Reply {len(self.calls)}", "modelId": kwargs["model_id"]}

        self.vault = Vault(os.urandom(32), Path(self.directory.name) / "vault.json")
        self.app = create_app(secret_key=os.urandom(32), vault=self.vault, send_message=fake_send)
        self.client = self.app.test_client()

    def tearDown(self):
        self.directory.cleanup()

    def test_pages_list_real_models_and_no_embedded_key(self):
        page = self.client.get("/").get_data(as_text=True)
        chat = self.client.get("/chat").get_data(as_text=True)
        for model_id in ALLOWED_MODEL_IDS:
            self.assertIn(model_id, page)
        self.assertIn("gemini-3.5-flash", page)
        self.assertIn("deprecated", page.lower())
        self.assertNotIn("GEMINI_API_KEY", page + chat)
        script = self.client.get("/static/js/chat.js")
        try:
            self.assertIn("/api/key", script.get_data(as_text=True))
        finally:
            script.close()

    def test_chat_requires_the_users_own_key_even_if_the_environment_has_one(self):
        os.environ["GEMINI_API_KEY"] = "shared-server-key-should-never-run"
        try:
            response = self.client.post("/api/chat", json={"text": "Hello"})
        finally:
            os.environ.pop("GEMINI_API_KEY", None)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_key")
        self.assertEqual(self.calls, [])

    def test_invalid_key_is_not_stored_or_echoed(self):
        response = self.client.post(
            "/api/key",
            json={"apiKey": "invalid-key-value-0000000000", "modelId": "gemini-3.6-flash", "remember": True},
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("invalid-key-value-0000000000", response.get_data(as_text=True))
        self.assertFalse(self.client.get("/api/session").get_json()["hasKey"])

    def test_deprecated_model_is_rejected_before_gemini_is_called(self):
        response = self.client.post(
            "/api/key",
            json={"apiKey": SECRET, "modelId": "gemini-3.5-flash"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "model_unavailable")
        self.assertEqual(self.calls, [])

    def test_conversation_uses_the_selected_model_and_prior_turns(self):
        saved = self.client.post(
            "/api/key",
            json={"apiKey": SECRET, "modelId": "gemini-3.5-flash-lite", "remember": False},
        )
        self.assertEqual(saved.status_code, 200)
        body = saved.get_json()
        self.assertEqual(body["fingerprint"], "7890")
        self.assertNotIn(SECRET, saved.get_data(as_text=True))
        self.assertNotIn("apiKey", body)

        first = self.client.post("/api/chat", json={"text": "How should I revise?"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["messages"][1]["modelId"], "gemini-3.5-flash-lite")

        switched = self.client.patch("/api/model", json={"modelId": "gemini-3.8-flash"})
        self.assertEqual(switched.get_json()["modelId"], "gemini-3.8-flash")
        second = self.client.post("/api/chat", json={"text": "Turn that into a four-week plan."})
        self.assertEqual(second.status_code, 200)
        sent = self.calls[-1]
        self.assertEqual(sent["model_id"], "gemini-3.8-flash")
        self.assertEqual(sent["api_key"], SECRET)
        self.assertEqual(
            [item["text"] for item in sent["messages"]],
            ["How should I revise?", "Reply 2", "Turn that into a four-week plan."],
        )
        self.assertIn("Britain", sent["system_instruction"])
        self.assertEqual(len(second.get_json()["messages"]), 4)

        cleared = self.client.post("/api/chat/reset")
        self.assertEqual(cleared.get_json()["messages"], [])
        removed = self.client.delete("/api/key")
        self.assertFalse(removed.get_json()["hasKey"])
        self.assertEqual(self.client.post("/api/chat", json={"text": "Again"}).status_code, 400)

    def test_failed_reply_does_not_append_the_turn(self):
        self.client.post("/api/key", json={"apiKey": SECRET, "modelId": "gemini-3.6-flash"})

        def fail_once(**kwargs):
            if kwargs["messages"][-1]["text"] == "This will fail":
                return {"modelId": kwargs["model_id"], "error": {"code": "network", "message": "The connection to Gemini failed."}}
            return {"text": "ok", "modelId": kwargs["model_id"]}

        self.app.config["SEND_MESSAGE"] = fail_once
        failed = self.client.post("/api/chat", json={"text": "This will fail"})
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(self.client.get("/api/session").get_json()["messages"], [])

    def test_key_checks_are_rate_limited(self):
        statuses = [
            self.client.post(
                "/api/key",
                json={"apiKey": "invalid-key-value-0000000000", "modelId": "gemini-3.6-flash"},
            ).status_code
            for _ in range(9)
        ]
        self.assertEqual(statuses[:8], [400] * 8)
        self.assertEqual(statuses[8], 429)


class LiveGeminiTests(unittest.TestCase):
    def test_rejected_key_reaches_google(self):
        result = send_message(
            api_key="AIzaSyINVALIDKEYINVALIDKEYINVALID12",
            model_id="gemini-3.6-flash",
            messages=[{"role": "user", "text": "Hello"}],
            timeout=30,
        )
        self.assertEqual(result["error"]["code"], "invalid_key", result)
        self.assertNotIn("AIzaSyINVALID", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
