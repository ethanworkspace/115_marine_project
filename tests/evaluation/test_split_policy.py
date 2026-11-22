import unittest
from pathlib import Path


class SplitPolicyTests(unittest.TestCase):
    def test_policy_groups_documents_versions_and_defers_locking(self):
        text = Path("docs/evaluation_split_policy.md").read_text(encoding="utf-8")
        for term in ("document/version", "development", "locked_test", "source_holdout", "does not assign or lock"):
            self.assertIn(term, text)


if __name__ == "__main__":
    unittest.main()
