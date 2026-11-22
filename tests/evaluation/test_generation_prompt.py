import unittest
from pathlib import Path

from src.evaluation.generation.ollama import load_generation_prompt


class GenerationPromptTests(unittest.TestCase):
    def test_prompt_is_evidence_bound_and_abstains(self):
        prompt = load_generation_prompt(Path(__file__).resolve().parents[2])
        self.assertIn("只能根據", prompt)
        self.assertIn("insufficient_evidence", prompt)
        self.assertIn("繁體中文", prompt)


if __name__ == "__main__":
    unittest.main()
