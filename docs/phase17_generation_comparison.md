# Phase 17 controlled local generation comparison

This is an **AI-generated Corpus-Grounded Silver Benchmark**. Reference-based
metrics use Silver references and are not human expert correctness.

## Frozen study

The four configured local models are frozen in
`reports/evaluation/generation_models/phase17/generator_comparison_manifest.json`
before generation: Gemma 2 9B (existing frozen baseline), DeepSeek-R1 8B,
Qwen2.5-Coder 7B, and DeepSeek-R1 7B. No model acquisition is permitted.
Each new generator executes all 169 Oracle and all 169 E4 Top-5 questions.
Only the model changes. Prompt, schema, ordering, context IDs, temperature,
top-p, seed, 1024-token limit, 8192 context and the maximum-two-attempt technical
retry contract remain identical. No JSON repairs or reasoning requests.

Qwen has the same digest as the frozen primary judge. Its deterministic metrics
remain comparable; judge-based primary ranking excludes it. Self-judging is
not executed in this version. Native RAGAS 0.4.3 metrics and the Phase 16 local
judge/embedding adapters are imported unchanged. Gemma scores are reused rather
than rejudged, including its failed metric checkpoint.

## Execution

Use `.venv-ragas/Scripts/python.exe`:

1. `scripts/phase17_snapshot.py`
2. `-m src.evaluation.generation_models.runner prepare`
3. `-m src.evaluation.generation_models.runner generate`
4. `-m src.evaluation.generation_models.runner judge`
5. `-m src.evaluation.generation_models.runner report`
6. `scripts/phase17_snapshot.py --verify`

Checkpoints preserve attempts and scores; resume does not rerun successful
outputs, select a best answer, or repeat failed metrics beyond the fixed retry.
Every attempt retains content, separate native thinking fields, stream events,
request hash, token counts, finish reason and error. Capture gaps must be reported
explicitly, never converted to a fictitious complete raw capture.

## Analysis rules

Judge quality metrics are answered-only. Paired comparisons require both valid
scores on matching IDs; excluded counts are shown. All-question citation recall
uses the fixed required-chunk denominator, with failures/abstentions contributing
zero. Token F1 is paired answered-only. Bootstrap: 10,000, seed 17017. A CI
including zero does not support clear superiority on this sample. Low-score
diagnostic threshold is 0.5, frozen before evaluation.

The 30-output judge repeatability subset is chosen deterministically from new,
non-conflicted answered outputs, balancing model/condition/style/species/category
without inspecting judge scores; two fresh complete evaluations are run.

RAM is sampled Ollama process-family working-set sum; it is not unique physical
memory. Device-wide VRAM use and model `size_vram` allocation are distinct from
unavailable per-process peak VRAM. Missing measurements remain null.
Gemma performance is historical on the same machine; cache and CPU/GPU offload
state can differ. Pareto uses unweighted descriptive point estimates of
Faithfulness, Silver-reference Correctness, all-question citation recall and
protocol p95 latency. It is not an automatic final edge-model recommendation.

No E4 execution occurs: Windows Code Integrity/Smart App Control may block its
CUDA DLL. Frozen context checksums establish the reused retrieval condition;
this environment limitation does not invalidate the frozen E4 measurements.

Milkfish has zero questions and calculation has only three: no fabricated
species metrics or strong small-sample conclusions. Citation-ID validity does
not independently prove per-claim citation support. No production changes.

All 169 frozen Silver question/reference records identify `gemma2:9b` as their
generation model. Same-model reference-style alignment can favor the Gemma
baseline in reference-based metrics; Faithfulness and other independently
judged measures, reliability and paired cohorts must be reported separately.
