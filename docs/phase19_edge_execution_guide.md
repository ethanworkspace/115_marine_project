# Phase 19A — execution gate and measurement guide

## Current state

No physical edge device was specified. `configs/edge_target_device.yaml` is a pending
JSON-compatible YAML 1.2 template (matching the project's existing configuration style).
Its schema is valid, but its semantic execution gate is false. It does not designate
the current Windows/RTX 4060 research host. No model was loaded, unloaded or generated.

Default preparation: `.venv/Scripts/python.exe scripts/phase19_edge_benchmark.py`.
Actual execution is a separate `--execute` invocation on the named physical target.
Do not execute until device fields and runtime preflight are complete.

## Target fields

Provide confirmed device name/ID and execution hostname, CPU, accelerator availability,
RAM and accelerator/unified memory, OS/build, local Ollama endpoint/version, storage,
sensor identities/scopes, deployment mode and declared runtime/power/cooling settings.
Explicitly mark absent GPU/NPU as unavailable. Unknown CPU/OS/RAM is not a ready target.
The execution hostname must match `execution_node`; there is no automatic host fallback.
The current adapter supports Ollama and read-only Windows/Linux RAM plus optional
nvidia-smi device-wide GPU telemetry. Other NPU/unified-memory/power-meter adapters
are not fabricated; unavailable measurements stay null. No automatic installation.

Acceptance thresholds are absent in the supplied research artifacts. Consequently
`acceptance_thresholds_defined=false`; observations are descriptive feasibility.
Any genuine prior threshold must include its original source/date before any execution.
Do not add pass/fail thresholds after observing device results.

## Immutable physical-device inputs

`data/evaluation/edge/phase19_inputs_v1/` contains:

- Exact 60-question Phase 18 subset, in original order.
- All frozen E4 Top-5 context IDs/order/text and evaluation-side Silver references.
- Byte-identical generation_v2 prompt and original output schema.
- Same-model Phase 17 answers for behavior comparison (no historical latency imported).
- SHA-256 bundle manifest. Every file is checked before execution.

Copy these immutable inputs, evaluation package and frozen model identity manifests to
the physical target. Copy existing exact model artifacts only; do not download a new
model, change quantization or create a variant. Never copy device results over research
host Corpus/Silver/Retrieval/Generation artifacts. Use a separate results directory.

## Frozen execution

All four candidates keep existing digests and quality status. Before execution the
adapter checks installed tags, exact digest, parameter count, quantization, native
context and runtime version. A missing/different model blocks preflight; no substitute.

Same generation_v2 prompt/formatting/schema, protocol v2.2, temperature 0, top_p 1,
seed 15015, max output 1024, experimental num_ctx 8192. Only frozen options are applied;
runtime thread/batch/offload defaults and declared settings are recorded, not tuned.
No per-model parser, JSON cleaning, reference/evidence labels or parent context in input.

Three unload-verified cold starts per model use the same first frozen question.
Runtime load duration and first observed ready-state upper bound are separate.
OS disk cache is not forcibly cleared and that limitation is retained.
Each full warm block uses one fixed non-benchmark warm-up, then all 60 questions serially.
Three rotating whole-model passes are predefined; all models retain the same question order.
Warm-up/cold results never enter warm performance means.
Loss of verified residency remains a limitation, not a quietly labeled warm request.
Incomplete runs retain expected denominators and cannot become deployable_on_device.

Only parse/schema/runtime technical failures permit one identical fresh retry;
maximum_attempts=2. All raw content, thinking channels, stream events, errors, attempts,
token counts and timing are saved. No retry-until-success or best-answer selection.

## Timing / token semantics

TTFT_final_answer means request sent to first non-empty `message.content` token in the
structured final-output channel, excluding separate `message.thinking` tokens. It is not
time to the first natural-language character inside the JSON answer field.
TTFT_any_token includes thinking when exposed. Inline mixed reasoning/content cannot
provide honest final-token timing and remains null; the raw output is not repaired.
Runtime TPS is eval_count/decode_duration, with its actual token semantics saved.
Visible-answer TPS needs a separately identified content count and duration. Thinking
counts cannot be guessed from string length, nor silently compared as visible TPS.
Request wall time, final attempt time and retry-inclusive protocol time are separate.

## Memory / power / thermal

The current RAM sampler measures whole-device used RAM. Device-wide VRAM samples are
not process/tensor peaks. All values save scope, sensor, phase and sampling interval.
Unified pools are not estimated by adding RAM to VRAM. Sampling peaks are lower-bound
observations, not guaranteed absolute peaks. GPU-board watts are not whole-device watts.
Energy integrates measured, continuous-scope samples only; missing samples yield null.
Thermal/throttling/clock values stay null without an appropriate sensor.
Instrumentation overhead and scope limitations must accompany results.
Frozen Phase 18 protocol specifies no sustained-load duration; this round adds none.

## Interpretation / later phases

Hardware status is separate from quality status. Qwen remains evaluation_unresolved,
even if fastest; its judge conflict and Gemma reference bias remain. Human review is 0.
No human-validated best model, final quality winner, weighted score or auto migration.
Descriptive Pareto results exclude missing/incomparable axes.
19A is generator_only, even when eventual deployment_mode is full_rag. 19B is separately
planned only after completed 19A: independently time BM25, embedding, RRF, reranker,
generation and total on the target itself. No historical RTX 4060 timing can be added.
Actual target-runtime/sensor validation is still required; synthetic tests prove tooling
invariants, not device feasibility or production readiness.
