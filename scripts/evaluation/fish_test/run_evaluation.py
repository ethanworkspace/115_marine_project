from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.evaluation.generation.frozen import read_jsonl, sha256_file, validate_frozen_inputs

API = "http://127.0.0.1:11434"
QUESTION_FILE = ROOT / "reports/evaluation/fish_test_phase_a_20261012/fish_test_questions_normalized.jsonl"
PHASE_A_DIR = ROOT / "reports/evaluation/fish_test_phase_a_20261012"
PROTECTED_MANIFEST = ROOT / "reports/evaluation/final_model_selection/phase20/protected_inputs_before.json"
SQLITE_PATH = ROOT / "rag_store.sqlite3"
EXPECTED_SQLITE_SHA256 = "d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087"
EXPECTED_CORPUS_SHA256 = "540a7dfa641fdbf9c2246feea75a226ade41a8e85d5c995fa5b3c8514aa03162"
EXPECTED_RERANKER_REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
EXPECTED_BGE_DIGEST = "7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab"

MODEL_SPECS = [
    {"model_id": "M1", "label": "DeepSeek-R1-Distill-Qwen-7B", "tag": "deepseek-r1:7b", "family": "qwen2", "digest": "755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f"},
    {"model_id": "M2", "label": "Qwen2.5-Coder-7B-Instruct", "tag": "qwen2.5-coder:7b", "family": "qwen2", "digest": "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364"},
    {"model_id": "M3", "label": "DeepSeek-R1-Distill-Llama-8B", "tag": "hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M", "family": "llama", "digest": "aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42"},
    {"model_id": "M4", "label": "Gemma2-9B-It", "tag": "gemma2:9b", "family": "gemma2", "digest": "ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b"},
]
JUDGE_SPEC = {"label": "Mistral NeMo Instruct 12B", "tag": "mistral-nemo:12b-instruct-2407-q4_K_M", "digest": "daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55", "family": "llama"}
EMBED_SPEC = {"tag": "bge-m3:latest", "digest": EXPECTED_BGE_DIGEST}
OPTIONS = {"temperature": 0, "top_p": 1.0, "seed": 15015, "num_predict": 1024, "num_ctx": 8192}
JUDGE_OPTIONS = {"temperature": 0, "top_p": 1.0, "seed": 15015, "num_predict": 512, "num_ctx": 8192}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "object", "properties": {"context_id": {"type": "string"}, "quote": {"type": "string"}}, "required": ["context_id", "quote"], "additionalProperties": False}},
        "uncertainty": {"type": "string"},
    },
    "required": ["answer", "citations", "uncertainty"],
    "additionalProperties": False,
}
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "faithfulness": {"type": "number", "minimum": 0, "maximum": 1},
        "answer_relevance": {"type": "number", "minimum": 0, "maximum": 1},
        "context_sufficient": {"type": "boolean"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
    "required": ["faithfulness", "answer_relevance", "context_sufficient", "unsupported_claims", "rationale"],
    "additionalProperties": False,
}
SYSTEM_PROMPT = (
    "你是水產養殖問答助理。僅使用本題提供的檢索 Context，不得使用外部知識補足。"
    "若 Context 不足以支持答案，請明確說明不足或不確定。使用繁體中文。"
    "依指定 JSON Schema 輸出答案與可定位的 Context 引用；不要輸出 Schema 以外文字。"
)


def now_local() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def canonical_sha(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def jsonl_read(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return read_jsonl(path)


def http_json(endpoint: str, payload: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(API + endpoint, data=data, method="POST" if payload is not None else "GET")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read())
    if not isinstance(value, dict):
        raise ValueError(f"{endpoint} returned non-object JSON")
    return value


def protect_baseline() -> dict[str, Any]:
    manifest = json.loads(PROTECTED_MANIFEST.read_text(encoding="utf-8"))
    entries = manifest.get("files", [])
    errors: list[dict[str, Any]] = []
    matches = 0
    checked = 0
    for entry in entries:
        relative = str(entry.get("path", ""))
        path = ROOT / relative
        if not relative or not path.is_file():
            errors.append({"path": relative, "status": "missing"})
            continue
        try:
            actual = sha256_file(path)
            actual_size = path.stat().st_size
            checked += 1
            ok = actual == entry.get("sha256") and actual_size == entry.get("size_bytes")
            matches += int(ok)
            if not ok:
                errors.append({"path": relative, "status": "mismatch", "expected_sha256": entry.get("sha256"), "actual_sha256": actual, "expected_size": entry.get("size_bytes"), "actual_size": actual_size})
        except Exception as exc:
            errors.append({"path": relative, "status": "unreadable", "exception_type": type(exc).__name__, "message": str(exc)})
    sqlite_sha = sha256_file(SQLITE_PATH) if SQLITE_PATH.is_file() else None
    return {"expected_count": 636, "manifest_count": len(entries), "checked_count": checked, "matching_count": matches, "mismatches": errors, "complete": len(entries) == 636 and checked == 636 and matches == 636 and not errors, "sqlite_sha256": sqlite_sha, "sqlite_expected_sha256": EXPECTED_SQLITE_SHA256, "sqlite_matches": sqlite_sha == EXPECTED_SQLITE_SHA256}


def source_input_audit(questions: list[dict[str, Any]]) -> dict[str, Any]:
    import csv
    inventory = list(csv.DictReader((PHASE_A_DIR / "fish_test_file_inventory.csv").open("r", encoding="utf-8-sig", newline="")))
    workbooks: dict[str, dict[str, Any]] = {}
    for row in inventory:
        name = row.get("file_name") or row.get("filename")
        if not name or not name.lower().endswith(".xlsx"):
            continue
        workbooks[name] = row
    audit = []
    for name, row in sorted(workbooks.items()):
        path = ROOT / "fish test" / name
        status = "missing"
        actual = None
        if path.is_file():
            actual = sha256_file(path)
            status = "matches_phase_a" if actual == row.get("sha256") else "checksum_mismatch"
        audit.append({"file_name": name, "exists": path.is_file(), "expected_sha256": row.get("sha256"), "actual_sha256": actual, "status": status})
    quality = json.loads((PHASE_A_DIR / "fish_test_data_quality.json").read_text(encoding="utf-8"))
    return {"phase_a_workbook_count": quality.get("workbook_count"), "phase_a_sheet_count": quality.get("sheet_count"), "question_count": len(questions), "unique_question_id_count": len({q.get("question_id") for q in questions}), "workbook_hashes": audit, "all_workbooks_match": len(audit) == 6 and all(r["status"] == "matches_phase_a" for r in audit), "phase_a_duplicate_groups": quality.get("exact_duplicate_groups", []), "near_duplicate_pair_count": quality.get("suspected_near_duplicate_pair_count"), "candidate_gold_status": "not_independently_approved"}


def validate_models() -> dict[str, Any]:
    version = http_json("/api/version").get("version")
    tags = http_json("/api/tags").get("models", [])
    by_name = {r.get("name"): r for r in tags}
    specs = [{**row, "role": "generator"} for row in MODEL_SPECS] + [{**JUDGE_SPEC, "model_id": "Independent Judge", "role": "judge"}, {**EMBED_SPEC, "model_id": "BGE-M3", "role": "embedding"}]
    results = []
    for spec in specs:
        row = by_name.get(spec["tag"])
        if not row:
            results.append({**spec, "status": "missing_local_tag", "runtime_version": version})
            continue
        shown = http_json("/api/show", {"model": spec["tag"]})
        details = row.get("details") or {}
        info = shown.get("model_info") or {}
        arch = info.get("general.architecture") or details.get("family")
        param_count = info.get(f"{arch}.parameter_count") if arch else None
        result = {**spec, "actual_digest": row.get("digest"), "actual_family": details.get("family"), "architecture": arch, "parameter_count": param_count, "parameter_size": details.get("parameter_size"), "quantization": details.get("quantization_level"), "size_bytes": row.get("size"), "runtime_version": version, "capabilities": shown.get("capabilities", []), "model_info": info}
        if spec["role"] == "embedding":
            result["status"] = "pass" if row.get("digest") == spec["digest"] else "identity_mismatch"
        else:
            result["status"] = "pass" if row.get("digest") == spec["digest"] and arch == spec["family"] else "identity_mismatch"
        if spec.get("model_id") == "M3" and arch != "llama":
            result["status"] = "identity_mismatch"
        results.append(result)
    return {"checked_at": now_local(), "runtime_version": version, "expected_runtime_version": "0.35.0", "runtime_version_matches_historical": version == "0.35.0", "models": results, "all_generator_identities_pass": all(next(r for r in results if r.get("model_id") == spec["model_id"])["status"] == "pass" for spec in MODEL_SPECS), "judge_identity_pass": next(r for r in results if r.get("role") == "judge")["status"] == "pass", "embedding_identity_pass": next(r for r in results if r.get("role") == "embedding")["status"] == "pass", "incorrect_m3_alias": {"tag": "deepseek-r1:8b", "architecture": "qwen3", "used": False}}


class RerankerWorker:
    def __init__(self, run_dir: Path):
        py = ROOT / ".venv-reranker/Scripts/python.exe"
        worker = ROOT / "scripts/phase19b_r2_reranker_worker.py"
        self.stderr_file = (run_dir / "reranker_worker_stderr.log").open("w", encoding="utf-8")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}
        self.process = subprocess.Popen([str(py), "-B", str(worker)], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr_file, text=True, encoding="utf-8", env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.lines: queue.Queue[str | None] = queue.Queue()
        def read_stdout() -> None:
            assert self.process.stdout
            for line in self.process.stdout:
                self.lines.put(line)
            self.lines.put(None)
        self.reader = threading.Thread(target=read_stdout, daemon=True)
        self.reader.start()
        self.info = self.receive()
        if not self.info.get("ready"):
            raise RuntimeError("Reranker worker preflight failed: " + json.dumps(self.info, ensure_ascii=False)[:2000])

    def receive(self) -> dict[str, Any]:
        try:
            line = self.lines.get(timeout=900)
        except queue.Empty as exc:
            raise TimeoutError("Reranker worker timed out") from exc
        if line is None:
            raise RuntimeError("Reranker worker exited unexpectedly")
        return json.loads(line)

    def call(self, payload: dict[str, Any]) -> Any:
        assert self.process.stdin
        self.process.stdin.write(json.dumps(payload, ensure_ascii=True) + "\n")
        self.process.stdin.flush()
        reply = self.receive()
        if not reply.get("ok"):
            raise RuntimeError("Reranker operation failed: " + json.dumps(reply, ensure_ascii=False)[:2000])
        return reply["value"]

    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.call({"operation": "rerank", "query": query, "candidates": candidates})

    def close(self) -> None:
        try:
            if self.process.poll() is None and self.process.stdin:
                self.process.stdin.write(json.dumps({"operation": "close"}) + "\n")
                self.process.stdin.flush()
                self.process.wait(timeout=30)
        except Exception:
            self.process.terminate()
            self.process.wait(timeout=15)
        self.stderr_file.close()


class HardwareSampler:
    def __init__(self, run_dir: Path, interval: float = 1.0):
        self.run_dir = run_dir
        self.interval = interval
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self.phase = "idle"
        self.identity: dict[str, Any] = {}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        script = r"$ErrorActionPreference='Stop'; while($true){try{$c=(Get-Counter '\GPU Adapter Memory(*)\Shared Usage' -ErrorAction Stop).CounterSamples; $a=@($c|ForEach-Object{@{path=$_.Path;value_bytes=[long]$_.CookedValue}}); @{timestamp=(Get-Date).ToUniversalTime().ToString('o');samples=$a;error=$null}|ConvertTo-Json -Compress -Depth 5}catch{@{timestamp=(Get-Date).ToUniversalTime().ToString('o');samples=@();error=$_.Exception.Message}|ConvertTo-Json -Compress -Depth 5}; Start-Sleep -Seconds 1}"
        self.shared_process = subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "+script], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.shared_records: list[dict[str, Any]] = []
        def read_shared() -> None:
            assert self.shared_process.stdout
            for line in self.shared_process.stdout:
                try:
                    item = json.loads(line)
                    item.update({"phase": self.phase, **self.identity})
                    self.shared_records.append(item)
                except Exception as exc:
                    self.errors.append("shared_counter_parse: " + str(exc))
        self.shared_thread = threading.Thread(target=read_shared, daemon=True)
        self.shared_thread.start()

    @staticmethod
    def _ram_used() -> int:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError("GlobalMemoryStatusEx failed")
        return int(status.ullTotalPhys - status.ullAvailPhys)

    @staticmethod
    def _gpu() -> list[dict[str, Any]]:
        output = subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"], text=True, timeout=5)
        result = []
        for line in output.strip().splitlines():
            name, used, total = [x.strip() for x in line.split(",")]
            result.append({"name": name, "dedicated_used_bytes": int(float(used) * 1024 * 1024), "dedicated_total_bytes": int(float(total) * 1024 * 1024)})
        return result

    def sample_once(self) -> dict[str, Any]:
        record = {"timestamp": now_local(), "phase": self.phase, **self.identity}
        try:
            record["system_ram_used_bytes"] = self._ram_used()
        except Exception as exc:
            record["system_ram_error"] = type(exc).__name__ + ": " + str(exc)
        try:
            record["gpu"] = self._gpu()
        except Exception as exc:
            record["gpu_error"] = type(exc).__name__ + ": " + str(exc)
        self.samples.append(record)
        return record

    def _loop(self) -> None:
        while not self.stop.is_set():
            self.sample_once()
            self.stop.wait(self.interval)

    def start(self) -> None:
        self.sample_once()
        self.thread.start()

    def mark(self, phase: str, **identity: Any) -> tuple[int, int]:
        self.phase = phase
        self.identity = identity
        self.sample_once()
        return len(self.samples) - 1, len(self.shared_records)

    def mark_end(self) -> tuple[int, int]:
        self.sample_once()
        return len(self.samples) - 1, len(self.shared_records)

    def finish(self) -> dict[str, Any]:
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join(timeout=10)
        try:
            self.shared_process.terminate()
            self.shared_process.wait(timeout=10)
        except Exception:
            pass
        if self.shared_thread.is_alive():
            self.shared_thread.join(timeout=3)
        with (self.run_dir / "hardware_samples.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for row in self.samples:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        with (self.run_dir / "shared_gpu_memory_samples.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for row in self.shared_records:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        return {"sample_interval_seconds": self.interval, "system_ram_sensor": "Windows GlobalMemoryStatusEx", "dedicated_vram_sensor": "nvidia-smi memory.used/total", "shared_gpu_sensor": "Windows GPU Adapter Memory(*)\\Shared Usage performance counter", "shared_gpu_sample_count": len(self.shared_records), "shared_gpu_adapter_identity": "performance counter adapter LUID; not mapped to a physical GPU name", "sampled_peaks_are_lower_bounds": True, "process_specific_ram": "not_available", "process_specific_vram": "not_available", "errors": self.errors}


def measurement_slice(sampler: HardwareSampler, start_index: tuple[int, int], end_index: tuple[int, int]) -> dict[str, Any]:
    ss, sh = start_index
    es, eh = end_index
    samples = sampler.samples[ss:es + 1]
    shared = sampler.shared_records[sh:eh + 1]
    ram = [r.get("system_ram_used_bytes") for r in samples if isinstance(r.get("system_ram_used_bytes"), int)]
    vram = [g.get("dedicated_used_bytes") for r in samples for g in r.get("gpu", []) if isinstance(g.get("dedicated_used_bytes"), int)]
    shared_values = [x.get("value_bytes") for r in shared for x in r.get("samples", []) if isinstance(x.get("value_bytes"), int)]
    return {"system_ram_peak_bytes_sampled": max(ram) if ram else None, "dedicated_vram_peak_bytes_sampled": max(vram) if vram else None, "shared_gpu_memory_peak_counter_bytes_sampled": max(shared_values) if shared_values else None, "system_ram_sample_count": len(ram), "dedicated_vram_sample_count": len(vram), "shared_gpu_sample_count": len(shared_values), "shared_gpu_scope": "maximum among available GPU Adapter Memory counter instances; LUID not mapped to NVIDIA name" if shared_values else "unavailable", "sampled_peak_is_lower_bound": True}


def prompt_for(question: dict[str, Any], contexts: list[dict[str, Any]]) -> str:
    options = question.get("options") or {}
    option_text = "\n".join(f"{key}. {value}" for key, value in options.items() if value and str(value).strip())
    context_text = "\n\n".join(f"[{c['context_id']}] document={c['document_id']} page={c.get('page')}\n{c['text']}" for c in contexts)
    prompt = f"問題：\n{question['question_text']}"
    if option_text:
        prompt += "\n選項：\n" + option_text
    prompt += "\n\n固定檢索 Context：\n" + context_text
    prompt += "\n\n僅根據以上 Context 作答；需要時指出資料不足。引用請使用 Context ID 和短句。"
    return prompt


def stream_chat(tag: str, system_prompt: str, user_prompt: str, schema: dict[str, Any], options: dict[str, Any], keep_alive: str = "30m") -> dict[str, Any]:
    payload = {"model": tag, "stream": True, "format": schema, "keep_alive": keep_alive, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "options": options}
    request = urllib.request.Request(API + "/api/chat", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    started = time.perf_counter()
    content_parts: list[str] = []
    events: list[dict[str, Any]] = []
    first_content = None
    first_any = None
    done: dict[str, Any] = {}
    error = None
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            while True:
                line = response.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                event = json.loads(line.decode("utf-8"))
                events.append(event)
                message = event.get("message") or {}
                content = message.get("content") or ""
                thinking = message.get("thinking") or ""
                elapsed = time.perf_counter() - started
                if (content or thinking) and first_any is None:
                    first_any = elapsed
                if content:
                    if first_content is None:
                        first_content = elapsed
                    content_parts.append(content)
                if event.get("error"):
                    error = str(event["error"])
                if event.get("done"):
                    done = event
                    break
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
    wall = time.perf_counter() - started
    raw = "".join(content_parts)
    parsed = None
    parse_error = None
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            parse_error = "response_json_not_object"
            parsed = None
    except Exception as exc:
        parse_error = type(exc).__name__ + ": " + str(exc)
    if not error and not done:
        error = "stream_interrupted_or_done_event_missing"
    inline_reasoning = "<think>" in raw or "</think>" in raw
    ttft = None if inline_reasoning else first_content
    eval_count = done.get("eval_count")
    eval_duration = done.get("eval_duration")
    tps = eval_count / (eval_duration / 1e9) if isinstance(eval_count, (int, float)) and isinstance(eval_duration, (int, float)) and eval_duration > 0 else None
    return {"raw_output": raw, "parsed": parsed, "parse_error": parse_error, "execution_error": error, "wall_time_seconds": wall, "ttft_first_any_token_seconds": first_any, "ttft_first_content_token_seconds": ttft, "ttft_inline_reasoning_ambiguous": inline_reasoning, "prompt_eval_count": done.get("prompt_eval_count"), "generated_token_count": eval_count, "generation_duration_ns": eval_duration, "tokens_per_second": tps, "load_duration_ns": done.get("load_duration"), "done_reason": done.get("done_reason"), "stream_event_count": len(events), "stream_events": events, "final_event": done, "request_sha256": canonical_sha(payload)}


def output_schema_valid(value: Any, context_ids: set[str]) -> tuple[bool, bool, list[str]]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return False, False, ["output_not_object"]
    if set(value) != {"answer", "citations", "uncertainty"}:
        errors.append("wrong_or_missing_top_level_keys")
    if not isinstance(value.get("answer"), str):
        errors.append("answer_not_string")
    if not isinstance(value.get("citations"), list):
        errors.append("citations_not_array")
    if not isinstance(value.get("uncertainty"), str):
        errors.append("uncertainty_not_string")
    citation_ids_valid = True
    for i, citation in enumerate(value.get("citations", []) if isinstance(value.get("citations"), list) else []):
        if not isinstance(citation, dict) or set(citation) != {"context_id", "quote"} or not isinstance(citation.get("context_id"), str) or not isinstance(citation.get("quote"), str):
            errors.append(f"citation_{i}_shape_invalid")
            citation_ids_valid = False
        elif citation["context_id"] not in context_ids:
            errors.append(f"citation_{i}_unknown_context_id")
            citation_ids_valid = False
    return not errors, citation_ids_valid, errors


def choose_pilot(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = {
        "虱目魚": ["FT-milkfish-Q01", "FT-milkfish-Q10"],
        "吳郭魚": ["FT-tilapia-Q03", "FT-tilapia-Q14"],
        "石斑魚": ["FT-grouper-Q03", "FT-grouper-Q10"],
        "鱸魚": ["FT-seabass-Q02", "FT-seabass-Q08"],
        "烏魚": ["FT-mullet-Q01", "FT-mullet-Q15"],
        "鰻魚": ["FT-eel-Q01", "FT-eel-Q09"],
    }
    by_id = {str(q.get("question_id")): q for q in questions}
    missing = [qid for ids in wanted.values() for qid in ids if qid not in by_id]
    if missing:
        raise ValueError("Pilot question IDs missing from Phase A: " + ", ".join(missing))
    selected = [by_id[qid] for ids in wanted.values() for qid in ids]
    if len(selected) != 12 or len({q["question_id"] for q in selected}) != 12:
        raise ValueError("Pilot selector did not yield 12 distinct questions")
    return selected


def get_unload(tag: str) -> dict[str, Any]:
    try:
        request = urllib.request.Request(API + "/api/generate", data=json.dumps({"model": tag, "keep_alive": 0}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            active = http_json("/api/ps").get("models", [])
            if not any(row.get("name", row.get("model")) == tag for row in active):
                return {"tag": tag, "unloaded": True, "resident_models": active}
            time.sleep(0.25)
        return {"tag": tag, "unloaded": False, "resident_models": http_json("/api/ps").get("models", [])}
    except Exception as exc:
        return {"tag": tag, "unloaded": False, "error": type(exc).__name__ + ": " + str(exc)}


def make_retrieval_engine(run_dir: Path) -> tuple[Any, Any, Any, Any, dict[str, Any]]:
    from src.evaluation.grounded_baselines import OllamaEmbeddingRuntime, load_dense_index
    from src.evaluation.retrievers.bm25 import EvaluationBM25
    from src.evaluation.silver import _eligible_corpus
    from src.evaluation.rrf import fuse_ranked_lists
    frozen = validate_frozen_inputs(ROOT)
    corpus = _eligible_corpus(frozen["corpus"])
    if len(corpus) != 2224:
        raise RuntimeError(f"Expected 2,224 eligible frozen corpus chunks; got {len(corpus)}")
    corpus_by_id = {str(row["chunk_id"]): row for row in corpus}
    if len(corpus_by_id) != len(corpus):
        raise RuntimeError("Frozen retrieval corpus has duplicate chunk IDs")
    bm25 = EvaluationBM25(corpus, corpus_sha256=frozen["hashes"]["evaluation_corpus_v2_sha256"])
    dense, index_manifest = load_dense_index(ROOT, {"corpus": corpus, "questions": frozen["questions"], "hashes": {"evaluation_corpus_v2": frozen["hashes"]["evaluation_corpus_v2_sha256"]}})
    embed = OllamaEmbeddingRuntime()
    embedding_meta = embed.preflight()
    if embedding_meta.get("model_digest") != EXPECTED_BGE_DIGEST or int(embedding_meta.get("embedding_dimension") or 0) != int(index_manifest.get("embedding_dimension") or 0):
        raise RuntimeError("Live BGE-M3 identity or dimension differs from frozen E2 index")
    reranker = RerankerWorker(run_dir)
    reranker_smoke = reranker.call({"operation": "score", "query": "水產養殖水質管理", "texts": ["水產養殖水質管理與監測內容。"]})
    if len(reranker_smoke) != 1 or not math.isfinite(float(reranker_smoke[0])):
        reranker.close()
        raise RuntimeError("Pinned BGE reranker single-pair smoke failed")
    env = {"corpus_version": "Evaluation Corpus v2", "corpus_sha256": frozen["hashes"]["evaluation_corpus_v2_sha256"], "eligible_chunk_count": len(corpus), "e4_manifest_sha256": frozen["hashes"]["e4_manifest_sha256"], "e4_trace_sha256": frozen["hashes"]["e4_ranking_trace_sha256"], "e4_index_manifest": index_manifest, "embedding_runtime": embedding_meta, "reranker_worker": reranker.info, "reranker_smoke_score": reranker_smoke[0], "retrieval_config": {"bm25_candidates": 50, "dense_candidates": 50, "rrf_k": 60, "reranker": "BAAI/bge-reranker-v2-m3", "reranker_revision": EXPECTED_RERANKER_REVISION, "top_k": 5, "read_only": True}}
    return bm25, dense, embed, reranker, {"frozen": frozen, "corpus": corpus, "corpus_by_id": corpus_by_id, "rrf": fuse_ranked_lists, "environment": env}


def retrieve_one(question: dict[str, Any], bm25: Any, dense: Any, embed: Any, reranker: RerankerWorker, aux: dict[str, Any]) -> dict[str, Any]:
    from array import array
    started = time.perf_counter()
    query = str(question["question_text"])
    bm = bm25.retrieve(query, top_k=50)
    vec = array("f", embed.embed_texts([query], batch_size=32)[0]).tolist()
    dense_hits = dense.rank_vector(vec)[:50]
    fused = aux["rrf"](bm, dense_hits, aux["corpus_by_id"], k=60, top_n=50)
    candidates = []
    for row in fused:
        source = aux["corpus_by_id"][row["chunk_id"]]
        candidates.append({"chunk_id": row["chunk_id"], "document_id": row["document_id"], "page": row["page"], "rank": row["final_rank"], "rrf_rank": row["final_rank"], "rrf_score": row["rrf_score"], "bm25_rank": row["bm25_rank"], "dense_rank": row["dense_rank"], "text": source["text"]})
    ranked = reranker.rerank(query, candidates)
    contexts = []
    for i, candidate in enumerate(ranked[:5], start=1):
        contexts.append({"context_id": f"C{i}", "chunk_id": candidate["chunk_id"], "document_id": candidate["document_id"], "page": candidate.get("page"), "top5_rank": i, "text": candidate["text"], "text_sha256": hashlib.sha256(str(candidate["text"]).encode("utf-8")).hexdigest(), "reranker_score": candidate.get("reranker_score"), "bm25_rank": candidate.get("bm25_rank"), "dense_rank": candidate.get("dense_rank")})
    if len(contexts) != 5:
        raise RuntimeError(f"E4 returned {len(contexts)} contexts, expected exactly 5")
    return {"question_id": question["question_id"], "query": query, "retrieval_config": aux["environment"]["retrieval_config"], "corpus_version": "Evaluation Corpus v2", "corpus_sha256": aux["environment"]["corpus_sha256"], "index_checksum": aux["environment"]["e4_index_manifest"].get("vectors_sha256"), "bm25_top50_chunk_ids": [x.chunk_id for x in bm], "dense_top50_chunk_ids": [x.chunk_id for x in dense_hits], "rrf_top50_chunk_ids": [x["chunk_id"] for x in fused], "contexts": contexts, "context_sha256": canonical_sha([c["text"] for c in contexts]), "context_provenance_sha256": canonical_sha([{k: c[k] for k in ("context_id", "chunk_id", "document_id", "page", "top5_rank", "text_sha256")} for c in contexts]), "retrieval_elapsed_seconds": time.perf_counter() - started, "expected_evidence_mapping": "unavailable; Phase A source fields are candidate metadata without independent chunk/span mapping", "expected_evidence_hit_at_5": None, "retrieval_hit_miss": "not_evaluable_without_verified_expected_chunk_mapping", "support_sufficiency": "pending_independent_judge"}


def generator_phase(rows: list[dict[str, Any]], retraces: dict[str, dict[str, Any]], models: list[dict[str, Any]], run_dir: Path, sampler: HardwareSampler, only_question_ids: set[str] | None = None) -> list[dict[str, Any]]:
    output_path = run_dir / "generation_outputs.jsonl"
    existing = jsonl_read(output_path)
    done_keys = {(r.get("question_id"), r.get("model_id")) for r in existing}
    warmup_path = run_dir / "warmup_results.jsonl"
    warmups = {r.get("model_id") for r in jsonl_read(warmup_path)}
    retrieval_by_id = retraces
    errors: list[dict[str, Any]] = []
    try:
        for model in models:
            model_rows = [q for q in rows if (only_question_ids is None or q["question_id"] in only_question_ids) and (q["question_id"], model["model_id"]) not in done_keys and q["question_id"] in retrieval_by_id]
            if not model_rows and model["model_id"] in warmups:
                continue
            if model["model_id"] not in warmups:
                warm_q = model_rows[0] if model_rows else next(q for q in rows if q["question_id"] in retrieval_by_id)
                warm_prompt = prompt_for(warm_q, retrieval_by_id[warm_q["question_id"]]["contexts"])
                result = stream_chat(model["tag"], SYSTEM_PROMPT, warm_prompt, OUTPUT_SCHEMA, OPTIONS)
                append_jsonl(warmup_path, {"timestamp": now_local(), "model_id": model["model_id"], "model_tag": model["tag"], "model_digest": model["digest"], "warmup_only": True, "scored": False, "response_summary": {k: result.get(k) for k in ("execution_error", "parse_error", "wall_time_seconds", "ttft_first_content_token_seconds", "generated_token_count", "tokens_per_second")}})
                if result.get("execution_error") or result.get("parse_error"):
                    errors.append({"model_id": model["model_id"], "stage": "warmup", "error": result.get("execution_error") or result.get("parse_error")})
                    break
            for question in model_rows:
                qid = question["question_id"]
                contexts = retrieval_by_id[qid]["contexts"]
                prompt = prompt_for(question, contexts)
                key = (qid, model["model_id"])
                record = {"timestamp": now_local(), "question_id": qid, "model_id": model["model_id"], "model_label": model["label"], "model_tag": model["tag"], "model_digest": model["digest"], "context_sha256": retrieval_by_id[qid]["context_sha256"], "system_prompt": SYSTEM_PROMPT, "user_prompt": prompt, "options": OPTIONS, "output_schema": OUTPUT_SCHEMA, "attempts": []}
                result = None
                for attempt in range(1, 3):
                    sampler.phase = "generator"
                    sample_start = sampler.mark("generator", question_id=qid, model_id=model["model_id"], attempt=attempt)
                    result = stream_chat(model["tag"], SYSTEM_PROMPT, prompt, OUTPUT_SCHEMA, OPTIONS)
                    sample_end = sampler.mark_end()
                    result["memory"] = measurement_slice(sampler, sample_start, sample_end)
                    record["attempts"].append({"attempt": attempt, **result})
                    if not result.get("execution_error"):
                        break
                assert result is not None
                parsed = result.get("parsed")
                context_ids = {c["context_id"] for c in contexts}
                valid_schema, valid_citation_ids, schema_errors = output_schema_valid(parsed, context_ids)
                record.update({"raw_output": result.get("raw_output"), "parsed_output": parsed, "parse_error": result.get("parse_error"), "execution_error": result.get("execution_error"), "wall_time_seconds": result.get("wall_time_seconds"), "ttft_first_any_token_seconds": result.get("ttft_first_any_token_seconds"), "ttft_first_content_token_seconds": result.get("ttft_first_content_token_seconds"), "generated_token_count": result.get("generated_token_count"), "generation_duration_ns": result.get("generation_duration_ns"), "tokens_per_second": result.get("tokens_per_second"), "load_duration_ns": result.get("load_duration_ns"), "done_reason": result.get("done_reason"), "stream_event_count": result.get("stream_event_count"), "stream_events": result.get("stream_events"), "final_event": result.get("final_event"), "request_sha256": result.get("request_sha256"), "schema_valid": valid_schema, "citation_ids_valid": valid_citation_ids, "schema_errors": schema_errors, "generation_status": "success" if not result.get("execution_error") else "failed_after_retry_policy", "retry_policy": "maximum 2 attempts; retry only on transport/runtime execution error; no retry for malformed structured output", "context_sha256": retrieval_by_id[qid]["context_sha256"], "candidate_answer_used_in_prompt": False, "candidate_rubric_used_in_prompt": False})
                append_jsonl(output_path, record)
                done_keys.add(key)
                print(json.dumps({"stage": "generation", "question_id": qid, "model_id": model["model_id"], "status": record["generation_status"], "complete": len(done_keys)}, ensure_ascii=False), flush=True)
            unload = get_unload(model["tag"])
            append_jsonl(run_dir / "model_unload_results.jsonl", {"timestamp": now_local(), **unload})
            if not unload.get("unloaded"):
                errors.append({"model_id": model["model_id"], "stage": "unload", "error": unload.get("error", "model remained resident"), "resident_models": unload.get("resident_models")})
                break
    finally:
        pass
    return errors


def judge_phase(rows: list[dict[str, Any]], retrievals: dict[str, dict[str, Any]], run_dir: Path, only_question_ids: set[str] | None = None) -> list[dict[str, Any]]:
    gen = jsonl_read(run_dir / "generation_outputs.jsonl")
    out_path = run_dir / "judge_results.jsonl"
    prior = jsonl_read(out_path)
    judged = {(r.get("question_id"), r.get("model_id")) for r in prior}
    questions = {q["question_id"]: q for q in rows}
    errors: list[dict[str, Any]] = []
    warmups = jsonl_read(run_dir / "judge_warmup.jsonl")
    if not warmups:
        warm = stream_chat(JUDGE_SPEC["tag"], "You are a strict independent evaluator. Return only the required JSON.", "Warm-up check: provide a valid JSON object with numeric scores and a concise rationale.", JUDGE_SCHEMA, JUDGE_OPTIONS)
        append_jsonl(run_dir / "judge_warmup.jsonl", {"timestamp": now_local(), "judge_tag": JUDGE_SPEC["tag"], "judge_digest": JUDGE_SPEC["digest"], "scored": False, "status": "pass" if not warm.get("execution_error") and not warm.get("parse_error") else "failed", "error": warm.get("execution_error") or warm.get("parse_error"), "wall_time_seconds": warm.get("wall_time_seconds")})
        if warm.get("execution_error") or warm.get("parse_error"):
            return [{"stage": "judge_warmup", "error": warm.get("execution_error") or warm.get("parse_error")}]
    for record in gen:
        qid = record.get("question_id")
        key = (qid, record.get("model_id"))
        if key in judged or (only_question_ids is not None and qid not in only_question_ids):
            continue
        output = record.get("parsed_output")
        if not isinstance(output, dict) or not isinstance(output.get("answer"), str):
            append_jsonl(out_path, {"timestamp": now_local(), "question_id": qid, "model_id": record.get("model_id"), "judge_tag": JUDGE_SPEC["tag"], "judge_digest": JUDGE_SPEC["digest"], "status": "not_scored_generation_invalid", "faithfulness": None, "answer_relevance": None, "context_sufficient": None, "reason": "generator output missing a parseable answer"})
            judged.add(key)
            continue
        q = questions[qid]
        contexts = retrievals[qid]["contexts"]
        context_text = "\n\n".join(f"[{c['context_id']}] document={c['document_id']} page={c.get('page')}\n{c['text']}" for c in contexts)
        judge_prompt = (
            "請獨立評估下列 RAG 回答，只依問題與 Context 評分。不要使用外部知識，"
            "不要使用或推測題庫候選答案／評分規準；本次只評估忠實度、問題相關性及 Context 是否足以回答。"
            "Faithfulness 以 Context 對回答事實主張的支持比例評 0–1；Answer Relevance 以是否直接回答問題評 0–1。"
            "Context Sufficiency 判斷不看回答表現，只看 Context 是否包含足以作答的資訊。"
            "若不確定，應保守評分並在 rationale 說明。\n\n"
            f"問題：\n{q['question_text']}\n\nContext：\n{context_text}\n\n回答：\n{output['answer']}"
        )
        judged_response = stream_chat(JUDGE_SPEC["tag"], "You are an independent evaluator. Do not reveal hidden reasoning. Return only schema-conforming JSON.", judge_prompt, JUDGE_SCHEMA, JUDGE_OPTIONS)
        parsed = judged_response.get("parsed")
        valid = isinstance(parsed, dict) and isinstance(parsed.get("faithfulness"), (int, float)) and isinstance(parsed.get("answer_relevance"), (int, float)) and isinstance(parsed.get("context_sufficient"), bool) and 0 <= float(parsed["faithfulness"]) <= 1 and 0 <= float(parsed["answer_relevance"]) <= 1
        result = {"timestamp": now_local(), "question_id": qid, "model_id": record.get("model_id"), "judge_tag": JUDGE_SPEC["tag"], "judge_digest": JUDGE_SPEC["digest"], "context_sha256": retrievals[qid]["context_sha256"], "judge_request_sha256": judged_response.get("request_sha256"), "status": "scored" if valid else "judge_failed", "faithfulness": float(parsed["faithfulness"]) if valid else None, "answer_relevance": float(parsed["answer_relevance"]) if valid else None, "context_sufficient": parsed.get("context_sufficient") if valid else None, "unsupported_claims": parsed.get("unsupported_claims") if valid else None, "rationale": parsed.get("rationale") if valid else None, "execution_error": judged_response.get("execution_error"), "parse_error": judged_response.get("parse_error"), "judge_wall_time_seconds": judged_response.get("wall_time_seconds"), "candidate_answer_used": False, "candidate_rubric_used": False, "scoring_method": "custom independent LLM Judge rubric; exploratory; not validated RAGAS implementation"}
        append_jsonl(out_path, result)
        judged.add(key)
        if not valid:
            errors.append({"question_id": qid, "model_id": record.get("model_id"), "stage": "judge", "error": judged_response.get("execution_error") or judged_response.get("parse_error") or "judge_schema_or_range_invalid"})
        print(json.dumps({"stage": "judge", "question_id": qid, "model_id": record.get("model_id"), "status": result["status"], "judged": len(judged)}, ensure_ascii=False), flush=True)
    unload = get_unload(JUDGE_SPEC["tag"])
    append_jsonl(run_dir / "judge_unload_results.jsonl", {"timestamp": now_local(), **unload})
    if not unload.get("unloaded"):
        errors.append({"stage": "judge_unload", "error": unload.get("error", "judge remained resident")})
    return errors


def write_metrics(rows: list[dict[str, Any]], retrievals: dict[str, dict[str, Any]], run_dir: Path) -> dict[str, Any]:
    gens = jsonl_read(run_dir / "generation_outputs.jsonl")
    judges = {(r.get("question_id"), r.get("model_id")): r for r in jsonl_read(run_dir / "judge_results.jsonl")}
    metrics = []
    for g in gens:
        judge = judges.get((g.get("question_id"), g.get("model_id")), {})
        row = {"question_id": g.get("question_id"), "model_id": g.get("model_id"), "species": next((q.get("species_chinese") for q in rows if q.get("question_id") == g.get("question_id")), None), "category": next((q.get("inferred_category") for q in rows if q.get("question_id") == g.get("question_id")), None), "generation_status": g.get("generation_status"), "schema_valid": g.get("schema_valid"), "citation_ids_valid": g.get("citation_ids_valid"), "faithfulness": judge.get("faithfulness"), "answer_relevance": judge.get("answer_relevance"), "context_sufficient_by_judge": judge.get("context_sufficient"), "context_precision_at_5": None, "arithmetic_accuracy": None, "logical_accuracy": None, "ttft_seconds": g.get("ttft_first_content_token_seconds"), "ttft_any_token_seconds": g.get("ttft_first_any_token_seconds"), "tps": g.get("tokens_per_second"), "generated_token_count": g.get("generated_token_count"), "wall_time_seconds": g.get("wall_time_seconds"), "system_ram_peak_bytes_sampled": (g.get("attempts") or [{}])[-1].get("memory", {}).get("system_ram_peak_bytes_sampled"), "dedicated_vram_peak_bytes_sampled": (g.get("attempts") or [{}])[-1].get("memory", {}).get("dedicated_vram_peak_bytes_sampled"), "shared_gpu_memory_peak_counter_bytes_sampled": (g.get("attempts") or [{}])[-1].get("memory", {}).get("shared_gpu_memory_peak_counter_bytes_sampled"), "gold_status": "candidate_answer_not_independently_validated", "composite_score": None}
        metrics.append(row)
    write_jsonl_path(run_dir / "per_question_metrics.jsonl", metrics)
    write_jsonl_path(run_dir / "efficiency_metrics.jsonl", [{k: r.get(k) for k in ("question_id", "model_id", "generation_status", "ttft_seconds", "ttft_any_token_seconds", "tps", "generated_token_count", "wall_time_seconds", "system_ram_peak_bytes_sampled", "dedicated_vram_peak_bytes_sampled", "shared_gpu_memory_peak_counter_bytes_sampled")} for r in metrics])
    write_jsonl_path(run_dir / "retrieval_trace.jsonl", list(retrievals.values()))
    write_jsonl_path(run_dir / "prompts.jsonl", [{"question_id": g.get("question_id"), "model_id": g.get("model_id"), "context_sha256": g.get("context_sha256"), "system_prompt": g.get("system_prompt"), "user_prompt": g.get("user_prompt"), "request_sha256": g.get("request_sha256")} for g in gens])
    def summary(metric: str, model_id: str) -> dict[str, Any]:
        vals = [r[metric] for r in metrics if r["model_id"] == model_id and isinstance(r.get(metric), (int, float)) and math.isfinite(float(r[metric]))]
        return {"n": len(vals), "mean": sum(vals) / len(vals) if vals else None, "min": min(vals) if vals else None, "max": max(vals) if vals else None}
    summaries = {}
    for model in MODEL_SPECS:
        mid = model["model_id"]
        summaries[mid] = {"model_tag": model["tag"], "model_digest": model["digest"], "successful_generations": sum(g.get("model_id") == mid and g.get("generation_status") == "success" for g in gens), "failed_generations": sum(g.get("model_id") == mid and g.get("generation_status") != "success" for g in gens), "metrics": {name: summary(name, mid) for name in ("faithfulness", "answer_relevance", "ttft_seconds", "tps", "system_ram_peak_bytes_sampled", "dedicated_vram_peak_bytes_sampled", "shared_gpu_memory_peak_counter_bytes_sampled")}, "structural_ifr": {"n": sum(g.get("model_id") == mid for g in gens), "valid": sum(g.get("model_id") == mid and bool(g.get("schema_valid")) for g in gens), "rate": (sum(g.get("model_id") == mid and bool(g.get("schema_valid")) for g in gens) / sum(g.get("model_id") == mid for g in gens)) if any(g.get("model_id") == mid for g in gens) else None}}
    result = {"created_at": now_local(), "scope": "pilot_only" if len({r["question_id"] for r in metrics}) <= 12 else "full_or_partial_run", "question_count_with_generation": len({r["question_id"] for r in metrics}), "generation_records": len(gens), "judge_records": len(judges), "model_summaries": summaries, "shared_retrieval_question_count": len(retrievals), "context_precision_at_5": {"n": 0, "value": None, "reason": "No independently verified gold evidence-to-chunk mapping for fish test questions."}, "arithmetic_accuracy": {"n": 0, "value": None, "reason": "Fish test calculation candidates do not have independently verified formula, units, conditions, rounding and tolerance."}, "logical_accuracy": {"n": 0, "value": None, "reason": "No independent logical-accuracy rubric was found in the Phase 16-20 specification."}, "candidate_reference_answer_used_as_gold": False, "human_gold": 0}
    write_json(run_dir / "model_comparison_summary.json", result)
    return result


def write_jsonl_path(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8", newline="\n")


def write_static_reports(run_dir: Path, run_id: str, phase: str, baseline: dict[str, Any], source_audit: dict[str, Any], model_audit: dict[str, Any], retrieval_env: dict[str, Any] | None, execution: dict[str, Any], end_baseline: dict[str, Any] | None = None) -> None:
    quality = json.loads((PHASE_A_DIR / "fish_test_data_quality.json").read_text(encoding="utf-8"))
    spec = json.loads((PHASE_A_DIR / "research_plan_metric_spec.json").read_text(encoding="utf-8"))
    write_json(run_dir / "model_runtime_alignment.json", model_audit)
    write_json(run_dir / "scoring_policy_audit.json", {"historical_weighting": {"quality_inner_weights": [0.175, 0.175, 0.175, 0.175], "quality_outer_factor": 0.70, "edge_inner_weights": [0.10, 0.10, 0.10], "edge_outer_factor": 0.30, "maximum_total_if_double_applied": 0.58, "formula": "0.70 * 0.175 * sum(4 quality metrics) + 0.30 * 0.10 * sum(3 edge metrics)"}, "proposed_unfrozen_formula": {"quality_component": "0.175 * (faithfulness + answer_relevance + arithmetic_accuracy + structural_ifr)", "edge_component": "0.10 * (ttft_score + tps_score + memory_pressure_score)", "maximum_if_all_normalized": 1.0}, "formula_validation": {"historical_max_check": abs(0.70 * 0.175 * 4 + 0.30 * 0.10 * 3 - 0.58) < 1e-12, "proposed_max_check": abs(0.175 * 4 + 0.10 * 3 - 1.0) < 1e-12, "status": "passed"}, "metric_spec_source": spec, "unresolved": ["standalone research proposal not found", "memory pressure raw-to-score normalization not found", "TTFT/TPS normalization not defined in available specification", "Answer Relevance Phase 20 formula not explicit", "independent logical-accuracy rubric not found", "fish test has no independent Gold; arithmetic accuracy not assessed"], "exploratory_scoring": "No composite weighted total or winner is calculated; each metric is presented separately. Context Precision@5 has weight 0 and is a shared retrieval metric."})
    write_json(run_dir / "fish_test_metric_spec.json", {"phase_a_spec": spec, "run_metrics": {"faithfulness": "custom independent Judge 0-1 rubric; exploratory, not validated RAGAS", "answer_relevance": "custom independent Judge 0-1 rubric", "structural_ifr": "valid required JSON fields/types divided by all generator requests; citation ID validity reported separately", "context_precision_at_5": "not evaluable without independently verified expected evidence chunk IDs", "arithmetic_accuracy": "not evaluated; no Gold-verified formula set", "logical_accuracy": "not evaluated; no independent rubric", "ttft": "streamed first non-empty final message.content token; if inline thinking makes channel ambiguous, null", "tps": "Ollama done.eval_count / done.eval_duration", "memory": "sampled whole-system RAM and dedicated GPU memory; shared counter per adapter LUID where readable"}, "weighting_policy_frozen": False, "composite_score_emitted": False})
    write_json(run_dir / "fish_test_data_quality.json", quality)
    write_json(run_dir / "source_input_audit.json", source_audit)
    write_json(run_dir / "model_inventory.json", model_audit)
    write_json(run_dir / "retrieval_preflight.json", {"status": "passed" if retrieval_env else "failed_or_not_reached", "environment": retrieval_env, "failure": execution.get("retrieval_error")})
    write_json(run_dir / "pilot_results.json", {"run_id": run_id, "phase": phase, "generated_at": now_local(), "pilot_questions": execution.get("pilot_questions", []), "retrieval_count": execution.get("retrieval_count", 0), "generator_outputs": execution.get("generator_count", 0), "judge_results": execution.get("judge_count", 0), "warmup_count": execution.get("warmup_count", 0), "status": execution.get("status"), "pilot_go": execution.get("pilot_go", False), "go_gate_results": execution.get("go_gate_results", {}), "errors": execution.get("errors", []), "stop_reason": execution.get("stop_reason"), "exploratory_only": True, "formal_gold_available": False, "formal_weighting_frozen": False})
    write_json(run_dir / "compatibility.json", {"run_id": run_id, "protected_manifest_before": {"count": baseline.get("checked_count"), "complete": baseline.get("complete"), "mismatches": baseline.get("mismatches")}, "protected_manifest_after": {"count": end_baseline.get("checked_count") if end_baseline else None, "complete": end_baseline.get("complete") if end_baseline else None, "mismatches": end_baseline.get("mismatches") if end_baseline else None}, "sqlite_before_sha256": baseline.get("sqlite_sha256"), "sqlite_after_sha256": end_baseline.get("sqlite_sha256") if end_baseline else None, "sqlite_matches_expected_before": baseline.get("sqlite_matches"), "sqlite_unchanged": bool(end_baseline and baseline.get("sqlite_sha256") == end_baseline.get("sqlite_sha256")), "production_modified": False, "corpus_v2_modified": False, "historical_e4_modified": False, "model_weights_modified": False, "judge_modified": False, "fish_test_originals_modified": False, "formal_model_scoring": False, "winner": None, "protected_baseline_ok": bool(baseline.get("complete") and end_baseline and end_baseline.get("complete") and baseline.get("sqlite_sha256") == end_baseline.get("sqlite_sha256"))})
    write_json(run_dir / "execution_manifest.json", {"run_id": run_id, "created_at": now_local(), "phase": phase, "run_directory": str(run_dir), "question_source": str(QUESTION_FILE.relative_to(ROOT)), "question_count": len(read_jsonl(QUESTION_FILE)), "model_config_version": "fish-test-exp-v1; M3 corrected to Llama-8B tag", "historical_frozen_config_modified": False, "retrieval": retrieval_env, "execution": execution, "formal_winner": None})
    summary = [
        "# Fish Test 評測執行摘要",
        "",
        f"- Run ID：`{run_id}`",
        f"- 階段：`{phase}`",
        f"- 狀態：`{execution.get('status')}`",
        f"- Pilot Go：`{execution.get('pilot_go', False)}`",
        f"- 本輪實際檢索題數：{execution.get('retrieval_count', 0)}",
        f"- Generator 輸出紀錄：{execution.get('generator_count', 0)}",
        f"- Judge 評分紀錄：{execution.get('judge_count', 0)}",
        f"- 保護基線：開始 {baseline.get('matching_count')}/636；結束 {end_baseline.get('matching_count') if end_baseline else '未完成'}/636",
        f"- SQLite：開始 `{baseline.get('sqlite_sha256')}`；結束 `{end_baseline.get('sqlite_sha256') if end_baseline else '未完成'}`",
        "- Formal Gold：未取得；候選答案未當成 Gold。",
        "- Composite weighted score / Winner：未計算。",
        "",
        "## 主要限制",
        "",
        "Phase A 找到的原研究計畫書未包含獨立、可確認的完整權重正規化規則。候選答案與來源欄位尚未經獨立核驗；因此不報正式 Accuracy、Arithmetic Accuracy 或 Context Precision@5。Faithfulness 與 Answer Relevance 使用隔離的 Mistral NeMo Judge 探索性評分，不等同已校準的 RAGAS 正式分數。",
        "",
        "Pilot 詳細結果、錯誤與 Gate 判定請檢視 `pilot_results.json`、`retrieval_trace.jsonl`、`generation_outputs.jsonl`、`judge_results.jsonl` 與 `per_question_metrics.jsonl`。",
    ]
    (run_dir / "fish_test_final_report.md").write_text("\n".join(summary) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--phase", choices=["pilot", "full"], default="pilot")
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_dir.name
    questions = read_jsonl(QUESTION_FILE)
    if len(questions) != 180 or len({q.get("question_id") for q in questions}) != 180:
        raise RuntimeError("Phase A normalized input does not contain 180 unique question IDs")
    run_questions = choose_pilot(questions) if args.phase == "pilot" else questions
    baseline = protect_baseline()
    source_audit = source_input_audit(questions)
    write_json(run_dir / "protected_baseline_before.json", baseline)
    write_jsonl_path(run_dir / "fish_test_questions_normalized.jsonl", questions)
    execution: dict[str, Any] = {"phase": args.phase, "status": "preflight", "errors": [], "pilot_questions": [q["question_id"] for q in run_questions] if args.phase == "pilot" else [], "retrieval_count": 0, "generator_count": 0, "judge_count": 0, "warmup_count": 0, "pilot_go": False, "go_gate_results": {}}
    retrieval_env = None
    model_audit: dict[str, Any] = {"status": "not_checked"}
    retrievals: dict[str, dict[str, Any]] = {r["question_id"]: r for r in jsonl_read(run_dir / "retrieval_trace.jsonl")}
    if not baseline["complete"] or not baseline["sqlite_matches"]:
        execution.update(status="blocked_protected_baseline", stop_reason="636-file manifest or expected SQLite checksum did not pass before inference")
        write_static_reports(run_dir, run_id, args.phase, baseline, source_audit, model_audit, None, execution)
        return 2
    if not source_audit["all_workbooks_match"]:
        execution.update(status="blocked_fish_test_source_integrity", stop_reason="One or more fish test XLSX files differ from Phase A")
        write_static_reports(run_dir, run_id, args.phase, baseline, source_audit, model_audit, None, execution)
        return 2
    try:
        model_audit = validate_models()
        write_json(run_dir / "model_runtime_alignment.json", model_audit)
        if not model_audit["all_generator_identities_pass"] or not model_audit["judge_identity_pass"] or not model_audit["embedding_identity_pass"] or not model_audit["runtime_version_matches_historical"]:
            raise RuntimeError("Model/Judge/Embedding identity or Ollama version gate failed")
    except Exception as exc:
        execution.update(status="blocked_model_preflight", stop_reason=type(exc).__name__ + ": " + str(exc), errors=[traceback.format_exc()])
        end = protect_baseline()
        write_json(run_dir / "protected_baseline_after.json", end)
        write_static_reports(run_dir, run_id, args.phase, baseline, source_audit, model_audit, None, execution, end)
        return 2
    bm25 = dense = embed = reranker = None
    sampler = None
    retrieval_error = None
    try:
        bm25, dense, embed, reranker, aux = make_retrieval_engine(run_dir)
        retrieval_env = aux["environment"]
        execution["retrieval_count_before_run"] = len(retrievals)
        for q in run_questions:
            if q["question_id"] in retrievals:
                continue
            result = retrieve_one(q, bm25, dense, embed, reranker, aux)
            retrievals[q["question_id"]] = result
            append_jsonl(run_dir / "retrieval_trace.jsonl", result)
            print(json.dumps({"stage": "retrieval", "question_id": q["question_id"], "context_sha256": result["context_sha256"]}, ensure_ascii=False), flush=True)
    except Exception as exc:
        retrieval_error = type(exc).__name__ + ": " + str(exc)
        execution["errors"].append({"stage": "retrieval_preflight_or_query", "error": retrieval_error, "traceback": traceback.format_exc()})
        execution.update(status="blocked_e4_retrieval", stop_reason=retrieval_error, retrieval_count=len(retrievals))
    finally:
        if reranker is not None:
            try:
                reranker.close()
            except Exception as exc:
                execution["errors"].append({"stage": "reranker_close", "error": str(exc)})
    embedding_unload = get_unload(EMBED_SPEC["tag"]) if not retrieval_error else None
    if embedding_unload is not None:
        append_jsonl(run_dir / "embedding_unload_results.jsonl", {"timestamp": now_local(), **embedding_unload})
        execution["embedding_unloaded_after_retrieval"] = bool(embedding_unload.get("unloaded"))
        if not embedding_unload.get("unloaded"):
            execution["errors"].append({"stage": "embedding_unload", "error": embedding_unload.get("error", "BGE-M3 remained resident"), "resident_models": embedding_unload.get("resident_models")})
    if retrieval_error:
        end = protect_baseline()
        write_json(run_dir / "protected_baseline_after.json", end)
        write_static_reports(run_dir, run_id, args.phase, baseline, source_audit, model_audit, retrieval_env, execution, end)
        return 2
    try:
        sampler = HardwareSampler(run_dir)
        sampler.start()
        execution["retrieval_count"] = len(retrievals)
        selected_ids = {q["question_id"] for q in run_questions}
        gen_errors = generator_phase(questions, retrievals, MODEL_SPECS, run_dir, sampler, selected_ids)
        execution["errors"].extend({"stage": "generator", **e} for e in gen_errors)
        sampler_meta = sampler.finish()
        execution["hardware_sampler"] = sampler_meta
    except Exception as exc:
        execution["errors"].append({"stage": "generator_phase", "error": type(exc).__name__ + ": " + str(exc), "traceback": traceback.format_exc()})
        if sampler:
            execution["hardware_sampler"] = sampler.finish()
    execution["generator_count"] = len(jsonl_read(run_dir / "generation_outputs.jsonl"))
    try:
        judge_errors = judge_phase(questions, retrievals, run_dir, {q["question_id"] for q in run_questions})
    except Exception as exc:
        judge_errors = [{"stage": "judge_phase", "error": type(exc).__name__ + ": " + str(exc), "traceback": traceback.format_exc()}]
    execution["errors"].extend({"stage": "judge", **e} for e in judge_errors)
    execution["judge_count"] = len(jsonl_read(run_dir / "judge_results.jsonl"))
    execution["warmup_count"] = len(jsonl_read(run_dir / "warmup_results.jsonl")) + len(jsonl_read(run_dir / "judge_warmup.jsonl"))
    metrics = write_metrics(questions, retrievals, run_dir)
    gens = jsonl_read(run_dir / "generation_outputs.jsonl")
    judges = jsonl_read(run_dir / "judge_results.jsonl")
    expected = len(run_questions) * len(MODEL_SPECS)
    selected_question_ids = {q["question_id"] for q in run_questions}
    contexts_consistent = all(
        len([g for g in gens if g.get("question_id") == q["question_id"]]) == len(MODEL_SPECS)
        and len({g.get("context_sha256") for g in gens if g.get("question_id") == q["question_id"]}) == 1
        for q in run_questions
    )
    gen_key_set = {(g.get("question_id"), g.get("model_id")) for g in gens if g.get("question_id") in selected_question_ids}
    judge_key_set = {(j.get("question_id"), j.get("model_id")) for j in judges if j.get("question_id") in selected_question_ids}
    per_model = {m["model_id"]: sum(g.get("model_id") == m["model_id"] and g.get("generation_status") == "success" and isinstance((g.get("parsed_output") or {}).get("answer"), str) and bool((g.get("parsed_output") or {}).get("answer", "").strip()) for g in gens if g.get("question_id") in {q["question_id"] for q in run_questions}) for m in MODEL_SPECS}
    judgable_keys = {(g.get("question_id"), g.get("model_id")) for g in gens if g.get("question_id") in selected_question_ids and isinstance((g.get("parsed_output") or {}).get("answer"), str) and bool((g.get("parsed_output") or {}).get("answer", "").strip())}
    judge_success_keys = {(j.get("question_id"), j.get("model_id")) for j in judges if j.get("question_id") in selected_question_ids and j.get("status") == "scored"}
    judge_success = len(judge_success_keys)
    judgable_count = len(judgable_keys)
    ttft_n = sum(g.get("ttft_first_content_token_seconds") is not None for g in gens if g.get("question_id") in selected_question_ids)
    tps_n = sum(g.get("tokens_per_second") is not None for g in gens if g.get("question_id") in selected_question_ids)
    judge_warmup = jsonl_read(run_dir / "judge_warmup.jsonl")
    execution["go_gate_results"] = {"four_model_identities_correct": model_audit.get("all_generator_identities_pass", False), "four_models_generated": all(per_model.get(m["model_id"], 0) > 0 for m in MODEL_SPECS), "historical_e4_loaded_and_freshly_queried": len(retrievals) >= len(run_questions), "same_context_digest_across_four_models": contexts_consistent, "independent_judge_operational": judgable_count > 0 and judgable_keys.issubset(judge_success_keys) and bool(judge_warmup) and judge_warmup[0].get("status") == "pass", "ttft_measured": ttft_n == expected, "tps_measured": tps_n == expected, "excel_generated_and_reopened": "pending_workbook_validation", "metric_missing_values_handled": metrics.get("context_precision_at_5", {}).get("n") == 0 and metrics.get("arithmetic_accuracy", {}).get("n") == 0, "gold_and_weighting_limits_do_not_invalidate_exploratory": True}
    technical_gate_values = [v for k, v in execution["go_gate_results"].items() if k != "excel_generated_and_reopened"]
    execution["pilot_go"] = all(technical_gate_values)
    execution["status"] = "pilot_technical_gates_pass_pending_workbook" if args.phase == "pilot" and execution["pilot_go"] else "pilot_blocked" if args.phase == "pilot" else "full_run_complete" if len({g.get("question_id") for g in gens}) == 180 and len(gens) == 720 else "full_run_incomplete"
    if not execution["pilot_go"] and args.phase == "pilot":
        failed = [name for name, ok in execution["go_gate_results"].items() if not ok]
        execution["stop_reason"] = "Pilot Go gates not all met: " + ", ".join(failed)
    end = protect_baseline()
    write_json(run_dir / "protected_baseline_after.json", end)
    write_static_reports(run_dir, run_id, args.phase, baseline, source_audit, model_audit, retrieval_env, execution, end)
    print(json.dumps({"status": execution["status"], "pilot_go": execution["pilot_go"], "retrieval_count": len(retrievals), "generator_count": execution["generator_count"], "judge_count": execution["judge_count"], "failed_gates": [k for k, v in execution["go_gate_results"].items() if not v]}, ensure_ascii=False), flush=True)
    return 0 if execution["pilot_go"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
