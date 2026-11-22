import unittest

from src.evaluation.phase20_protocol import common_config_issues


class SamePromptTests(unittest.TestCase):
    def test_prompt_schema_and_generation_parameters_must_match(self):
        row = {"prompt_sha256": "p", "schema_sha256": "s", "temperature": 0,
               "top_p": 1, "seed": 15015, "max_output": 1024, "context": 8192}
        self.assertEqual(common_config_issues([dict(row) for _ in range(4)]), [])
        rows = [dict(row) for _ in range(4)]
        rows[2]["max_output"] = 768
        self.assertIn("non_common_or_missing_max_output", common_config_issues(rows))


if __name__ == "__main__":
    unittest.main()
