import unittest

from src.evaluation.annotation import records_for_queue


class AnnotationQueueTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"question_id": "d", "annotation_status": "draft"},
            {"question_id": "a", "annotation_status": "annotated"},
            {"question_id": "r", "annotation_status": "reviewed"},
            {"question_id": "b", "annotation_status": "blocked"},
        ]

    def test_three_queues_are_state_separated(self):
        self.assertEqual([x["question_id"] for x in records_for_queue(self.records, "annotation_queue")], ["d"])
        self.assertEqual([x["question_id"] for x in records_for_queue(self.records, "review_queue")], ["a"])
        self.assertEqual([x["question_id"] for x in records_for_queue(self.records, "completed_queue")], ["r"])

    def test_unknown_queue_fails_explicitly(self):
        with self.assertRaises(ValueError):
            records_for_queue(self.records, "locked_queue")


if __name__ == "__main__":
    unittest.main()
