"""Local, evaluation-only cross-encoder runtime for the frozen Phase 14 study."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


MODEL_ID = "BAAI/bge-reranker-v2-m3"
DEFAULT_MAX_LENGTH = 512
DEFAULT_BATCH_SIZE = 4


@dataclass(frozen=True)
class RerankerLoadInfo:
    model_id: str
    model_path: str
    device: str
    dtype: str
    max_sequence_length: int
    batch_size: int
    tokenizer_class: str
    tokenizer_is_fast: bool
    model_class: str
    model_load_seconds: float
    parameter_count: int


class CrossEncoderRuntime:
    """Score only `(query, child-chunk text)` pairs with a pinned local model."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        device: str,
        max_length: int = DEFAULT_MAX_LENGTH,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if max_length <= 0 or batch_size <= 0:
            raise ValueError("max_length and batch_size must be positive")
        self.model_path = Path(model_path).resolve()
        if not self.model_path.is_dir():
            raise FileNotFoundError(f"Local reranker snapshot does not exist: {self.model_path}")
        for required in ("config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json"):
            if not (self.model_path / required).is_file():
                raise FileNotFoundError(f"Required model artifact is absent: {self.model_path / required}")

        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.device = device
        self.max_length = max_length
        self.batch_size = batch_size
        started = time.perf_counter()
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_path,
            local_files_only=True,
            use_fast=True,
        )
        if not self.tokenizer.is_fast:
            raise RuntimeError("The pinned tokenizer.json fast tokenizer was not selected")
        self.model = AutoModelForSequenceClassification.from_pretrained(
            self.model_path,
            local_files_only=True,
            use_safetensors=True,
        )
        self.model.to(device=device, dtype=torch.float32)
        self.model.eval()
        if self.model.config.model_type != "xlm-roberta":
            raise RuntimeError(f"Unexpected model architecture: {self.model.config.model_type}")
        if str(self.model.config._name_or_path).startswith("Oracle/"):
            raise RuntimeError("A model other than the requested BAAI checkpoint was loaded")
        if hasattr(torch, "cuda") and str(device).startswith("cuda"):
            torch.cuda.synchronize()
        load_seconds = time.perf_counter() - started
        self.load_info = RerankerLoadInfo(
            model_id=MODEL_ID,
            model_path=str(self.model_path),
            device=device,
            dtype="float32",
            max_sequence_length=max_length,
            batch_size=batch_size,
            tokenizer_class=self.tokenizer.__class__.__name__,
            tokenizer_is_fast=bool(self.tokenizer.is_fast),
            model_class=self.model.__class__.__name__,
            model_load_seconds=load_seconds,
            parameter_count=sum(int(param.numel()) for param in self.model.parameters()),
        )

    def untruncated_token_lengths(self, query: str, passages: Sequence[str]) -> list[int]:
        """Return pair lengths with special tokens before the configured truncation."""
        if not passages:
            return []
        result: list[int] = []
        for start in range(0, len(passages), self.batch_size):
            batch_passages = list(passages[start : start + self.batch_size])
            encoded = self.tokenizer(
                [query] * len(batch_passages),
                batch_passages,
                padding=False,
                truncation=False,
                add_special_tokens=True,
                return_attention_mask=False,
            )
            result.extend(len(ids) for ids in encoded["input_ids"])
        return result

    def score_pairs(self, query: str, passages: Sequence[str]) -> list[float]:
        """Score every passage in order; raw classification logits are retained."""
        if not passages:
            return []
        scores: list[float] = []
        torch = self.torch
        for start in range(0, len(passages), self.batch_size):
            batch_passages = list(passages[start : start + self.batch_size])
            encoded = self.tokenizer(
                [query] * len(batch_passages),
                batch_passages,
                padding="longest",
                truncation="longest_first",
                max_length=self.max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            with torch.inference_mode():
                logits = self.model(**encoded, return_dict=True).logits.reshape(-1).float()
            batch_scores = [float(value) for value in logits.detach().cpu().tolist()]
            if len(batch_scores) != len(batch_passages):
                raise RuntimeError("The reranker returned a different number of scores than input pairs")
            if not all(math.isfinite(value) for value in batch_scores):
                raise RuntimeError("The reranker returned NaN or Inf scores")
            scores.extend(batch_scores)
        if str(self.device).startswith("cuda"):
            torch.cuda.synchronize()
        return scores

    def rerank(self, query: str, candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Resort candidates by score with fixed RRF-rank/chunk-ID tie breaks."""
        candidate_rows = [dict(row) for row in candidates]
        ids = [str(row["chunk_id"]) for row in candidate_rows]
        if len(ids) != len(set(ids)):
            raise ValueError("RRF candidate chunk IDs must be unique")
        scores = self.score_pairs(query, [str(row["text"]) for row in candidate_rows])
        scored = []
        for row, score in zip(candidate_rows, scores, strict=True):
            row["reranker_score"] = score
            scored.append(row)
        scored.sort(
            key=lambda row: (
                -float(row["reranker_score"]),
                int(row.get("rank", row.get("rrf_rank", 10**9))),
                str(row["chunk_id"]),
            )
        )
        for rank, row in enumerate(scored, start=1):
            row["reranker_rank"] = rank
        if {str(row["chunk_id"]) for row in scored} != set(ids):
            raise RuntimeError("Reranking changed candidate identity")
        return scored
