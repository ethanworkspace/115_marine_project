import unittest

from src.evaluation.grounded.pipeline import benchmark_readiness, make_question_record
from tests.evaluation.grounded_fixtures import make_corpus_record, make_evidence


class GroundedReadinessTests(unittest.TestCase):
    def test_readiness_requires_count_species_categories_styles_and_resolved_evidence(self):
        species_names = ("吳郭魚", "虱目魚", "石斑魚", "烏魚")
        corpus = {}
        evidences = []
        for index, species in enumerate(species_names):
            record = make_corpus_record(
                f"c{index}", f"d{index}", species,
                f"{species}養殖資料記載水質穩定與魚群管理資訊，供評測問題直接引用。",
            )
            evidence = make_evidence(record)
            corpus[record["chunk_id"]] = record
            evidences.append(evidence)
        styles = ("direct", "paraphrase", "contextual")
        categories = ("fact", "water_quality", "disease", "sop")
        questions = []
        for index in range(120):
            evidence = evidences[index % 4]
            style = styles[index % 3]
            category = categories[index % 4]
            questions.append(make_question_record(
                question_id=f"q{index}",
                question="資料記載了哪些養殖資訊？",
                answer="資料記載水質穩定與魚群管理資訊。",
                evidences=[evidence],
                style=style,
                category=category,
                corpus_sha256="c" * 64,
                generation_model="test",
                generation_config={},
                supporting_quotes=[],
            ))
        report = benchmark_readiness(questions, corpus, "c" * 64)
        self.assertTrue(report["grounded_silver_ready"])
        self.assertTrue(all(report["checks"].values()))

    def test_empty_set_is_not_ready(self):
        report = benchmark_readiness([], {}, "c" * 64)
        self.assertFalse(report["grounded_silver_ready"])


if __name__ == "__main__":
    unittest.main()
