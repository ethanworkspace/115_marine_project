"""Fixed, local Ollama generation client for Phase 15."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests


OLLAMA_BASE_URL = "http://127.0.0.1:11434"
GENERATION_OPTIONS = {
    "temperature": 0,
    "top_p": 1.0,
    "seed": 15015,
    "num_predict": 768,
    "num_ctx": 8192,
}
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["question_id", "status", "answer", "citations"],
    "properties": {
        "question_id": {"type": "string"},
        "status": {"type": "string", "enum": ["answered", "insufficient_evidence"]},
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["context_id", "chunk_id", "document_id", "page"],
                "properties": {
                    "context_id": {"type": "string"},
                    "chunk_id": {"type": "string"},
                    "document_id": {"type": "string"},
                    "page": {"type": "integer", "minimum": 1},
                },
            },
        },
    },
}


class LocalGenerationError(RuntimeError):
    pass


def load_generation_prompt(root: Path) -> str:
    path = root / "prompts/generation_v1.txt"
    prompt = path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("Generation v1 prompt is empty")
    return prompt


def call_ollama(*, model: str, system_prompt: str, user_prompt: str, base_url: str = OLLAMA_BASE_URL,
                timeout: int = 900,
                session: requests.Session | None = None) -> dict[str, Any]:
    """Stream one structured response from loopback Ollama and capture runtime counters."""
    client = session or requests.Session()
    request_body = {
        "model": model,
        "stream": True,
        "format": OUTPUT_SCHEMA,
        "keep_alive": "30m",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": dict(GENERATION_OPTIONS),
    }
    start = time.perf_counter()
    first_token_seconds: float | None = None
    content_parts: list[str] = []
    final_event: dict[str, Any] = {}
    try:
        with client.post(f"{base_url.rstrip('/')}/api/chat", json=request_body, timeout=timeout, stream=True) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                event = json.loads(raw_line)
                message = event.get("message") or {}
                delta = message.get("content") or ""
                if delta:
                    if first_token_seconds is None:
                        first_token_seconds = time.perf_counter() - start
                    content_parts.append(str(delta))
                if event.get("done"):
                    final_event = event
    except Exception as exc:
        raise LocalGenerationError(f"local Ollama request failed: {type(exc).__name__}: {exc}") from exc
    elapsed = time.perf_counter() - start
    raw_output = "".join(content_parts)
    if not raw_output:
        raise LocalGenerationError("Ollama returned no message content")
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise LocalGenerationError(f"Ollama response was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise LocalGenerationError("Ollama response JSON was not an object")
    return {
        "raw_output": raw_output,
        "parsed": parsed,
        "latency_seconds": elapsed,
        "ttft_seconds": first_token_seconds,
        "prompt_tokens": final_event.get("prompt_eval_count"),
        "completion_tokens": final_event.get("eval_count"),
        "tokens_per_second": (
            final_event.get("eval_count") / (final_event.get("eval_duration", 0) / 1e9)
            if final_event.get("eval_count") is not None and final_event.get("eval_duration")
            else None
        ),
        "load_duration_ns": final_event.get("load_duration"),
        "done_reason": final_event.get("done_reason"),
    }
