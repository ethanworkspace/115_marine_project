# Phase 16 frozen generation evaluation

This evaluates existing outputs from the **AI-generated Corpus-Grounded Silver Benchmark**. It does not generate new answers. `silver_reference_correctness` is the native RAGAS `AnswerCorrectness` implementation renamed in reports to identify its Silver reference. It does not measure human expert, clinical, or authoritative correctness.

## Frozen protocol

- Input: `ragas_input_v2_2.jsonl`, 169 paired questions, 338 rows.
- Conditions: `oracle` and `e4_top5`; never pool primary averages.
- Main judge metrics: answered-only. Abstentions, pending evaluations, skipped metrics and technical failures are separately counted.
- Judge: existing local `qwen2.5-coder:7b`, fixed digest, Ollama 0.35.0. The user approved this replacement after DeepSeek-R1 8B repeatedly exhausted the fixed 4096-token budget. DeepSeek preflight and partial results are preserved under `runtime_diagnostics/deepseek_r1_8b`; none enter the primary or repeatability scores. This judge is distinct from the frozen Gemma generator. No cloud evaluator and no downloaded judge model.
- Judge parameters: temperature 0, top_p 1, seed 16016, output limit 4096, context length 16384. Native RAGAS prompts and examples are unchanged; their checksums and schemas are recorded.
- Native JSON schema passed to Ollama. Any returned reasoning is preserved and runtime behavior is recorded in preflight.
- Embedding: existing BGE-M3, dimension 1024, L2 normalization. Used only for RAGAS Answer Relevancy and reference semantic similarity.
- Native Answer Relevancy strictness 3; Answer Correctness weights 0.75 factuality / 0.25 semantic similarity, beta 1.
- Exactly one fresh retry for a technical transport, completion, JSON or schema failure. Identical request payload. No JSON repair, changed prompt, score-based retry, or selection of a better score.
- Metric checkpoints prevent a resumed process from replacing completed evaluations. Both successful and failed attempts remain in the raw trace.
- Bootstrap: paired by question ID, 10,000 iterations, seed 16016. Pairs must have valid scores and answered outputs in both conditions. Confidence intervals describe this Silver sample only.
- Diagnostic low-score thresholds fixed at `<0.5` before primary execution. These are observational error-analysis labels, not expert correctness judgments.

## Execution

Use `.venv-ragas/Scripts/python.exe`, independently from `.venv` and `.venv-reranker`.

```powershell
.\.venv-ragas\Scripts\python.exe -m src.evaluation.ragas_eval.runner prepare
.\.venv-ragas\Scripts\python.exe -m src.evaluation.ragas_eval.runner preflight
.\.venv-ragas\Scripts\python.exe -m src.evaluation.ragas_eval.runner run
```

`run` resumes the same frozen experiment; it does not retry a completed failed metric. `report` can summarize checkpoints, with unexecuted rows explicitly pending. Do not rerun `preflight` after primary scoring has begun or change the evaluator manifest. The isolated dependency freeze is under `reports/evaluation/ragas/requirements.lock.txt`; RAGAS 0.4.3 requires the recorded `langchain-community==0.4.1` compatibility pin.

The production `.venv` remains the environment for the full project test suite. `.venv-ragas` contains only evaluator dependencies, so the unrelated PDF/Word parser tests cannot be imported there without their existing parser libraries. Run the ten new Phase 16 test modules in the isolated environment; all 23 cases pass. Exact-text embedding vectors are memoized within the evaluation process; LLM judge calls in both repeatability rounds are fresh and never memoized.

The final full-suite run in `.venv` passed 310 cases and skipped six optional Torch runtime cases. Those six passed earlier in `.venv-reranker`, but a later rerun was blocked by Windows Smart App Control / Code Integrity rejecting `c10_cuda.dll` (WinError 4551), including outside the tool sandbox. The signing-policy event and both test results are preserved. No security policy or old package was changed to bypass this block. The installed files in both old environments remain checksum-identical.

## Interpretation limits

RAGAS Faithfulness judges decomposed claims against all provided contexts. Deterministic citation validity checks whether IDs and provenance resolve. Required-evidence citation recall checks whether known Silver evidence is cited. None of these alone establishes that every claim's individual citation entails that claim; claim-to-citation alignment and local judge competence remain limitations.

The approved Qwen judge is a code-specialized 7B model, not an aquaculture expert. Its competence and repeatability must be reported; changing judge identity does not establish domain authority.

The 11 E4 questions lacking complete required evidence form an observational subset. Answering such a question is not automatically hallucination. Retrieval-hit but low-scoring answers also do not establish strict causal attribution.

Judge repeatability uses two fresh evaluations of a fixed coverage-first subset of 30 answered rows (15 per condition), chosen without inspecting scores. Report valid paired counts, exact agreement, mean absolute difference and correlation; do not hide failed repeat evaluations or undefined correlation for constant scores.

Small category/species groups and the three calculation questions are descriptive. Preserve the deterministic numerical results and the earlier evidence-generation leakage audit. Do not collapse retrieval, generation, citation and judge metrics into a composite score.
