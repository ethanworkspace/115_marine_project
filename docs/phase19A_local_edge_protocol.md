# Phase 19A — Local Edge Inference Workstation

Target: marine-edge-workstation-01, i5-14400F / 32 GiB DDR4-3200 / RTX 4060 8 GiB dedicated / Windows 11 / Ollama 0.35.0.
This is a workstation feasibility benchmark, not embedded-board or Jetson performance.

The fixed 60-question Phase 18 subset and its 300 E4 contexts are byte-verified against the Phase 19 portable bundle. Four existing artifacts retain their complete digest and quantization. No new retrieval, evaluator, model download, runtime tuning or production migration occurs.

## Execution

- Three verified model-cold starts per artifact; OS disk cache is retained. Ollama absence and WDDM Ollama GPU allocation release are checked.
- Three serial warm rounds in the declared rotating model order, preserving each round's original question order.
- Every block starts after GPU utilization below 5% for 60 consecutive seconds and preferably temperature at most 45 C. The wait is capped at 300 seconds; unmet conditions remain explicit.
- One identical synthetic warm-up outside the formal 60 questions, excluded from statistics.
- Protocol v2.2, existing generation_v2 prompt/schema, temperature 0, top_p 1, seed 15015, 1024 output tokens, 8192 context, at most two fresh identical attempts after technical failure.
- Gemma and Qwen each have a predeclared 1800-second cyclic sustained workload with 300-second reporting intervals. DeepSeek diagnostic candidates do not.
- Inference failure rate uses all executed formal requests, including failed final attempts. Retry success is not a final failure. Missing scheduled requests remain separately reported.

## Measurement interpretation

TTFT-any includes native thinking; TTFT-final-answer starts with the first content-channel token, not native thinking. It measures the final JSON channel rather than the first word in the JSON answer field. Inline unseparated thinking makes final TTFT unavailable. Client streaming reads lines without 512-byte buffering. No model input or output is altered.

Runtime TPS may include thinking. DeepSeek visible-answer TPS is null when Ollama does not provide separate counts and decoding durations. Do not call mixed-token TPS a fair visible-answer speed comparison.

RAM used is whole-system, with individual Ollama process working sets separately recorded. Process working sets are not summed as private RAM because shared pages may be counted twice. Dedicated VRAM is whole-device NVIDIA usage; WDDM GPU process usage and RAM-backed shared GPU memory remain separate, by adapter instance. Shared capacity is not dedicated capacity. Peaks are sampled every two seconds, not exact instantaneous maxima.

Power, if available, is GPU board power only. An N/A sensor remains null; no whole-system watts or energy are estimated. Temperature and clocks do not by themselves prove thermal throttling.

Three-run per-question medians underpin paired performance bootstrap (10000 iterations, seed 19019). No post-result performance thresholds, weighted score, single quality winner or quality-status upgrade is permitted. Qwen quality remains evaluation_unresolved and human support review remains absent.

## Integrity and scope

Existing Phase 19 preparation reports remain frozen. The target config is explicitly updated as authorized. New execution logs and reports are under phase19A. Inputs, Phase 15–18 outputs and production artifacts are protected with SHA-256, size and mtime snapshots. Phase 19A latency is generator-only, never full-RAG latency.
