import unittest

from src.evaluation.phase10_recovery import build_recovery_work_queue, deterministic_priority_score


class RecoveryQueueTests(unittest.TestCase):
    def test_phase_order_precedes_score_and_is_deterministic(self):
        args = {
            "local_sources": [{"document_id": "local", "affected_questions": ["q"], "affected_facts": ["f"]}],
            "missing_sources": [{"source_alias_id": "missing", "affected_questions": ["q1", "q2", "q3"]}],
            "fact_gaps": [], "local_impact": {"artifacts": {}}, "ocr_priority": {}, "legacy_documents": [],
        }
        first = build_recovery_work_queue(**args)
        second = build_recovery_work_queue(**args)
        self.assertEqual(first, second)
        self.assertEqual(first[0]["work_type"], "A_local_corpus_omission")
        self.assertEqual(first[1]["work_type"], "B_missing_source")
        self.assertGreater(first[1]["priority_score"], 0)

    def test_priority_inputs_affect_score(self):
        self.assertGreater(deterministic_priority_score(questions=2, facts=3, species=2, categories=3,
                         source_quality=2, recoverability=2),
                         deterministic_priority_score(questions=1, facts=1, species=1, categories=1,
                         source_quality=1, recoverability=1))


if __name__ == "__main__":
    unittest.main()
