import json
import unittest
from src.evaluation.ragas_eval.runtime import technical_retry, sha_text


def response(text):
    return {'message': {'content': text}, 'done': True, 'done_reason': 'stop'}


class JudgeRetryTests(unittest.TestCase):
    def test_no_retry_when_valid(self):
        saved = []
        result = technical_retry(lambda: response('{"score":0}'), json.loads, saved.append)
        self.assertEqual(result['score'], 0)  # low scores must never trigger retry
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['raw_output_sha256'], sha_text(saved[0]['raw_output']))

    def test_one_fresh_retry_same_call_and_raw_preserved(self):
        calls, saved = [], []
        def call():
            calls.append(1)
            return response('invalid' if len(calls) == 1 else '{"ok":true}')
        self.assertTrue(technical_retry(call, json.loads, saved.append)['ok'])
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved[0]['raw_output'], 'invalid')
        self.assertFalse(saved[0]['json_parse_status'])
        self.assertTrue(saved[1]['schema_status'])

    def test_failure_stops_at_two(self):
        saved = []
        with self.assertRaises(RuntimeError):
            technical_retry(lambda: response('bad'), json.loads, saved.append)
        self.assertEqual(len(saved), 2)

    def test_no_fence_stripping_or_repair(self):
        saved = []
        with self.assertRaises(RuntimeError):
            technical_retry(lambda: response('```json\n{"ok":true}\n```'), json.loads, saved.append)
        self.assertTrue(all(not r['json_parse_status'] for r in saved))

    def test_truncation_is_technical_failure_even_with_valid_json(self):
        saved = []
        with self.assertRaises(RuntimeError):
            technical_retry(lambda: {**response('{"ok":true}'), 'done_reason': 'length'}, json.loads, saved.append)
        self.assertEqual(len(saved), 2)
