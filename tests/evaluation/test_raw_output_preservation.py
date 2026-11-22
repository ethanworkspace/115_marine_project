import json
import unittest

from src.evaluation.generation.runner_v2 import call_ollama_v2


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=True):
        yield json.dumps({"message": {"content": self.content}, "done": True}).encode("utf-8")


class FakeSession:
    def __init__(self, content):
        self.content = content
        self.request = None

    def post(self, *_args, **kwargs):
        self.request = kwargs
        return FakeResponse(self.content)


class RawOutputPreservationTests(unittest.TestCase):
    def test_malformed_json_body_is_returned_and_hashed_before_parse_error(self):
        session = FakeSession("{ definitely not json")
        result = call_ollama_v2(model="fixture", system_prompt="s", user_prompt="u", session=session)
        self.assertEqual(result["raw_output"], "{ definitely not json")
        self.assertIsNotNone(result["raw_output_sha256"])
        self.assertTrue(result["parse_error"])
        self.assertTrue(result["response_received"])
        self.assertIn("format", session.request["json"])


if __name__ == "__main__":
    unittest.main()
