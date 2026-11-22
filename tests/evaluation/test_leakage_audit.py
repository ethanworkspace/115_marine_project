import unittest

from src.evaluation.grounded_baselines import leakage_audit
from tests.evaluation.grounded_baseline_fixtures import corpus_rows, question


class LeakageAuditTests(unittest.TestCase):
    def test_reports_long_exact_substring_without_filtering_direct(self):
        corpus = corpus_rows()
        corpus[0]["text"] = "本文說明水質管理內容樣本，應檢視溶氧與鹽度變化。"
        q = question()
        q["question"] = "本文說明水質管理內容樣本，應檢視溶氧"
        report = leakage_audit([q], {row["chunk_id"]: row for row in corpus}, suspicious_substring_length=16)
        self.assertEqual(report["question_count"], 1)
        self.assertEqual(report["suspicious_question_count"], 1)
        self.assertTrue(report["direct_questions_are_retained"])


if __name__ == "__main__":
    unittest.main()
