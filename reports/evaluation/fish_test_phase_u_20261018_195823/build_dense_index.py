from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests

OUT = Path(__file__).resolve().parent
CORPUS = OUT / "corpus_v3"
CHUNKS = CORPUS / "corpus_chunks_v3.jsonl"
MANIFEST = CORPUS / "corpus_v3_manifest.json"
VECTORS = CORPUS / "dense_vectors.f32"
CHECKPOINT = CORPUS / "dense_embedding_checkpoint.json"
OLLAMA = "http://127.0.0.1:11434"
MODEL = "bge-m3:latest"
EXPECTED_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"
BATCH = 24
DIMENSIONS = 1024


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_chunks() -> list[dict[str, Any]]:
    return [json.loads(x) for x in CHUNKS.read_text(encoding="utf-8").splitlines() if x.strip()]


def verify_model() -> dict[str, Any]:
    tags = requests.get(f"{OLLAMA}/api/tags", timeout=15)
    tags.raise_for_status()
    data = tags.json()
    matches = [m for m in data.get("models", []) if m.get("name") == MODEL]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one Ollama tag for {MODEL}; found {len(matches)}")
    digest = matches[0].get("digest")
    if digest != EXPECTED_DIGEST:
        raise RuntimeError(f"Embedding model digest mismatch: expected {EXPECTED_DIGEST}, got {digest}")
    show = requests.post(f"{OLLAMA}/api/show", json={"model": MODEL}, timeout=30)
    show.raise_for_status()
    details = show.json()
    model_info = details.get("model_info", {})
    if model_info.get("general.architecture") not in {"bert", "bge"}:
        raise RuntimeError(f"Unexpected embedding model architecture: {model_info.get('general.architecture')}")
    return {"model": MODEL, "digest": digest, "expected_digest": EXPECTED_DIGEST, "architecture": model_info.get("general.architecture"), "parameter_size": matches[0].get("details", {}).get("parameter_size"), "quantization_level": matches[0].get("details", {}).get("quantization_level"), "embedding_length": model_info.get("bert.embedding_length"), "verified_via": "local Ollama /api/tags and /api/show"}


def embed_batch(texts: list[str]) -> np.ndarray:
    last_error = None
    for attempt in range(1, 4):
        try:
            r = requests.post(
                f"{OLLAMA}/api/embed",
                json={"model": MODEL, "input": texts, "truncate": False, "keep_alive": "30m"},
                timeout=300,
            )
            r.raise_for_status()
            embeddings = np.asarray(r.json().get("embeddings"), dtype=np.float32)
            if embeddings.shape != (len(texts), DIMENSIONS):
                raise RuntimeError(f"Unexpected embedding shape {embeddings.shape}; expected {(len(texts), DIMENSIONS)}")
            if not np.isfinite(embeddings).all():
                raise RuntimeError("Embedding response contains NaN/Inf")
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            if np.any(norms <= 0):
                raise RuntimeError("Embedding response has a zero-norm vector")
            return embeddings / norms
        except Exception as e:  # bounded retries; checkpoint remains authoritative
            last_error = e
            if attempt < 3:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Embedding batch failed after 3 attempts: {last_error}")


def main() -> None:
    started = time.perf_counter()
    model = verify_model()
    manifest = read_json(MANIFEST)
    all_chunks = read_chunks()
    docs = [x for x in all_chunks if x["retrieval_eligible"]]
    if len(docs) != manifest["retrieval_eligible_chunk_count"]:
        raise RuntimeError("Retrieval-eligible count differs from corpus manifest")
    if not docs or any("text" not in x or not x["text"] for x in docs):
        raise RuntimeError("Eligible corpus contains empty text")
    texts = [x["text"] for x in docs]
    ids = [x["chunk_id"] for x in docs]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate chunk IDs in retrieval corpus")
    corpus_digest = sha(CHUNKS)
    total = len(docs)
    if CHECKPOINT.exists():
        cp = read_json(CHECKPOINT)
        if cp.get("corpus_chunk_jsonl_sha256") != corpus_digest or cp.get("model_digest") != model["digest"] or cp.get("total_vectors") != total:
            raise RuntimeError("Existing dense checkpoint is incompatible with this corpus/model")
        start = int(cp.get("next_index", 0))
        if not VECTORS.exists() or VECTORS.stat().st_size != total * DIMENSIONS * 4:
            raise RuntimeError("Dense vector file is missing or has an unexpected size")
    else:
        start = 0
        with VECTORS.open("wb") as f:
            f.truncate(total * DIMENSIONS * 4)
        write = np.memmap(VECTORS, dtype=np.float32, mode="r+", shape=(total, DIMENSIONS))
        write.flush()
        del write
        CHECKPOINT.write_text(json.dumps({"status": "RUNNING", "next_index": 0, "total_vectors": total, "dimensions": DIMENSIONS, "normalization": "L2", "corpus_chunk_jsonl_sha256": corpus_digest, "model_digest": model["digest"], "updated_at_utc": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
    vectors = np.memmap(VECTORS, dtype=np.float32, mode="r+", shape=(total, DIMENSIONS))
    batch_count = (total + BATCH - 1) // BATCH
    for i in range(start, total, BATCH):
        batch = embed_batch(texts[i:i+BATCH])
        vectors[i:i+len(batch)] = batch
        if ((i // BATCH) + 1) % 10 == 0 or i + len(batch) == total:
            vectors.flush()
            next_index = i + len(batch)
            cp = {"status": "RUNNING" if next_index < total else "COMPLETE", "next_index": next_index, "total_vectors": total, "dimensions": DIMENSIONS, "batch_size": BATCH, "batch_count": batch_count, "normalization": "L2", "corpus_chunk_jsonl_sha256": corpus_digest, "model": model, "model_digest": model["digest"], "updated_at_utc": datetime.now(timezone.utc).isoformat()}
            CHECKPOINT.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"embedded": next_index, "total": total, "percent": round(next_index*100/total, 2)}, ensure_ascii=False), flush=True)
    vectors.flush()
    del vectors
    vector_sha = sha(VECTORS)
    # Try to release the model from Ollama after the embedding phase.
    try:
        requests.post(f"{OLLAMA}/api/embed", json={"model": MODEL, "input": ["release model"], "keep_alive": "0s"}, timeout=60).raise_for_status()
    except Exception:
        pass
    manifest["embedding_index"] = {
        "status": "BUILT",
        "model": MODEL,
        "model_digest": model["digest"],
        "dimensions": DIMENSIONS,
        "normalization": "L2",
        "eligible_chunk_count": total,
        "context_only_not_embedded_count": len(all_chunks)-total,
        "vector_file": str(VECTORS.relative_to(OUT)).replace("\\", "/"),
        "vector_file_bytes": VECTORS.stat().st_size,
        "vector_file_sha256": vector_sha,
        "matrix_row_order": "corpus_chunks_v3.jsonl filtered by retrieval_eligible, stable source_id/record_locator/chunk_id order",
        "matrix_order_ids_sha256": hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.perf_counter()-started, 3),
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"status": "BUILT", "model_digest": model["digest"], "eligible_vectors": total, "vector_sha256": vector_sha, "wall_seconds": round(time.perf_counter()-started, 2)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
