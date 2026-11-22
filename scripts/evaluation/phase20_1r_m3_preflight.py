"""Verify and smoke-test the exact local Phase 20.1R M3 GGUF artifact."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/evaluation/final_model_selection/phase20_1R"
MODEL = "hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M"
EXPECTED_BASE = "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"
REPO = "bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF"
REVISION = "935d400c2ed1a29cc2a1045df25ec7998fb4dfe4"
FILENAME = "DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tags = requests.get("http://127.0.0.1:11434/api/tags", timeout=20).json().get("models", [])
    model = next((r for r in tags if r.get("name") == MODEL), None)
    timestamp = datetime.now(timezone.utc).isoformat()
    if not model:
        atomic_json(OUT / "M3_runtime_preflight.json", {"model": MODEL, "status": "blocked_model_not_imported", "completed_at_utc": timestamp})
        return 2
    show = requests.post("http://127.0.0.1:11434/api/show", json={"model": MODEL, "verbose": True}, timeout=120).json()
    model_info = show.get("model_info", {})
    manifest_root = Path.home() / ".ollama" / "models" / "manifests"
    candidates = []
    for p in manifest_root.rglob("*"):
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("schemaVersion") == 2 and sha_file(p) == model.get("digest"):
            candidates.append((p, data))
    manifest_path = candidates[0][0] if candidates else None
    manifest_data = candidates[0][1] if candidates else None
    weight_layer = next((layer for layer in (manifest_data or {}).get("layers", []) if layer.get("mediaType") == "application/vnd.ollama.image.model"), None)
    blob_path = (Path.home() / ".ollama" / "models" / "blobs" / f"sha256-{weight_layer['digest'].split(':', 1)[-1]}") if weight_layer else None
    artifact_hash = sha_file(blob_path) if blob_path and blob_path.is_file() else None
    gguf_source = next((str(value) for key, value in model_info.items() if key.startswith("general.base_model")), None)
    tokenizer = {key: value for key, value in model_info.items() if key.startswith("tokenizer.ggml.") and key not in {"tokenizer.ggml.merges", "tokenizer.ggml.tokens", "tokenizer.ggml.scores", "tokenizer.ggml.token_type"}}
    tokenizer_sha = hashlib.sha256(json.dumps(tokenizer, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    template = show.get("template", "")
    acquisition = {
        "candidate_id": "M3",
        "candidate_model": EXPECTED_BASE,
        "source_repository": REPO,
        "source_repository_url": f"https://huggingface.co/{REPO}",
        "repository_revision": REVISION,
        "revision_resolution": "Hugging Face repository HEAD observed at the pinned commit on the source tree; Ollama hf.co resolver did not expose the resolved commit, so the downloaded bytes are additionally locked by SHA-256.",
        "revision_pinned_by_runtime_pull": False,
        "base_model_source": gguf_source or EXPECTED_BASE,
        "file_name": FILENAME,
        "file_size_bytes": weight_layer.get("size") if weight_layer else None,
        "artifact_size_bytes": weight_layer.get("size") if weight_layer else None,
        "artifact_sha256": artifact_hash,
        "layer_sha256_expected": weight_layer.get("digest", "").split(":", 1)[-1] if weight_layer else None,
        "artifact_sha_matches_layer_digest": bool(artifact_hash and weight_layer and artifact_hash == weight_layer["digest"].split(":", 1)[-1]),
        "ollama_runtime_name": MODEL,
        "ollama_digest": model.get("digest"),
        "ollama_manifest_path": str(manifest_path) if manifest_path else None,
        "ollama_manifest_sha256": sha_file(manifest_path) if manifest_path else None,
        "quantization": model.get("details", {}).get("quantization_level"),
        "architecture": model_info.get("general.architecture"),
        "parameter_count": model_info.get("general.parameter_count"),
        "native_context_length": model_info.get("llama.context_length"),
        "license_metadata": model_info.get("general.license"),
        "gguf_metadata": {k: v for k, v in model_info.items() if k.startswith("general.") or k in {"llama.context_length", "llama.embedding_length", "llama.block_count", "llama.vocab_size"}},
        "tokenizer_metadata": tokenizer,
        "tokenizer_metadata_sha256": tokenizer_sha,
        "chat_template": template,
        "chat_template_sha256": hashlib.sha256(template.encode("utf-8")).hexdigest(),
        "local_cache_location": str(blob_path) if blob_path else None,
        "ollama_runtime_version": requests.get("http://127.0.0.1:11434/api/version", timeout=10).json().get("version"),
        "acquired_at_utc": timestamp,
    }
    atomic_json(OUT / "M3_acquisition_manifest.json", acquisition)

    schema = json.loads((ROOT / "schemas/generation_output_v2.schema.json").read_text(encoding="utf-8"))
    # Distilled reasoning models can spend a small smoke-test budget on their
    # internal <think> segment before emitting the requested final structure.
    # Keep one fixed preflight budget across all three technical checks.
    options = {"temperature": 0, "top_p": 1, "seed": 15015, "num_predict": 1024, "num_ctx": 8192}
    tests = [
        ("simple_generation", "Return only the word ready.", None),
        ("generation_v2_schema", "Use Evidence C1: 2 plus 2 equals 4. Answer the question 'What is 2 plus 2?' with status answered and citation C1.", schema),
        ("context_8192", ("Use only this evidence: C1 states that a marker word is reef. Return a concise answer with citation C1. Padding note: " + "Neutral aquaculture context capacity smoke text. " * 500), schema),
    ]
    smoke_rows = []
    for test_id, user_text, format_schema in tests:
        payload = {"model": MODEL, "messages": [{"role": "user", "content": user_text}], "stream": False, "options": options}
        if format_schema is not None:
            payload["format"] = format_schema
        started = time.perf_counter()
        try:
            response = requests.post("http://127.0.0.1:11434/api/chat", json=payload, timeout=1800)
            response.raise_for_status()
            body = response.json()
            content = body.get("message", {}).get("content", "")
            parsed = None
            schema_ok = None
            parse_error = None
            if format_schema is not None:
                try:
                    parsed = json.loads(content)
                    schema_ok = (
                        set(parsed) == {"question_id", "status", "answer", "citations"}
                        and isinstance(parsed["question_id"], str)
                        and parsed["status"] in {"answered", "insufficient_evidence"}
                        and isinstance(parsed["answer"], str)
                        and isinstance(parsed["citations"], list)
                        and all(isinstance(c, str) and c.startswith("C") for c in parsed["citations"])
                    )
                except Exception as exc:
                    parse_error = f"{type(exc).__name__}: {exc}"
                    schema_ok = False
            smoke_rows.append({"test_id": test_id, "status": "pass" if schema_ok is not False and body.get("done_reason") != "length" else "fail", "output": content, "parsed": parsed, "schema_valid": schema_ok, "parse_error": parse_error, "done_reason": body.get("done_reason"), "prompt_eval_count": body.get("prompt_eval_count"), "eval_count": body.get("eval_count"), "duration_seconds": time.perf_counter()-started, "num_ctx": options["num_ctx"], "num_predict": options["num_predict"]})
        except Exception as exc:
            smoke_rows.append({"test_id": test_id, "status": "technical_failure", "error": f"{type(exc).__name__}: {exc}", "duration_seconds": time.perf_counter()-started})

    runtime_ok = len(smoke_rows) == 3 and all(r.get("status") == "pass" for r in smoke_rows)
    manifest_integrity = bool(artifact_hash and acquisition["artifact_sha_matches_layer_digest"])
    result = {
        "model": MODEL,
        "ollama_digest": model.get("digest"),
        "architecture": acquisition["architecture"],
        "base_model_metadata": gguf_source,
        "quantization": acquisition["quantization"],
        "artifact_integrity_pass": manifest_integrity,
        "runtime_smoke_pass": all(r.get("status") == "pass" for r in smoke_rows[:1]),
        "generation_v2_schema_smoke_pass": smoke_rows[1].get("status") == "pass",
        "context_8192_smoke_pass": smoke_rows[2].get("status") == "pass",
        "smoke_tests": smoke_rows,
        "m3_ready": bool(manifest_integrity and acquisition["architecture"] == "llama" and acquisition["quantization"] == "Q4_K_M" and (gguf_source == EXPECTED_BASE or gguf_source is None) and runtime_ok),
        "revision_pinned_by_runtime_pull": acquisition["revision_pinned_by_runtime_pull"],
        "revision_limitation": "The Ollama hf.co import path does not expose a pinned repository commit; file SHA-256 and GGUF lineage are recorded as the exact local artifact identity.",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(OUT / "M3_runtime_preflight.json", result)
    return 0 if result["m3_ready"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
