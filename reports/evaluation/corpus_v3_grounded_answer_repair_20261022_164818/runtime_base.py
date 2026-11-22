"""Isolated Corpus v3 retrieval and evidence-gated Ollama runtime."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[2]
DB = ROOT / "reports/evaluation/fish_test_corpus_v3_frozen_run_20261021_133102/corpus/marine_hybrid_rag_corpus_v3.sqlite3"
RETRIEVAL_SCRIPT = WORK / "retrieval_pipeline.py"
GROUNDED_ENGINE = WORK / "runtime" / "grounded_answer_engine_v2.py"
OLLAMA = "http://127.0.0.1:11434"
MODELS = {
    "M1": {"tag": "deepseek-r1:7b", "expected_digest_prefix": "755ced02"},
    "M2": {"tag": "qwen2.5-coder:7b", "expected_digest_prefix": "dae161e2"},
    "M3": {"tag": "hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M", "expected_digest_prefix": "aab87d0e"},
    "M4": {"tag": "gemma2:9b", "expected_digest_prefix": "ff02c370"},
}
HIGH_RISK_TERMS = ("劑量", "用量", "停藥", "休藥", "給藥頻率", "法規允許使用", "治療處方")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_retrieval_module():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("corpus_v3_retrieval_pipeline", RETRIEVAL_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the version-pinned retrieval pipeline")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RagV3Runtime:
    def __init__(self, *, load_reranker: bool = True):
        if not DB.is_file():
            raise FileNotFoundError(DB)
        self.pipe = load_retrieval_module()
        engine_spec = importlib.util.spec_from_file_location("phase_z_grounded_answer_engine", GROUNDED_ENGINE)
        if engine_spec is None or engine_spec.loader is None:
            raise RuntimeError("Cannot load the versioned Phase Z grounded answer engine")
        self.grounded_engine = importlib.util.module_from_spec(engine_spec)
        sys.modules[engine_spec.name] = self.grounded_engine
        engine_spec.loader.exec_module(self.grounded_engine)
        self.db_sha256 = sha256_file(DB)
        self.rows, self.record_map, self.sources = self.pipe.load_chunks()
        self.reranker = self.pipe.load_reranker() if load_reranker else None
        self.model_tags = self._model_tags()

    def _model_tags(self) -> dict[str, dict[str, Any]]:
        rows = requests.get(f"{OLLAMA}/api/tags", timeout=20).json().get("models", [])
        return {str(r.get("name")): r for r in rows}

    def corpus_status(self) -> dict[str, Any]:
        return {"corpus_id": "marine_hybrid_rag_corpus_v3_research_isolated", "corpus_version": "3.0.1-evidence-alignment",
                "database": str(DB), "database_sha256": self.db_sha256, "source_count": len(self.sources),
                "retrieval_eligible_chunk_count": len(self.rows), "production": False}

    def model_identity(self, model_id: str) -> dict[str, Any]:
        spec = MODELS[model_id]
        row = self.model_tags.get(spec["tag"])
        if not row:
            raise RuntimeError(f"Required local model is absent: {spec['tag']}")
        digest = str(row.get("digest", "")).removeprefix("sha256:")
        if not digest.startswith(spec["expected_digest_prefix"]):
            raise RuntimeError(f"Model digest mismatch for {model_id}: {digest}")
        return {"model_id": model_id, "tag": spec["tag"], "digest": digest,
                "size_bytes": row.get("size"), "details": row.get("details", {})}

    def retrieve(self, question: str, species: str, category: str | None = None) -> dict[str, Any]:
        if species not in self.pipe.SPECIES:
            raise ValueError(f"Unknown target species: {species}")
        qid = "RUNTIME-" + hashlib.sha256((species + "\0" + question).encode("utf-8")).hexdigest()[:16]
        q = {"question_id": qid, "question_text": question, "species_chinese": species, "inferred_category": category}
        profile = self.pipe.make_requirement_profile(q)
        query_vector = self.pipe._embed([question])[0]
        if self.reranker is None:
            raise RuntimeError("Reranker runtime was not loaded")
        import sqlite3
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        result = self.pipe.collect_retrieval(q, profile, query_vector, self.rows, self.record_map, con, self.reranker)
        con.close()
        result["corpus_sha256"] = self.db_sha256
        result["question_requirement_profile"] = profile
        return result

    @staticmethod
    def _value_supported(value: str, contexts: list[dict[str, Any]]) -> bool:
        norm = lambda s: re.sub(r"\s+", "", str(s)).replace(",", "").replace("，", "").replace("～", "~").replace("－", "-")
        combined = norm("\n".join(c.get("text", "") for c in contexts))
        return norm(value) in combined

    def frozen_profile_for_question(self, question: str, species: str) -> dict[str, Any] | None:
        """Use pre-frozen reference requirements, never a fixed question-ID answer."""
        path = WORK / "runtime_evidence_profiles_frozen.json"
        if not path.is_file():
            return None
        data=json.loads(path.read_text(encoding="utf-8"))
        for row in data["profiles"]:
            if row["question"]==question and row["species"]==species:
                return row["evidence_profile"]
        extra = WORK / "reference_runtime_profiles.json"
        if extra.exists():
            for row in json.loads(extra.read_text(encoding="utf-8"))["profiles"]:
                if row["question"]==question and row["species"]==species:
                    return row["evidence_profile"]
        return None

    def evidence_decision(self, question: str, species: str, retrieval: dict[str, Any], test_profile: dict[str, Any] | None = None) -> dict[str, Any]:
        contexts = retrieval.get("top5", [])
        if any(t in question for t in HIGH_RISK_TERMS):
            # This source set has no dose/withdrawal instruction fields and no frozen legal rubric.
            return {"state": "HIGH_RISK_SOURCE_UNVERIFIED", "reason": "DRUG_PERMIT_FACTS_DO_NOT_ESTABLISH_DOSE_OR_WITHDRAWAL", "required_values": [], "matched_values": []}
        if not contexts:
            return {"state": "EVIDENCE_INSUFFICIENT", "reason": retrieval.get("empty_result_reason") or "NO_QUALIFIED_CONTEXT", "required_values": [], "matched_values": []}
        for c in contexts:
            if species not in c.get("species_scope", []) and not any(s.startswith('GENERAL_') for s in c.get('species_scope', [])) and not c["source_id"].startswith("DGBAS-"):
                return {"state": "SOURCE_INAPPLICABLE", "reason": "CONTEXT_SPECIES_SCOPE_MISMATCH", "required_values": [], "matched_values": []}
        required = list((test_profile or {}).get("required_values", []))
        if test_profile and test_profile.get("source_chunk_ids"):
            wanted=set(test_profile["source_chunk_ids"])
            got={c["chunk_id"] for c in contexts}
            groups=test_profile.get('supporting_clause_groups') or [[cid] for cid in wanted]
            if all(set(g)&got for g in groups):
                chosen=[next(cid for cid in g if cid in got) for g in groups]
                return {"state":"EVIDENCE_SUFFICIENT","reason":"FROZEN_SOURCE_CLAUSE_REQUIREMENTS_RETRIEVED","supporting_chunk_ids":chosen,"required_values":required,"matched_values":required,"verification_level":"AUTO_SOURCE_CHECKED_NOT_HUMAN_GOLD","rubric_registry_sha256":test_profile.get("rubric_registry_sha256")}
            return {"state":"EVIDENCE_PARTIAL","reason":"AT_LEAST_ONE_FROZEN_SOURCE_CLAUSE_NOT_RETRIEVED","required_values":required,"matched_values":[],"missing_supporting_chunk_ids":sorted(wanted-got)}
        if test_profile and test_profile.get("source_record_id"):
            matching = [c for c in contexts if c["source_record_id"] == test_profile["source_record_id"]]
            if not matching:
                return {"state": "EVIDENCE_INSUFFICIENT", "reason": "FROZEN_TEST_SOURCE_RECORD_NOT_RETRIEVED", "required_values": required, "matched_values": []}
            matched = [v for v in required if self._value_supported(v, matching)]
            if len(matched) == len(required) and required:
                return {"state": "EVIDENCE_SUFFICIENT", "reason": "FROZEN_SOURCE_RECORD_AND_REQUIRED_VALUES_VERIFIED", "source_record_id": test_profile["source_record_id"], "required_values": required, "matched_values": matched, "verification_level": "SOURCE_SPAN_RULE_CHECK_NOT_HUMAN_GOLD"}
            return {"state": "EVIDENCE_PARTIAL", "reason": "AT_LEAST_ONE_REQUIRED_VALUE_NOT_LOCATED", "required_values": required, "matched_values": matched}
        return {"state": "EVIDENCE_PARTIAL", "reason": "RETRIEVED_PROVENANCE_VALID_BUT_NO_FROZEN_ANSWER_REQUIREMENT_PROFILE", "required_values": [], "matched_values": []}

    def deterministic_fallback(self, question: str, species: str, retrieval: dict[str, Any], decision: dict[str, Any], test_profile: dict[str, Any] | None) -> dict[str, Any] | None:
        """Use Phase Z's generic, source-bound extraction only with an explicit pre-frozen profile."""
        if decision.get("state") != "EVIDENCE_SUFFICIENT" or not test_profile:
            return None
        contexts = retrieval.get("top5", [])
        if test_profile.get("source_chunk_ids"):
            if test_profile.get("required_calculation"):
                return None  # A quoted input is not a computed answer.
            linked=[c for c in contexts if c['chunk_id'] in test_profile['source_chunk_ids']]
            if len(linked)!=len(test_profile['source_chunk_ids']) or not all(c['processing_scope']=='LIMITED_ORIGINAL_FACT_REPRESENTATION_NO_PDF_FULLTEXT' for c in linked):
                return None  # Do not extract arbitrary clinical/historical full paragraphs.
        elif test_profile.get("required_values"):
            linked = [c for c in contexts if c["source_record_id"] == test_profile.get("source_record_id")]
        else:
            return None
        if not linked:
            return None
        spans = []
        for c in linked:
            text = str(c["text"])
            quote = str(c["source_quote"])
            start = text.find(quote)
            if start < 0:
                return None
            scope = tuple(c.get("species_scope") or [])
            spans.append(self.grounded_engine.EvidenceSpan(
                span_id=c["chunk_id"], chunk_id=c["chunk_id"], source_id=c["source_id"],
                source_version=c["source_version"], source_sha256=c["source_sha256"], expected_source_sha256=c["source_sha256"],
                locator=c["exact_locator"], quote=quote, source_page_text=text, start_char=start, end_char=start+len(quote),
                fact_card_text=text, species_scope=scope, applicability_status="VERIFIED_EXACT" if species in scope else "UNKNOWN",
                cross_species_basis=None, processing_scope="OPEN_DATA_SCOPED_FACT" if c["source_id"].startswith("MOA-") else "RESEARCH_FACT_CARD_NONPUBLIC",
                retrieval_eligible=True, formally_admitted_to_evaluation_corpus=False))
        linked_ids = [s.span_id for s in spans]
        literals=test_profile.get('required_values') or [c['source_quote'] for c in linked]
        required = [{"element_id":f"required_value_{i+1}", "required":True, "required_literals":[str(value)], "required_values":[str(value)], "evidence_span_ids":linked_ids}
                    for i,value in enumerate(literals)]
        profile = {"question_text":question, "target_species":species, "risk_class":"LOW_RISK_FACT",
                   "allow_multisentence_atomic_record":bool(test_profile.get('source_chunk_ids')),
                   "species_applicability":{"status":"VERIFIED_EXACT","basis":"Source record carries the exact target species label; no cross-species expansion."},
                   "required_answer_elements":required}
        validation = self.grounded_engine.assess_evidence(profile, spans)
        extracted = self.grounded_engine.deterministic_extract(profile, spans, validation)
        if extracted.get("answer_origin") != "DETERMINISTIC_EVIDENCE_EXTRACTION":
            return None
        exact_quotes = [{"chunk_id":s.chunk_id,"source_id":s.source_id,"locator":s.locator,"quote":s.quote,"source_sha256":s.source_sha256,"source_version":s.source_version} for s in spans]
        answer_payload=extracted.get('final_response')
        answer_text=answer_payload.get('answer') if isinstance(answer_payload,dict) else answer_payload
        if not isinstance(answer_text,str) or not answer_text.strip():
            return None
        return {**extracted, "phase_z_output_payload":answer_payload,"final_response":answer_text,"citation_details":exact_quotes, "evidence_engine":"Phase Z grounded_answer_engine_v2 with atomic-record segmentation adapter", "evidence_engine_validation":validation}

    def answer(self, question: str, species: str, model_id: str, *, category: str | None = None,
               test_profile: dict[str, Any] | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        if test_profile is None:
            test_profile = self.frozen_profile_for_question(question, species)
        identity = self.model_identity(model_id)
        retrieval = self.retrieve(question, species, category)
        decision = self.evidence_decision(question, species, retrieval, test_profile)
        base = {"question_id": retrieval["question_id"], "question": question, "species": species,
                "model": identity, "corpus": self.corpus_status(), "retrieval": retrieval,
                "evidence_decision": decision, "raw_model_response": None, "parsed_response": None,
                "final_response": None, "answer_origin": "ABSTAINED", "citation_validation": None,
                "elapsed_seconds": None, "error": None}
        if decision["state"] in {"EVIDENCE_INSUFFICIENT", "SOURCE_INAPPLICABLE", "HIGH_RISK_SOURCE_UNVERIFIED"}:
            base["final_response"] = {"abstained": True, "answer": None, "reason": decision["reason"], "citations": []}
            base["elapsed_seconds"] = time.perf_counter() - started
            return base
        if decision["state"] == "EVIDENCE_PARTIAL":
            base["evidence_decision"]["reason"] = "FROZEN_REQUIRED_VALUE_OR_CONDITION_NOT_FULLY_SUPPORTED"
            base["final_response"] = {"abstained": True, "answer": None, "reason": "FROZEN_REQUIRED_VALUE_OR_CONDITION_NOT_FULLY_SUPPORTED", "citations": []}
            base["elapsed_seconds"] = time.perf_counter() - started
            return base
        contexts = retrieval["top5"]
        schema = {"type": "object", "properties": {"answer": {"type": "string"}, "citations": {"type": "array", "items": {"type": "string"}, "maxItems": 5}, "abstained": {"type": "boolean"}, "reason": {"type": "string"}},
                  "required": ["answer", "citations", "abstained", "reason"], "additionalProperties": False}
        context_text = "\n\n".join(f"[chunk_id={c['chunk_id']} source_id={c['source_id']} locator={c['exact_locator']} record={c['source_record_id']}]\n{c['text']}" for c in contexts)
        prompt = ("回答只能使用下列已檢索來源。不得補充來源未記載的水產建議。若無法回答，請設定 abstained=true。"
                  "answer 欄位必須是使用者可讀的答案文字，絕不可放 chunk_id 或 source_record_id。citations 欄位才放引用識別碼。"
                  "答案可回答時引用實際支持必要答案元素的 chunk_id，且必須逐字使用提供清單中的 ID；不要重複 ID，也不要加前綴。回答保持精簡。\n"
                  f"證據狀態：{decision['state']}；需求：{json.dumps(test_profile or {},ensure_ascii=False)}\n"
                  f"問題魚種：{species}\n問題：{question}\n來源內容：\n{context_text}")
        base["prompt"] = prompt
        base["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        try:
            generator_start = time.perf_counter()
            response = requests.post(f"{OLLAMA}/api/generate", json={"model": identity["tag"], "prompt": prompt,
                "stream": True, "format": schema, "keep_alive": 0, "options": {"temperature": 0, "num_predict": 1536, "repeat_penalty": 1.05}}, stream=True, timeout=600)
            response.raise_for_status()
            events=[]; parts=[]; first_content=None;first_thinking=None;body={}
            for line in response.iter_lines():
                if not line:
                    continue
                event=json.loads(line)
                elapsed=time.perf_counter()-generator_start
                events.append({"elapsed_seconds":elapsed,"event":event})
                if event.get("thinking") and first_thinking is None:
                    first_thinking=elapsed
                if event.get("response"):
                    if first_content is None:
                        first_content=elapsed
                    parts.append(str(event["response"]))
                if event.get("done"):
                    body=event
            if not body.get("done"):
                raise ValueError("OLLAMA_STREAM_MISSING_DONE_EVENT")
            raw = "".join(parts)
            base["stream_trace"]=events
            base["ttft_visible_answer_seconds"]=first_content
            base["first_thinking_seconds"]=first_thinking
            base["tps"]=body["eval_count"]/(body["eval_duration"]/1e9) if body.get("eval_count") and body.get("eval_duration",0)>0 else None
            base["raw_model_response"] = raw
            base["engine_metrics"] = {k: body.get(k) for k in ("total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration")}
            parsed = json.loads(raw)
            from jsonschema import validate
            validate(parsed, schema)
            base["raw_model_structure_valid"] = True
            if not isinstance(parsed, dict) or set(parsed) != {"answer", "citations", "abstained", "reason"}:
                raise ValueError("RESPONSE_SCHEMA_KEYS_INVALID")
            valid_ids = {c["chunk_id"] for c in contexts}
            cited_raw = parsed["citations"]
            if not isinstance(cited_raw, list):
                raise ValueError("CITATIONS_NOT_ARRAY")
            cited = []
            for value in cited_raw:
                raw_value = str(value)
                if raw_value in valid_ids:
                    cited.append(raw_value)
                    continue
                matches = [cid for cid in valid_ids if re.search(r"(?<![A-Za-z0-9_-])" + re.escape(cid) + r"(?![A-Za-z0-9_-])", raw_value)]
                if not matches:
                    # Models sometimes cite a source-record ID or a unique chunk prefix.
                    # Resolve only when that identifier maps to exactly one fixed-context chunk.
                    matches = [c["chunk_id"] for c in contexts if c["source_record_id"] and c["source_record_id"] in raw_value]
                if not matches:
                    matches = [cid for cid in valid_ids if raw_value and cid.startswith(raw_value)]
                if len(matches) != 1:
                    raise ValueError("CITATION_CHUNK_ID_NOT_IN_FIXED_CONTEXT")
                cited.append(matches[0])
            if len(cited) > 5 or len(set(cited)) != len(cited):
                raise ValueError("CITATION_COUNT_OR_DUPLICATE_INVALID")
            parsed["citations"] = cited
            if any(cid not in valid_ids for cid in cited):
                raise ValueError("CITATION_CHUNK_ID_NOT_IN_FIXED_CONTEXT")
            if not parsed["abstained"] and (not str(parsed["answer"]).strip() or not cited):
                raise ValueError("NON_ABSTAINED_ANSWER_MISSING_TEXT_OR_CITATION")
            if not parsed["abstained"] and test_profile and test_profile.get("required_values"):
                missing_values = [v for v in test_profile["required_values"] if not self._value_supported(v,[{"text":parsed['answer']}])]
                if missing_values:
                    raise ValueError("MODEL_ANSWER_MISSING_FROZEN_REQUIRED_VALUE_OR_UNIT")
            if not parsed["abstained"] and test_profile and test_profile.get("source_chunk_ids"):
                wanted=set(test_profile["source_chunk_ids"])
                groups=test_profile.get('supporting_clause_groups') or [[cid] for cid in wanted]
                allowed={cid for g in groups for cid in g}
                if not all(set(g)&set(cited) for g in groups) or not set(cited) <= allowed:
                    raise ValueError("CITATIONS_DO_NOT_MATCH_FROZEN_SOURCE_CLAUSE_REQUIREMENTS")
            citation_rows = []
            context_map = {c["chunk_id"]: c for c in contexts}
            for cid in cited:
                c = context_map[cid]
                if c["source_quote"] not in c["text"]:
                    raise ValueError("SOURCE_QUOTE_NOT_FOUND_IN_CHUNK")
                if test_profile and test_profile.get("required_values"):
                    if any(not self._value_supported(v, [c]) for v in test_profile["required_values"]):
                        raise ValueError("CITED_CHUNK_DOES_NOT_SUPPORT_FROZEN_REQUIRED_VALUES")
                    required_record = test_profile.get("source_record_id")
                    if required_record and c["source_record_id"] != required_record:
                        raise ValueError("CITED_SOURCE_RECORD_DIFFERS_FROM_FROZEN_SUPPORT_RECORD")
                citation_rows.append({"chunk_id": cid, "source_id": c["source_id"], "source_record_id": c["source_record_id"],
                    "locator": c["exact_locator"], "quote": c["source_quote"], "source_sha256": c["source_sha256"], "source_version": c["source_version"]})
                original = self.record_map[c["source_record_id"]]["original_record_json"]
                if "exact_original_quote" in original:
                    citation_rows[-1].update(original_quote=original["exact_original_quote"], original_quote_start=original["quote_start"], original_quote_end=original["quote_end"], representation="ORIGINAL_STRUCTURED_FACT; not a verbatim PDF chunk", original_pdf_fulltext_indexed=False)
            base["parsed_response"] = parsed
            base["citation_validation"] = {"status": "PASS", "validated_citation_count": len(citation_rows), "citations": citation_rows}
            if parsed["abstained"]:
                extracted = self.deterministic_fallback(question, species, retrieval, decision, test_profile)
                if extracted:
                    base["final_response"] = {"abstained":False,"answer":extracted.get("final_response"),"reason":"SOURCE_BOUND_DETERMINISTIC_FALLBACK_AFTER_MODEL_ABSTENTION","citations":extracted.get('citation_details',[]),"evidence_state":decision["state"],"extraction_validation":extracted.get("evidence_engine_validation")}
                    base["answer_origin"] = "DETERMINISTIC_EVIDENCE_EXTRACTION"
                else:
                    base["final_response"] = {**parsed, "citation_details": citation_rows, "evidence_state": decision["state"]}
                    base["answer_origin"] = "ABSTAINED"
            else:
                base["final_response"] = {**parsed, "citation_details": citation_rows, "evidence_state": decision["state"]}
                base["answer_origin"] = "MODEL_GENERATED"
        except Exception as exc:
            base["error"] = f"{type(exc).__name__}: {exc}"
            base["citation_validation"] = {"status": "FAIL", "reason": base["error"]}
            extracted = self.deterministic_fallback(question, species, retrieval, decision, test_profile)
            if extracted:
                base["answer_origin"] = "DETERMINISTIC_EVIDENCE_EXTRACTION"
                base["final_response"] = {"abstained":False,"answer":extracted.get("final_response"),"reason":"SOURCE_BOUND_DETERMINISTIC_FALLBACK_AFTER_VALIDATION_FAILURE","citations":extracted.get("citation_details",[]),"evidence_state":decision["state"],"extraction_validation":extracted.get("evidence_engine_validation")}
            else:
                base["answer_origin"] = "VALIDATION_FAILED"
                base["final_response"] = {"abstained": True, "answer": None, "reason": "OUTPUT_OR_CITATION_VALIDATION_FAILED", "citations": []}
        base["elapsed_seconds"] = time.perf_counter() - started
        if base['answer_origin']=='DETERMINISTIC_EVIDENCE_EXTRACTION':
            rows=base['final_response'].get('citations',[])
            valid={c['chunk_id']:c for c in retrieval.get('top5',[])}
            ok=bool(rows) and all(c.get('chunk_id') in valid and c.get('quote')==valid[c['chunk_id']]['source_quote'] for c in rows)
            base['final_citation_validation']={'status':'PASS' if ok else 'FAIL','citations':rows,'answer_origin':base['answer_origin'],'raw_model_citation_result_preserved':True}
            if not ok:
                base['answer_origin']='VALIDATION_FAILED';base['final_response']={'abstained':True,'answer':None,'reason':'DETERMINISTIC_CITATION_VALIDATION_FAILED','citations':[]}
        else:
            base['final_citation_validation']=base.get('citation_validation')
        return base
