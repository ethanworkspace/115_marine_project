import unittest
from pathlib import Path


class GenerationV2PromptTests(unittest.TestCase):
    def test_prompt_preserves_evidence_only_rules_and_context_id_protocol(self):
        text = Path("prompts/generation_v2.txt").read_text(encoding="utf-8")
        for phrase in ("只能根據本次提供的 Evidence", "繁體中文", "insufficient_evidence",
                       "不得輸出 chunk ID", "C1", "重要事實"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
