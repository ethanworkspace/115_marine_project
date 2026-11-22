import unittest

from src.evaluation.grounded.pipeline import validate_grounded_question
from tests.evaluation.grounded_fixtures import make_corpus_record, make_evidence, make_question


class MultiDocumentGenerationTests(unittest.TestCase):
    def test_two_required_evidence_documents_resolve(self):
        a = make_corpus_record("a", "doc-a", text="吳郭魚池塘管理資料記載應保持水質穩定，並觀察攝食狀況。")
        b = make_corpus_record("b", "doc-b", text="吳郭魚養殖資料記載魚群活動與攝食變化需要定期記錄。")
        ea, eb = make_evidence(a), make_evidence(b)
        answer = "一份資料要求保持水質穩定；另一份資料要求定期記錄魚群活動與攝食變化。"
        question = make_question(
            [ea, eb], question_text="吳郭魚養殖管理應同時掌握哪些水質與魚群資訊？",
            answer=answer,
            quotes=[
                {"chunk_id": "a", "quote": "資料記載應保持水質穩定"},
                {"chunk_id": "b", "quote": "魚群活動與攝食變化需要定期記錄"},
            ],
        )
        corpus = {"a": a, "b": b}
        self.assertTrue(question["multi_document"])
        self.assertEqual(len(question["required_documents"]), 2)
        self.assertEqual(validate_grounded_question(question, corpus), [])


if __name__ == "__main__":
    unittest.main()
