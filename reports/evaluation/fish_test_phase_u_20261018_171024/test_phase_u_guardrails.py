import json
import unittest
from pathlib import Path

OUT = Path(__file__).resolve().parent


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def loadl(name):
    return [json.loads(line) for line in (OUT / name).read_text(encoding="utf-8").splitlines() if line.strip()]


class PhaseUGuardrailTests(unittest.TestCase):
    def test_dgbas_admission_is_scoped_and_corpus_not_built(self):
        manifest = load("corpus_v3_manifest.json")
        self.assertEqual(manifest["status"], "BLOCKED_NOT_BUILT")
        self.assertFalse(manifest["formal_corpus_created"])
        self.assertEqual(len(manifest["admitted_source_allowlist"]), 1)
        self.assertEqual(manifest["admitted_source_allowlist"][0]["source_id"], "DGBAS-79395-2020")
        self.assertEqual(manifest["admitted_source_allowlist"][0]["corpus_inclusion_status"], "not_ingested")
        self.assertEqual(manifest["chunk_count"], 0)

    def test_crosswalk_corrections_are_detached_and_scoped(self):
        overlay = load("source_crosswalk_overlay.json")
        self.assertTrue(overlay["applies_to_new_phase_u_inventory_and_candidate_processing_only"])
        fixes = {x["source_id"]: x for x in overlay["phase_u_applied_corrections"]}
        self.assertEqual(fixes["S08"]["detached_wrong_document"], "養殖漁業防寒須知(農業部漁業署)")
        self.assertEqual(fixes["S10"]["detached_wrong_document"], "訂定總說明與逐條說明（110.4.27）")
        self.assertEqual(fixes["S08"]["admission_status"], "not_admitted")
        self.assertEqual(fixes["S10"]["admission_status"], "not_admitted")

    def test_all_180_questions_remain_ineligible_without_new_corpus(self):
        rows = loadl("question_eligibility_v3.jsonl")
        self.assertEqual(len(rows), 180)
        self.assertFalse(any(x["phase_u_benchmark_eligible"] for x in rows))
        self.assertTrue(all(x["historical_phase_t_record_preserved"] for x in rows))

    def test_retrieval_and_generation_not_fabricated(self):
        rows = loadl("retrieval_results_v3_final.jsonl")
        self.assertEqual(len(rows), 180)
        self.assertTrue(all(x["run_status"] == "NOT_RUN" and x["top5"] == [] for x in rows))
        self.assertEqual((OUT / "generator_results_v3_final.jsonl").read_text(encoding="utf-8"), "")
        metrics = load("evaluation_metrics_v3_final.json")
        self.assertEqual(metrics["model_generation_count"], 0)
        self.assertTrue(all(x["n"] == 0 and x["value"] is None for x in metrics["metrics"].values()))

    def test_protected_baseline_recheck(self):
        frozen = load("frozen_baseline_recheck.json")
        self.assertEqual(frozen["manifest_rows"], 636)
        self.assertTrue(frozen["all_636_match"])
        self.assertTrue(frozen["protected_sqlite_matches"])


if __name__ == "__main__":
    unittest.main()
