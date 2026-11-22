from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path.cwd()
OUT = ROOT / "reports/evaluation/fish_test_phase_a_20261012"
STAMP = datetime.now().astimezone().isoformat(timespec="seconds")


def jdump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def jldump(name, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def norm(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)


def val(value):
    return "" if value is None else str(value).strip()


def table(ws, header_row=4):
    rows = list(ws.iter_rows(values_only=True))
    headers = [val(x) for x in (rows[header_row - 1] if len(rows) >= header_row else [])]
    result = []
    for excel_row, row in enumerate(rows[header_row:], header_row + 1):
        if any(x is not None and str(x).strip() for x in row):
            result.append((excel_row, {h: row[i] if i < len(row) else None for i, h in enumerate(headers) if h}))
    return headers, result, len(rows)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def hash_worker(item):
    path, stat = item
    try:
        return path, sha256(path), None
    except Exception as exc:
        return path, None, f"{type(exc).__name__}: {exc}"


def csv_write(name, columns, rows):
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


FISH = {
    "吳郭魚": ("Oreochromis spp.", "tilapia"),
    "烏魚": ("Mugil cephalus", "mullet"),
    "石斑魚": ("Epinephelus spp.", "grouper"),
    "虱目魚": ("Chanos chanos", "milkfish"),
    "鰻魚": ("Anguilla spp.", "eel"),
    "鱸魚": ("Lates calcarifer / Lateolabrax spp. (workbook label varies)", "seabass"),
}
SHEET = {
    "說明": "使用說明", "流程": "工作流程", "sources": "資料來源", "facts": "事實資料庫",
    "questions": "題目庫", "calc": "計算資料", "scores": "評分紀錄", "test": "測試資料",
}
CATEGORIES = ["Fact", "Water Quality", "Disease", "Climate / Cold", "Medication / Law", "Calculation"]
PATTERNS = [
    ("Medication / Law", re.compile(r"用藥|藥品|藥物|停藥|禁藥|藥休|法規|法律|許可|核准")),
    ("Calculation", re.compile(r"計算|公式|投餌量|放養密度|飼養率|飼料轉換率|\bFCR\b|\bSGR\b", re.I)),
    ("Climate / Cold", re.compile(r"寒害|寒流|防寒|低溫|冬季|越冬|降溫|寒潮")),
    ("Disease", re.compile(r"疾病|病原|感染|寄生|症狀|防疫|消毒|病毒|寄生蟲")),
    ("Water Quality", re.compile(r"水質|溶氧|氨氮|氨氨|亞硝酸|鹽度|\bpH\b|酸鹼|水溫|水體|水質監測", re.I)),
]


def infer_category(topic, qtype, qtext, eval_type):
    text = " ".join(val(x) for x in (topic, qtype, qtext, eval_type))
    if "計算" in val(qtype) or "計算" in val(eval_type):
        return "Calculation", "workbook question/evaluation type"
    for category, pattern in PATTERNS:
        if pattern.search(text):
            return category, "heuristic from topic/question"
    return "Fact", "fallback inference"


fish_dir = ROOT / "fish test"
workbooks = sorted(fish_dir.glob("*.xlsx"))
inventory, questions, mirror_rows = [], [], []
fish_counts, category_counts, topic_counts = Counter(), Counter(), Counter()
wb_hashes = {}

for path in workbooks:
    fish = next((name for name in FISH if name in path.name), "unknown")
    _, slug = FISH.get(fish, ("unknown", "unknown"))
    file_sha = sha256(path)
    wb_hashes[path.name] = file_sha
    wb = load_workbook(path, read_only=True, data_only=True)
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        header_row = 4 if len(rows) >= 4 and sum(x is not None for x in rows[3]) >= 2 else 1
        headers = [val(x) for x in (rows[header_row - 1] if rows else []) if x is not None]
        data_rows = sum(1 for row in rows[header_row:] if any(x is not None and str(x).strip() for x in row))
        inventory.append({
            "file_name": path.name, "species": fish, "sheet_name": sheet_name, "max_row": ws.max_row,
            "max_column": ws.max_column, "header_row_guess": header_row, "columns": " | ".join(headers),
            "nonempty_data_rows_after_header": data_rows, "file_size_bytes": path.stat().st_size,
            "last_write_time": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            "sha256": file_sha, "status": "readable",
        })
    qheads, qrows, _ = table(wb[SHEET["questions"]])
    theads, trows, _ = table(wb[SHEET["test"]])
    _, srows, _ = table(wb[SHEET["sources"]])
    _, frows, _ = table(wb[SHEET["facts"]])
    _, crows, _ = table(wb[SHEET["calc"]])
    sources = {val(r.get("來源ID")): r for _, r in srows if val(r.get("來源ID"))}
    facts = {val(r.get("事實ID")): r for _, r in frows if val(r.get("事實ID"))}
    calcs = {val(r.get("題號")): r for _, r in crows if val(r.get("題號"))}
    test_by_id = {val(r.get("question_id")): r for _, r in trows if val(r.get("question_id"))}
    for row_no, q in qrows:
        qid = val(q.get("題號"))
        if not qid:
            continue
        td = test_by_id.get(qid, {})
        question = val(q.get("問題")) or val(td.get("user_input"))
        topic = val(q.get("主題"))
        qtype = val(q.get("題目形式")) or val(td.get("question_format"))
        eval_type = val(q.get("評估類型"))
        explicit = val(td.get("category"))
        category, basis = infer_category(topic, qtype, question, eval_type)
        if explicit in CATEGORIES:
            category, basis = explicit, "test_data_explicit_category"
        fact_ids = [x.strip() for x in re.split(r"[,;，；]", val(q.get("事實ID"))) if x.strip()]
        source_ids = [x.strip() for x in re.split(r"[,;，；]", val(q.get("來源ID"))) if x.strip()]
        urls = [x.strip() for x in re.split(r"[,;，；]", val(q.get("來源網址"))) if x.strip()]
        source_rows = [sources[x] for x in source_ids if x in sources]
        fact_rows = [facts[x] for x in fact_ids if x in facts]
        option = lambda n: val(q.get(f"選項{n}"))
        answer = val(q.get("基準答案")) or val(td.get("reference_answer"))
        test_text = val(td.get("user_input"))
        mirror_rows.append({
            "file": path.name, "question_id": qid, "question_bank_excel_row": row_no,
            "question_text_matches_test_data": norm(question) == norm(test_text) if test_text else False,
            "fact_ids_resolve": bool(fact_ids) and all(x in facts for x in fact_ids),
            "source_ids_resolve": bool(source_ids) and all(x in sources for x in source_ids),
        })
        questions.append({
            "question_id": f"FT-{slug}-{qid}", "original_question_id": qid, "source_workbook": path.name,
            "source_workbook_sha256": file_sha, "question_bank_excel_row": row_no,
            "species_chinese": fish, "species_label_in_test_data": val(td.get("species")),
            "species_taxonomy_status": "workbook label only; not independently verified",
            "question_text": question, "question_format": qtype, "evaluation_type": eval_type, "topic": topic,
            "inferred_category": category, "category_basis": basis, "difficulty": val(q.get("難度")),
            "options": {k: option(k) for k in "ABCD"},
            "candidate_correct_option": val(q.get("正確選項")) or val(td.get("correct_option")),
            "candidate_reference_answer": answer, "candidate_scoring_key_points": val(q.get("必答重點")),
            "candidate_major_error": val(q.get("重大錯誤")), "fact_ids": fact_ids, "source_ids": source_ids,
            "source_records": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in s.items()} for s in source_rows],
            "fact_records": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in f.items()} for f in fact_rows],
            "calculation_record": {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in calcs[qid].items()} if qid in calcs else None,
            "candidate_source_urls": urls or [val(s.get("URL")) for s in source_rows if val(s.get("URL"))],
            "law_last_verified": td.get("law_last_verified"), "source_page_or_exact_span": None,
            "referenced_source_sha256": None, "answer_verification_status": "candidate only; not independently verified",
            "human_gold_reviewed": False, "rag_grounding_status": "not verified against frozen E4",
            "split_label": val(td.get("split")), "formal_scoring_suitability": "not_ready",
            "exploratory_suitability": "candidate_only",
            "row_quality": {
                "question_text_present": bool(question), "answer_present": bool(answer or val(td.get("correct_option"))),
                "fact_ids_resolve": bool(fact_ids) and all(x in facts for x in fact_ids),
                "source_ids_resolve": bool(source_ids) and all(x in sources for x in source_ids),
                "source_url_present": bool(urls or source_rows), "missing_fact_ids": [x for x in fact_ids if x not in facts],
                "missing_source_ids": [x for x in source_ids if x not in sources],
            },
        })
        fish_counts[fish] += 1
        category_counts[category] += 1
        topic_counts[f"{fish}::{topic}"] += 1
    wb.close()

exact = defaultdict(list)
templates = defaultdict(list)
for q in questions:
    exact[norm(q["question_text"])].append(q["question_id"])
    templ = q["question_text"]
    for species in FISH:
        templ = templ.replace(species, "{SPECIES}")
    templates[(q["inferred_category"], norm(templ))].append(q["question_id"])
exact_dups = [{"normalized_text": k, "question_ids": v} for k, v in exact.items() if k and len(v) > 1]
template_dups = [{"category": k[0], "template_key": k[1], "question_ids": v} for k, v in templates.items() if k[1] and len(v) > 1]
near = []
for i, a in enumerate(questions):
    for b in questions[i + 1:]:
        if a["species_chinese"] == b["species_chinese"] and a["inferred_category"] == b["inferred_category"]:
            ratio = SequenceMatcher(None, norm(a["question_text"]), norm(b["question_text"])).ratio()
            if ratio >= .82 and norm(a["question_text"]) != norm(b["question_text"]):
                near.append({"question_id_a": a["question_id"], "question_id_b": b["question_id"], "similarity": round(ratio, 4), "review": "suspected; human review required"})
mirror_mismatch = [r for r in mirror_rows if not (r["question_text_matches_test_data"] and r["fact_ids_resolve"] and r["source_ids_resolve"])]
complete = sum(bool(q["question_text"] and q["candidate_reference_answer"]) for q in questions)
source_linked = sum(bool(q["source_ids"] and q["candidate_source_urls"]) for q in questions)
fact_linked = sum(bool(q["fact_ids"]) and q["row_quality"]["fact_ids_resolve"] for q in questions)

with (OUT / "fish_test_file_inventory.csv").open("w", encoding="utf-8-sig", newline="") as f:
    cols = ["file_name", "species", "sheet_name", "max_row", "max_column", "header_row_guess", "columns", "nonempty_data_rows_after_header", "file_size_bytes", "last_write_time", "sha256", "status"]
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(inventory)
jldump("fish_test_questions_normalized.jsonl", questions)
quality = {
    "created_at": STAMP, "workbook_count": len(workbooks), "sheet_count": len(inventory),
    "candidate_questions": len(questions), "unique_question_ids": len({q["question_id"] for q in questions}),
    "question_bank_and_test_data_are_mirrors": True, "mirror_mismatch_count": len(mirror_mismatch), "mirror_mismatch_examples": mirror_mismatch[:50],
    "complete_question_answer_candidates": complete, "source_linked_candidates": source_linked, "fact_id_linked_candidates": fact_linked,
    "exact_duplicate_groups": exact_dups, "species_substituted_template_groups": template_dups,
    "suspected_near_duplicate_pairs_at_similarity_0_82": near[:100], "suspected_near_duplicate_pair_count": len(near),
    "species_distribution": dict(fish_counts), "inferred_category_distribution": dict(category_counts),
    "species_category_distribution": {s: {c: sum(q["species_chinese"] == s and q["inferred_category"] == c for q in questions) for c in CATEGORIES} for s in FISH},
    "topic_distribution": dict(topic_counts), "question_format_distribution": dict(Counter(q["question_format"] for q in questions)),
    "evaluation_type_distribution": dict(Counter(q["evaluation_type"] for q in questions)), "split_labels": dict(Counter(q["split_label"] for q in questions)),
    "formal_scoring_ready": 0, "exploratory_candidates": len(questions), "human_gold": 0,
    "blockers": ["reference answers are workbook candidates, not independently verified", "original source version/checksum and exact page/span are not attached per item", "species/category applicability has not been independently audited", "no fresh frozen E4 evidence mapping/probe", "pilot_v3 is not a formal Selection/Holdout split"],
    "category_note": "The test-data category column encodes Direct/Paraphrase/Contextual query style, not the six study categories; inferred categories are heuristic and retain the basis field.",
}
jdump("fish_test_data_quality.json", quality)

metric_spec = {
    "created_at": STAMP,
    "proposal_document": {"standalone_research_proposal_found": False, "search_scope": ["docs", "src/evaluation", "reports/evaluation/final_model_selection"], "available_specs": ["src/evaluation/phase20_protocol.py", "docs/phase16_evaluation.md", "docs/retrieval_metrics.md", "docs/phase17_generation_comparison.md", "docs/phase19A_local_edge_protocol.md", "docs/phase19B_full_edge_protocol.md", "docs/evaluation_split_policy.md", "docs/annotation_guideline.md"]},
    "metrics": [
        {"name": "Faithfulness", "code_key": "faithfulness", "definition": "RAGAS claims decomposed and checked against supplied contexts; citation validity/recall separate.", "direction": "higher", "inner_weight": .175, "outer_factor": .70, "sources": ["docs/phase16_evaluation.md", "src/evaluation/phase20_protocol.py"]},
        {"name": "Answer Relevance", "code_key": "plan_answer_relevance", "definition": "Phase 20 primary metric; Phase 16 native Answer Relevancy strictness=3; detailed Phase 20 formula not explicit.", "direction": "higher", "inner_weight": .175, "outer_factor": .70, "sources": ["docs/phase16_evaluation.md", "src/evaluation/phase20_protocol.py"]},
        {"name": "Context Precision@5", "code_key": "retrieval_precision_at_5", "definition": "Unique acceptable evidence chunks divided by returned unique eligible chunks; shared retrieval/system metric.", "direction": "higher", "inner_weight": 0, "outer_factor": None, "sources": ["docs/retrieval_metrics.md", "src/evaluation/phase20_protocol.py"]},
        {"name": "Logical/Arithmetic Accuracy", "code_key": "arithmetic_accuracy", "definition": "Code only defines arithmetic_accuracy; separate logical accuracy rubric not found. Calculation gold requires formula/input/unit/expected output/rounding/tolerance/evidence.", "direction": "higher", "inner_weight": .175, "outer_factor": .70, "sources": ["src/evaluation/phase20_protocol.py"]},
        {"name": "Instruction Following Rate", "code_key": "plan_ifr", "definition": "valid structured outputs / all requests; not full semantic instruction compliance or inference failure rate.", "direction": "higher", "inner_weight": .175, "outer_factor": .70, "sources": ["src/evaluation/phase20_protocol.py", "docs/phase19B_full_edge_protocol.md"]},
        {"name": "TTFT", "code_key": "ttft_ms", "definition": "Accepted request to first final structured-content token, excluding thinking; E2E includes retrieval/generation/technical retry.", "direction": "lower", "inner_weight": .10, "outer_factor": .30, "sources": ["docs/phase19B_full_edge_protocol.md"]},
        {"name": "TPS", "code_key": "tps", "definition": "Runtime eval_count/decode_duration may include thinking; visible-answer TPS separate if available.", "direction": "higher", "inner_weight": .10, "outer_factor": .30, "sources": ["docs/phase19_edge_execution_guide.md", "docs/phase19A_local_edge_protocol.md"]},
        {"name": "RAM", "code_key": "raw_memory", "definition": "Whole-system and process-family working sets are separate; process sums may double-count shared pages. No individual Phase 20 weight.", "direction": "diagnostic", "inner_weight": None, "outer_factor": None, "sources": ["docs/phase17_generation_comparison.md", "docs/phase19A_local_edge_protocol.md"]},
        {"name": "VRAM", "code_key": "raw_memory", "definition": "Dedicated device VRAM separated from WDDM shared memory/model allocation. No individual Phase 20 weight.", "direction": "diagnostic", "inner_weight": None, "outer_factor": None, "sources": ["docs/phase17_generation_comparison.md", "docs/phase19A_local_edge_protocol.md"]},
        {"name": "Memory Pressure", "code_key": "memory_pressure", "definition": "0.10 edge inner weight, cost metric; raw-to-score formula not located.", "direction": "lower", "inner_weight": .10, "outer_factor": .30, "sources": ["src/evaluation/phase20_protocol.py"]},
    ],
    "weighting_audit": {"nominal_quality_edge": [0.70, 0.30], "inner_quality_sum": .70, "inner_edge_sum": .30, "outer_factors": [0.70, 0.30], "max_score": .58, "effective_quality_share": .8448275862, "effective_edge_share": .1551724138, "issue": "quality_edge_scores applies 70/30 after subweights already summing to 70/30; owner clarification needed before official scoring", "no_weights_invented": True},
    "other_defined_retrieval_metrics": ["Recall@K_chunk", "all_required_recall@K", "Recall@K_page", "Recall@K_document", "Precision@K", "MRR", "nDCG@K"],
    "phase16_answer_correctness_subweights": {"factuality": .75, "semantic_similarity": .25, "beta": 1, "scope": "internal to Phase 16 correctness, not overall Phase 20 score"},
    "unresolved": ["separate Logical Accuracy definition", "semantic instruction following rubric", "memory_pressure formula", "individual RAM/VRAM weight", "whether Phase 16 correctness score is part of Phase 20"],
}
jdump("research_plan_metric_spec.json", metric_spec)

def loadj(rel):
    try: return json.loads((ROOT / rel).read_text(encoding="utf-8-sig"))
    except Exception as exc: return {"_read_error": f"{type(exc).__name__}: {exc}"}

py_candidates = [("system", "C:/Python314/python.exe"), ("project_venv", "C:/my project/115_marine_project/.venv/Scripts/python.exe"), ("ragas_venv", "C:/my project/115_marine_project/.venv-ragas/Scripts/python.exe"), ("reranker_venv", "C:/my project/115_marine_project/.venv-reranker/Scripts/python.exe"), ("codex_bundled", "C:/Users/ethan/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe")]
py_probe = "import sys,importlib.util,importlib.metadata as m,json; ns=['pytest','docx','fitz','torch','transformers','sentence_transformers','openpyxl','pandas']; print(json.dumps({'python':sys.version.split()[0],'executable':sys.executable,'modules':{n:bool(importlib.util.find_spec(n)) for n in ns},'versions':{n:(m.version(n) if importlib.util.find_spec(n) else None) for n in ns}}))"
py_rows = []
for name, exe in py_candidates:
    if not Path(exe).exists():
        py_rows.append({"environment": name, "status": "not_found", "executable": exe}); continue
    try:
        cp = subprocess.run([exe, "-c", py_probe], capture_output=True, text=True, timeout=30)
        data = json.loads(cp.stdout.strip().splitlines()[-1]) if cp.returncode == 0 else None
        py_rows.append({"environment": name, "status": "probed" if cp.returncode == 0 else "probe_failed", "returncode": cp.returncode, "probe": data, "stderr": cp.stderr[-800:] or None})
    except Exception as exc:
        py_rows.append({"environment": name, "status": "probe_failed", "error": f"{type(exc).__name__}: {exc}"})

now = STAMP
ollama = {"status": "not_checked"}
try:
    with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as resp:
        tag_json = json.loads(resp.read().decode("utf-8"))
    tags = []
    for item in tag_json.get("models", []):
        det = item.get("details", {})
        tags.append({"name": item.get("name"), "digest": item.get("digest"), "size_bytes": item.get("size"), "family": det.get("family"), "parameter_size": det.get("parameter_size"), "quantization_level": det.get("quantization_level")})
    ollama = {"status": "reachable", "url": "http://127.0.0.1:11434/api/tags", "checked_at": now, "version": "not rechecked; Phase 20.1R manifest records 0.35.0", "models": tags}
except Exception as exc:
    ollama = {"status": "failed", "checked_at": now, "error": f"{type(exc).__name__}: {exc}", "earlier_phase_observation": "API responded earlier in this turn"}
gpu = {"status": "not_checked", "checked_at": now}
try:
    cp = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu", "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
    gpu = {"status": "available" if cp.returncode == 0 else "failed", "checked_at": now, "output": cp.stdout.strip(), "returncode": cp.returncode, "stderr": cp.stderr.strip() or None, "note": "read-only snapshot; no model test"}
except Exception as exc:
    gpu = {"status": "failed", "checked_at": now, "error": f"{type(exc).__name__}: {exc}"}
phase_readiness = loadj("reports/evaluation/final_model_selection/phase20_1R/readiness.json")
m3_manifest = loadj("reports/evaluation/final_model_selection/phase20_1R/M3_manifest.json")
e4_manifest = loadj("reports/evaluation/final_model_selection/phase20_1R/e4_final_manifest.json")
tag_map = {item.get("name"): item for item in ollama.get("models", []) if isinstance(item, dict)}
m3_tag_name = "hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M"
env = {
    "created_at": now, "project_directory": str(ROOT), "python_environments": py_rows, "ollama": ollama, "gpu": gpu,
    "model_inventory": {
        "M1": {"runtime": "deepseek-r1:7b", "local": tag_map.get("deepseek-r1:7b")},
        "M2": {"runtime": "qwen2.5-coder:7b", "local": tag_map.get("qwen2.5-coder:7b")},
        "M3": {"phase20_runtime_alias": "deepseek-r1:8b", "verified_llama_runtime": m3_tag_name, "verified_local": tag_map.get(m3_tag_name), "alias_local": tag_map.get("deepseek-r1:8b"), "artifact_architecture": m3_manifest.get("architecture"), "artifact_sha256": m3_manifest.get("artifact_sha256"), "ollama_digest": m3_manifest.get("ollama_digest"), "finding": "Llama-8B artifact is verified; phase20 alias maps to a qwen3-family local tag and must be reconciled."},
        "M4": {"runtime": "gemma2:9b", "local": tag_map.get("gemma2:9b")},
        "Independent Judge": {"runtime": "mistral-nemo:12b-instruct-2407-q4_K_M", "local": tag_map.get("mistral-nemo:12b-instruct-2407-q4_K_M")},
        "BGE-M3": {"runtime": "bge-m3:latest", "local": tag_map.get("bge-m3:latest")},
        "Reranker": {"model_id": (e4_manifest.get("reranker") or {}).get("model_id"), "revision": (e4_manifest.get("reranker") or {}).get("revision"), "device": (e4_manifest.get("reranker") or {}).get("device"), "local_path": ".venv-reranker/hf-cache"},
    },
    "historical_e4": {"ready": e4_manifest.get("ready"), "new_index_built": e4_manifest.get("new_index_built"), "chunk_count": e4_manifest.get("corpus_chunk_count"), "corpus_sha256": e4_manifest.get("corpus_sha256"), "manifest_sha256": e4_manifest.get("historical_E4_manifest_sha256"), "BM25_candidates": 50, "Dense_candidates": 50, "RRF_k": 60, "top_k": 5, "fair_use_limit": "technically available; fish test lacks independently verified answer/evidence mapping"},
    "phase20_1R_readiness": phase_readiness, "model_test_run_this_phase": False, "formal_scoring_run": False, "winner": None,
    "phase_b_readiness": {"four_model_artifacts_available": all(tag_map.get(x) for x in ["deepseek-r1:7b", "qwen2.5-coder:7b", "gemma2:9b"]) and bool(tag_map.get(m3_tag_name),), "independent_judge_available": bool(tag_map.get("mistral-nemo:12b-instruct-2407-q4_K_M")), "bge_m3_available": bool(tag_map.get("bge-m3:latest")), "historical_e4_ready": e4_manifest.get("ready") is True, "fish_test_gold_ready": False, "formal_split_ready": False, "m3_config_consistent": False, "metric_score_spec_unambiguous": False, "production_http_smoke": "not tested"},
}
jdump("evaluation_environment_readiness.json", env)

# Disk scan reads and hashes accessible files only; permission denied directories are retained as explicit unknowns.
baseline_obj = loadj("reports/evaluation/final_model_selection/phase20/protected_inputs_before.json")
def find_baseline_list(obj):
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and ("sha256" in obj[0] or "path" in obj[0]): return obj
        for item in obj:
            found = find_baseline_list(item)
            if found: return found
    if isinstance(obj, dict):
        for item in obj.values():
            found = find_baseline_list(item)
            if found: return found
    return []
baseline = find_baseline_list(baseline_obj)
baseline_paths = {
    str(item.get("path") or item.get("relative_path") or item.get("file") or "").replace(chr(92), "/")
    for item in baseline
}
files, scan_errors, dir_count = [], [], 0
def scan(folder):
    global dir_count
    try:
        entries = list(os.scandir(folder)); dir_count += 1
    except Exception as exc:
        scan_errors.append({"path": str(folder.relative_to(ROOT)) if folder != ROOT else ".", "stage": "enumerate", "error": f"{type(exc).__name__}: {exc}"}); return
    for entry in entries:
        path = Path(entry.path)
        try:
            if path == OUT or OUT in path.parents: continue
            if entry.is_symlink():
                scan_errors.append({"path": str(path.relative_to(ROOT)), "stage": "symlink_skipped", "error": "not followed"}); continue
            if entry.is_dir(follow_symlinks=False): scan(path)
            elif entry.is_file(follow_symlinks=False):
                try: files.append((path, entry.stat(follow_symlinks=False)))
                except Exception as exc: scan_errors.append({"path": str(path.relative_to(ROOT)), "stage": "stat", "error": f"{type(exc).__name__}: {exc}"})
        except Exception as exc:
            scan_errors.append({"path": str(path.relative_to(ROOT)), "stage": "classify", "error": f"{type(exc).__name__}: {exc}"})
scan(ROOT)
hashes, hash_errors = {}, []
with ThreadPoolExecutor(max_workers=4) as pool:
    future_map = [pool.submit(hash_worker, x) for x in files]
    for future in as_completed(future_map):
        path, digest, error = future.result()
        rel = str(path.relative_to(ROOT))
        if digest: hashes[rel] = digest
        if error: hash_errors.append({"path": rel, "error": error})

folder_size, folder_count, inaccessible = Counter(), Counter(), Counter()
file_rows, safe_cache, archived, review, protected = [], [], [], [], []
total_bytes = 0
for path, stat in files:
    rel = str(path.relative_to(ROOT)); parts = Path(rel).parts
    bucket = parts[0] if len(parts) > 1 else "<root files>"
    size = stat.st_size; total_bytes += size; folder_size[bucket] += size; folder_count[bucket] += 1
    lower = rel.lower().replace("\\", "/"); name = path.name.lower(); digest = hashes.get(rel)
    if "/__pycache__/" in "/" + lower or name.endswith(".pyc") or "/.pytest_cache/" in "/" + lower:
        label, reason = "safe_cache", "rebuildable bytecode/test cache candidate; not deleted"
        safe_cache.append({"path": rel, "size_bytes": size, "sha256": digest, "reason": reason})
    elif rel.replace(chr(92), "/") in baseline_paths:
        label, reason = "protected", "explicit member of historical frozen baseline"
        protected.append({"path": rel, "size_bytes": size, "mtime": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"), "sha256": digest, "classification": label, "reason": reason})
    elif lower.startswith("reports/") and not any(x in lower for x in ["protected", "phase20", "phase19", "phase18", "phase17", "phase16", "phase15"]):
        label, reason = "archive_candidate", "nonbaseline historical report candidate; archive only after verified copy; not moved"
        archived.append({"path": rel, "size_bytes": size, "sha256": digest, "reason": reason})
    elif lower.startswith(("data/", "my_data/", "rag_assets/", "reports/", "research_staging/", "fish test/", ".venv/", ".venv-ragas/", ".venv-reranker/", "src/", "tests/", "config/", "configs/", "prompts/", "schemas/", "scripts/", "docs/")) or name in {"rag_store.sqlite3", "app.py", "rag_core.py", "build_index.py", "chat.py"}:
        label, reason = "protected", "production/source/frozen/research artifact protected in Phase A"
        protected.append({"path": rel, "size_bytes": size, "mtime": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"), "sha256": digest, "classification": label, "reason": reason})
    else:
        label, reason = "requires_review", "purpose/rebuildability unknown"
        review.append({"path": rel, "size_bytes": size, "sha256": digest, "reason": reason})
    file_rows.append({"path": rel, "size_bytes": size, "mtime": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"), "sha256": digest, "classification": label, "reason": reason})
for error in scan_errors:
    parts = Path(error["path"]).parts; inaccessible[parts[0] if parts else "<root files>"] += 1
folder_rows = [{"first_level_folder": key, "accessible_file_count": folder_count[key], "accessible_size_bytes": folder_size[key], "accessible_size_gb_decimal": round(folder_size[key] / 1e9, 6), "accessible_size_gib": round(folder_size[key] / 1024**3, 6), "scan_errors_beneath": inaccessible[key], "size_status": "lower_bound_if_scan_errors"} for key in sorted(set(folder_size) | set(folder_count) | set(inaccessible))]
csv_write("disk_usage_by_folder.csv", ["first_level_folder", "accessible_file_count", "accessible_size_bytes", "accessible_size_gb_decimal", "accessible_size_gib", "scan_errors_beneath", "size_status"], folder_rows)
largest = sorted(file_rows, key=lambda x: x["size_bytes"], reverse=True)[:100]
csv_write("largest_files.csv", ["rank", "path", "size_bytes", "size_gb_decimal", "size_gib", "mtime", "sha256", "classification"], [{"rank": i+1, **row, "size_gb_decimal": round(row["size_bytes"]/1e9, 6), "size_gib": round(row["size_bytes"]/1024**3, 6)} for i, row in enumerate(largest)])
by_hash = defaultdict(list)
for row in file_rows:
    if row["sha256"]: by_hash[row["sha256"]].append(row)
dup_rows = []
for digest, group in by_hash.items():
    if len(group) > 1:
        for row in group:
            dup_rows.append({"sha256": digest, "path": row["path"], "size_bytes": row["size_bytes"], "duplicate_group_count": len(group), "other_paths": " | ".join(x["path"] for x in group if x["path"] != row["path"])})
csv_write("duplicate_files.csv", ["sha256", "path", "size_bytes", "duplicate_group_count", "other_paths"], dup_rows)
current = {r["path"].replace(chr(92), "/"): r for r in file_rows}
protected_recheck = []
for item in baseline:
    rel = str(item.get("path") or item.get("relative_path") or item.get("file") or "").replace("\\", "/")
    expected = item.get("sha256") or item.get("SHA256")
    if not rel: continue
    actual = current.get(rel)
    status = "unchanged" if actual and expected and actual["sha256"] == expected else ("missing_or_unreadable" if not actual or not actual["sha256"] else "changed")
    protected_recheck.append({"path": rel, "expected_sha256": expected, "current_sha256": actual.get("sha256") if actual else None, "status": status})
safe_bytes = sum(x["size_bytes"] for x in safe_cache); archive_bytes = sum(x["size_bytes"] for x in archived)
jdump("cleanup_candidate_manifest.json", {"created_at": STAMP, "deletion_performed": False, "movement_performed": False,
    "safe_cache": {"files": len(safe_cache), "bytes": safe_bytes, "gb": round(safe_bytes/1e9, 6), "items": safe_cache, "action": "candidate only; not removed"},
    "archive_candidate": {"files": len(archived), "bytes": archive_bytes, "gb": round(archive_bytes/1e9, 6), "items": archived, "action": "candidate only; not moved"},
    "requires_review": {"files": len(review), "bytes": sum(x["size_bytes"] for x in review), "items": review[:500], "truncated": len(review)>500},
    "inaccessible_directories": [x for x in scan_errors if x["stage"] == "enumerate"], "hash_errors": hash_errors,
    "recommendation": "No historical reports, models, indices, database or source files are safe to remove based on this inventory alone."})
jdump("disk_inventory_scan.json", {"created_at": STAMP, "accessible_files": len(files), "enumerated_directories": dir_count, "accessible_bytes": total_bytes, "accessible_gb_decimal": round(total_bytes/1e9, 6), "accessible_gib": round(total_bytes/1024**3, 6), "scan_error_count": len(scan_errors), "hash_error_count": len(hash_errors), "scan_errors": scan_errors[:400], "hash_errors": hash_errors[:100], "scope": "lower bound; inaccessible trees excluded; symlinks not followed; this output directory excluded"})
jdump("protected_files_manifest.json", {"created_at": STAMP, "classification_rule": "source, production, indices, models, databases, history and research materials are protected; regenerable bytecode/cache candidates are separate", "accessible_protected_file_count": len(protected), "protected_files": protected, "historical_636_recheck": {"baseline_path": "reports/evaluation/final_model_selection/phase20/protected_inputs_before.json", "baseline_entry_count": len(baseline), "unchanged": sum(x["status"] == "unchanged" for x in protected_recheck), "changed": sum(x["status"] == "changed" for x in protected_recheck), "missing_or_unreadable": sum(x["status"] == "missing_or_unreadable" for x in protected_recheck), "entries": protected_recheck}, "filesystem_scan_limited": bool(scan_errors or hash_errors)})
try:
    stat = (ROOT/"rag_store.sqlite3").stat()
    sqlite = {"path": "rag_store.sqlite3", "size_bytes": stat.st_size, "mtime": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"), "sha256": hashes.get("rag_store.sqlite3"), "status": "readable"}
except Exception as exc:
    sqlite = {"path": "rag_store.sqlite3", "status": "error", "error": f"{type(exc).__name__}: {exc}"}
jdump("compatibility.json", {"created_at": STAMP, "fish_test_files_modified": False, "historical_reports_modified": False, "production_models_indices_modified": False, "sqlite": sqlite, "historical_636_recheck": {"checked": len(protected_recheck), "unchanged": sum(x["status"] == "unchanged" for x in protected_recheck), "changed": sum(x["status"] == "changed" for x in protected_recheck), "missing_or_unreadable": sum(x["status"] == "missing_or_unreadable" for x in protected_recheck)}, "scan_errors": len(scan_errors), "note": "Some old pytest/temp paths could not be read due PermissionError/WinError 5; no model, production, retrieval, HTTP or pytest runs were performed."})

summary = f"""# Phase A — Fish Test、研究規格與磁碟盤點

盤點時間：{STAMP}

## 題庫

- {len(workbooks)} 份 XLSX、{len(inventory)} 個工作表、{len(questions)} 個完整題目登錄；題目庫與測試資料表是同題鏡像，未加倍計數。
- 有題幹與答案候選：{complete}；來源 ID/網址有連結：{source_linked}；事實 ID 可解析：{fact_linked}。
- 正式評分適用題數：0；探索性候選：{len(questions)}。答案尚未獨立驗證，來源沒有逐題頁碼/span/checksum，未映射 frozen E4，也沒有正式 Selection/Holdout。
- 魚種分布：{json.dumps(dict(fish_counts), ensure_ascii=False)}。
- 六類別推定分布：{json.dumps(dict(category_counts), ensure_ascii=False)}。工作簿的 category 欄是 Direct/Paraphrase/Contextual，不是六大主題類別；以上分類是依題幹和主題推定。
- 題庫/測試表資料不一致：{len(mirror_mismatch)}；完全重複題組：{len(exact_dups)}；同魚種疑似相似題對：{len(near)}（相似度門檻 0.82，需人工複核）。
- split 標籤：{json.dumps(dict(Counter(q['split_label'] for q in questions)), ensure_ascii=False)}。

## 研究計畫與指標

- 沒找到獨立研究計畫書；可用的是 Phase 16–20 文件與程式規格。
- Phase 20 子權重：Faithfulness、Answer Relevance、Arithmetic Accuracy、結構化輸出 IFR 各 0.175；TTFT、TPS、memory_pressure 各 0.10；Context Precision@5 為 0 權重的共用 Retrieval 指標。
- 程式先加總內層 Quality=0.70、Edge=0.30，接著又乘 0.70/0.30，理論最高總分為 0.58；正規化後相對比重約 Quality 84.48%、Edge 15.52%。正式評分前需核定此差異。
- RAM/VRAM 沒有個別總分權重；memory_pressure 的計算式尚未找到。程式的 IFR 衡量結構化輸出有效比例，不等於完整語意指令遵循率。

## 模型與檢索

- Ollama、本機模型標籤、Judge、BGE-M3、Reranker、GPU、Python 環境見 evaluation_environment_readiness.json。
- M3 權重確認為 DeepSeek-R1-Distill-Llama-8B（Llama/Q4_K_M）；但 Phase 20 設定使用 deepseek-r1:8b，而本機此標籤為 Qwen3 家族，須先對齊。
- RTX 4060 已辨識；顯存數字僅為一次唯讀快照。
- Historical E4 manifest 為 ready、索引未重建，可供唯讀檢索；fish test 尚無題目層級的合格證據映射，因此尚不能稱為公平四模型比較。

## 磁碟及清理

- 可讀檔案 {len(files):,} 個、目錄 {dir_count:,} 個；可讀容量 {total_bytes/1e9:.3f} GB（{total_bytes/1024**3:.3f} GiB）。部分路徑因存取拒絕無法列舉，因此是下限。
- 列舉錯誤 {len(scan_errors)}、雜湊錯誤 {len(hash_errors)}。最大第一層資料夾：{', '.join(f"{x['first_level_folder']} {x['accessible_size_gib']:.3f} GiB" for x in sorted(folder_rows, key=lambda z:z['accessible_size_bytes'], reverse=True)[:5])}。
- 可重建快取候選 {len(safe_cache)} 個檔、{safe_bytes/1e9:.6f} GB；歷史報表封存候選 {len(archived)} 個檔、{archive_bytes/1e9:.6f} GB。本輪沒有清除或搬動檔案。
- 模型、索引、資料庫、原始資料及歷史報表列為 protected；其他用途不明項目列 requires_review。

## Phase B 前置條件

1. 獨立核驗每題答案、來源版本、原文定位、使用依據及魚種/類別適用性。
2. 建立按知識群組隔離的正式 Selection/Holdout。
3. 對齊 M3 runtime 標籤與實際 Llama 權重。
4. 核定權重公式、memory_pressure、Logical Accuracy 與語意 Instruction Following 定義。
5. 確認每題能在同一 frozen E4 流程下公平比較。
6. 本輪未執行模型評分、檢索 benchmark、Production HTTP smoke、完整 pytest 或清理。

原始 fish test 檔案未修改。
"""
(OUT / "phase_a_summary.md").write_text(summary, encoding="utf-8")

validation = {}
for path in OUT.iterdir():
    try:
        if path.suffix == ".json": json.loads(path.read_text(encoding="utf-8"))
        elif path.suffix == ".jsonl":
            for line in path.read_text(encoding="utf-8").splitlines():
                if line: json.loads(line)
        elif path.suffix == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as f: list(csv.reader(f))
        validation[path.name] = {"status": "valid", "size_bytes": path.stat().st_size}
    except Exception as exc: validation[path.name] = {"status": "invalid", "error": f"{type(exc).__name__}: {exc}"}
jdump("output_validation.json", validation)
print(json.dumps({"output": str(OUT), "workbooks": len(workbooks), "sheets": len(inventory), "questions": len(questions), "complete": complete, "formal_ready": 0, "categories": dict(category_counts), "species": dict(fish_counts), "mirror_mismatches": len(mirror_mismatch), "exact_dup_groups": len(exact_dups), "near_pairs": len(near), "disk_files": len(files), "disk_dirs": dir_count, "disk_gb": round(total_bytes/1e9, 3), "scan_errors": len(scan_errors), "hash_errors": len(hash_errors), "safe_cache_files": len(safe_cache), "safe_cache_gb": round(safe_bytes/1e9, 6), "protected_baseline_entries": len(protected_recheck), "baseline_unchanged": sum(x["status"] == "unchanged" for x in protected_recheck), "output_validation": validation}, ensure_ascii=False))
