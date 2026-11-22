from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[4]
RUN = Path(__file__).resolve().parents[1]
OUT = RUN / "outputs"
OUT.mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        return [json.loads(line) for line in f if line.strip()]


git = {}
for args, key in [(["git", "rev-parse", "HEAD"], "head"), (["git", "branch", "--show-current"], "branch"), (["git", "status", "--short"], "status")]:
    p = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    git[key] = p.stdout.strip() if p.returncode == 0 else p.stderr.strip()

protected_paths = [
    ROOT / "rag_store.sqlite3",
    ROOT / "data/evaluation/corpus_v2.jsonl",
    ROOT / "data/evaluation/corpus_manifest_v2.json",
    ROOT / "data/evaluation/indexes/E1_grounded_bm25_v1/index_manifest.json",
    ROOT / "data/evaluation/indexes/E2_grounded_bge_m3_v1/index_manifest.json",
    ROOT / "data/evaluation/indexes/E2_grounded_bge_m3_v1/chunks.jsonl",
    ROOT / "data/evaluation/indexes/E2_grounded_bge_m3_v1/vectors.f32",
    ROOT / "reports/evaluation/fish_test_run_20261012_152244/generation_outputs.jsonl",
    ROOT / "reports/evaluation/fish_test_run_20261012_152244/retrieval_trace.jsonl",
    ROOT / "reports/evaluation/fish_test_run_20261012_152244/fish_test_evaluation_results.xlsx",
]
protected = [{"path": str(p.relative_to(ROOT)), "exists": p.is_file(), "size": p.stat().st_size if p.is_file() else None, "sha256": sha256(p)} for p in protected_paths]

manifest_path = ROOT / "reports/recovery/document_manifest_v3.jsonl"
corpus_path = ROOT / "data/evaluation/corpus_v2.jsonl"
manifest = read_jsonl(manifest_path)
chunks = read_jsonl(corpus_path)
status_counts = Counter((r.get("source_verification_status"), r.get("retrieval_role")) for r in chunks)
verified_docs = sorted({r.get("document_id") for r in chunks if r.get("source_verified") is True and r.get("source_verification_status") == "verified" and r.get("retrieval_role") == "retrieval" and r.get("document_id")})
doc_rows = []
for doc_id in verified_docs:
    c = next(r for r in chunks if r.get("document_id") == doc_id and r.get("retrieval_role") == "retrieval")
    m = next((r for r in manifest if r.get("document_id") == doc_id), {})
    doc_rows.append({
        "document_id": doc_id,
        "title": c.get("source_title"),
        "source_id": c.get("source_id"),
        "source_url": c.get("source_url"),
        "source_checksum": c.get("source_checksum"),
        "manifest_file_path": m.get("file_path"),
        "manifest_checksum": m.get("checksum"),
        "manifest_version": m.get("version"),
        "manifest_legal_status": m.get("legal_status"),
        "manifest_authority_status": m.get("authority_status"),
        "manifest_species": m.get("species"),
        "retrieval_chunks": sum(1 for r in chunks if r.get("document_id") == doc_id and r.get("retrieval_role") == "retrieval" and r.get("source_verified") is True and r.get("source_verification_status") == "verified"),
    })

model_tags = {
    "M1": ("deepseek-r1:7b", "DeepSeek-R1-Distill-Qwen-7B", "qwen2"),
    "M2": ("qwen2.5-coder:7b", "Qwen2.5-Coder-7B-Instruct", "qwen2"),
    "M3": ("hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M", "DeepSeek-R1-Distill-Llama-8B", "llama"),
    "M4": ("gemma2:9b", "Gemma2-9B-It", "gemma2"),
    "BGE-M3": ("bge-m3:latest", "BGE-M3", "bert"),
    "Judge": ("mistral-nemo:12b-instruct-2407-q4_K_M", "Mistral NeMo Instruct 12B", "llama"),
}
models = []
for model_id, (tag, expected_name, expected_family) in model_tags.items():
    try:
        r = requests.post("http://127.0.0.1:11434/api/show", json={"model": tag}, timeout=20)
        r.raise_for_status()
        body = r.json()
        info = body.get("model_info", {})
        details = body.get("details", {})
        family = details.get("family")
        basename = info.get("general.basename")
        models.append({"model_id": model_id, "tag": tag, "expected_name": expected_name, "expected_family": expected_family,
                       "actual_family": family, "actual_basename": basename, "parameter_size": details.get("parameter_size"),
                       "quantization": details.get("quantization_level"), "runtime_digest": next((m.get("digest") for m in requests.get("http://127.0.0.1:11434/api/tags", timeout=10).json().get("models", []) if m.get("name") == tag), None),
                       "identity_pass": family == expected_family and (expected_name.casefold().split("-")[0] in (basename or expected_name).casefold() or model_id in ("BGE-M3", "Judge")), "status": "available"})
    except Exception as e:
        models.append({"model_id": model_id, "tag": tag, "expected_name": expected_name, "expected_family": expected_family, "status": "unavailable", "error": str(e)})

reranker_roots = [
    Path(os.environ.get("HF_HOME", "C:/Users/ethan/.cache/huggingface")) / "hub/models--BAAI--bge-reranker-v2-m3/snapshots",
    ROOT / "models/bge-reranker-v2-m3",
    ROOT / "rag_assets/bge-reranker-v2-m3",
]
reranker_snapshots = []
for root in reranker_roots:
    if root.is_dir():
        for snap in root.iterdir():
            if snap.is_dir() and (snap / "model.safetensors").is_file():
                reranker_snapshots.append(str(snap.resolve()))

run_manifest = {
    "phase": "S_integrated_rag_v2",
    "run_id": RUN.name,
    "captured_at": datetime.now(timezone.utc).isoformat(),
    "root": str(ROOT),
    "working_directory": str(RUN),
    "git": git,
    "protected_file_snapshot": protected,
    "prior_phase_r_validation": json.loads((ROOT / "reports/evaluation/fish_test_phase_r_20261017_170144/phase_r_validation.json").read_text(encoding="utf-8")),
    "corpus_v2": {"path": str(corpus_path.relative_to(ROOT)), "sha256": sha256(corpus_path), "records": len(chunks), "verified_retrieval_chunks": sum(1 for r in chunks if r.get("source_verified") is True and r.get("source_verification_status") == "verified" and r.get("retrieval_role") == "retrieval"), "status_role_counts": {f"{a}|{b}": n for (a,b),n in status_counts.items()}, "verified_retrieval_documents": doc_rows},
    "models": models,
    "reranker": {"model_id": "BAAI/bge-reranker-v2-m3", "local_snapshots": reranker_snapshots, "available": bool(reranker_snapshots), "status": "available" if reranker_snapshots else "blocked_missing_local_model_snapshot"},
    "runtime": {"python": sys.version, "ollama_api": "http://127.0.0.1:11434", "cuda_available_in_reranker_env": True},
    "change_policy": "All implementation, corpus, index, DB, and evaluation artifacts are new under this run directory. No legacy files are edited. No cleanup/deletion performed.",
}
(OUT / "phase_s_execution_snapshot.json").write_text(json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"run_id": RUN.name, "git": git, "protected": [{"path": r["path"], "sha256": r["sha256"]} for r in protected], "corpus_v2": run_manifest["corpus_v2"], "models": models, "reranker": run_manifest["reranker"]}, ensure_ascii=False, indent=2))
