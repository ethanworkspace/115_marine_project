from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
Y = ROOT / "reports/evaluation/fish_test_phase_y_20261019_165045"
V = ROOT / "reports/evaluation/fish_test_phase_v_20261018_224918"
CORPUS = V / "corpus_v3_final"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def parse_physical_page(locator: str) -> int | None:
    m = re.search(r"physical page\s+(\d+)", str(locator), re.I)
    return int(m.group(1)) if m else None


def normal(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).replace("～", "~").replace("–", "-").replace("—", "-").replace("－", "-")


def sha_or_none(path: Path) -> str | None:
    try:
        return sha256(path) if path.is_file() else None
    except OSError:
        return None


def source_usage_class(text: str) -> str:
    low = (text or "").lower()
    if "no full-text" in low or "no fulltext" in low or "no public redistribution" in low:
        return "RESEARCH_FACT_CARD_ONLY_SCOPE_RECORDED; NO_FULLTEXT_INDEX"
    return "USE_SCOPE_NOT_INDEPENDENTLY_ESTABLISHED"


def build_reference_records() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    try:
        import pymupdf
    except Exception:
        import fitz as pymupdf  # type: ignore[no-redef]
    rows = read_jsonl(Y / "reference_answer_rubrics_frozen.jsonl")
    source_registry = {r.get("source_id"): r for r in read_jsonl(CORPUS / "source_registry_v3.jsonl")}
    refs = [r for r in rows if r.get("verification_status") == "SOURCE_VERIFIED_AUTOMATED"]
    frozen: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for r in refs:
        path = Path(r["source_file"])
        if not path.is_absolute():
            path = ROOT / path
        actual = sha_or_none(path)
        page_no = parse_physical_page(r.get("exact_source_locator", ""))
        quote = str(r.get("exact_source_text_span") or "")
        page_text = ""
        page_offset: int | None = None
        page_errors: list[str] = []
        page_count = None
        if not path.is_file():
            page_errors.append("SOURCE_FILE_MISSING")
        elif actual != r.get("source_sha256_expected") or actual != r.get("source_sha256_actual"):
            page_errors.append("SOURCE_SHA256_MISMATCH")
        else:
            try:
                doc = pymupdf.open(path)
                page_count = len(doc)
                if not page_no or page_no < 1 or page_no > len(doc):
                    page_errors.append("PHYSICAL_PAGE_NOT_IN_SOURCE")
                else:
                    page_text = doc[page_no - 1].get_text()
                    page_offset = page_text.find(quote)
                    if not quote or page_offset < 0:
                        # Exact evidence must remain exact; no whitespace-only
                        # substitutions are accepted as a source quote.
                        page_errors.append("EXACT_SPAN_NOT_FOUND_ON_DECLARED_PAGE")
                doc.close()
            except Exception as exc:
                page_errors.append(f"SOURCE_PARSE_ERROR:{type(exc).__name__}:{exc}")
        species = str(r.get("species") or "")
        question = str(r.get("original_question") or "")
        # Keep the broad historical category while honoring a more specific
        # taxon explicitly named in the question (e.g. 金目鱸 within 鱸魚).
        explicit_taxa = ("金目鱸", "鞍帶石斑", "虱目魚", "吳郭魚", "烏魚", "鰻魚")
        effective_species = next((taxon for taxon in explicit_taxa if taxon in question), species)
        answer = str(r.get("expected_answer_candidate") or "")
        cat = str(r.get("category") or "")
        fact_card = str(r.get("chunk_text") or "")
        source_id = str(r.get("source_id") or "UNVERIFIED")
        # The Phase Y metadata distinguishes species-specific chapters and the
        # FA-385 multi-species advisory. Do not infer scope from a title alone.
        source_page_scope = "UNKNOWN"
        scope_evidence = []
        if page_text:
            source_species_name = {
                "烏魚": ("烏魚", "Mugil cephalus"),
                "石斑魚": ("石斑魚",),
                "鞍帶石斑": ("鞍帶石斑", "Epinephelus lanceolatus", "石斑魚"),
                "金目鱸": ("金目鱸", "Lates calcarifer"),
                "虱目魚": ("虱目魚",),
                "吳郭魚": ("吳郭魚", "羅非魚"),
                "鰻魚": ("鰻魚", "Anguilla"),
            }.get(effective_species, (effective_species,))
            if any(x and x in page_text for x in source_species_name):
                source_page_scope = "VERIFIED_IN_DECLARED_PAGE"
                scope_evidence.append("Target species label or scientific name occurs in the declared source page.")
            else:
                # The page may rely on the chapter heading for the species.
                # Use the versioned, checksum-bound source registry/title as
                # separate document-level scope evidence, not a title guess.
                source_entry = source_registry.get(source_id, {})
                document_scope = " ".join(str(source_entry.get(k) or "") for k in ("title", "usage_scope", "attribution"))
                if any(x and x in document_scope for x in source_species_name):
                    source_page_scope = "VERIFIED_IN_SOURCE_DOCUMENT_METADATA"
                    scope_evidence.append("Species label is in the checksum-bound source registry/title; the exact cited page does not repeat the label.")
                else:
                    source_page_scope = "NOT_NAMED_IN_PAGE_OR_SOURCE_METADATA"
        usage = source_usage_class(str(r.get("source_usage_basis") or ""))
        risk_class = "LOW_RISK_FACT"
        if any(k in question + answer for k in ("疾病診斷", "用藥", "劑量", "停藥", "水黴病", "感染")):
            risk_class = "DISEASE_DIAGNOSIS"
        if cat in ("Medication / Law", "Medication/Law") or any(k in question + answer for k in ("法規", "法條", "停藥期", "藥品", "劑量")):
            risk_class = "LEGAL_INTERPRETATION"
        area_match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*公頃", question)
        rate_match = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*尾\s*/\s*公頃", question)
        explicit_calc = bool(area_match and rate_match and any(k in question for k in ("對應", "總共", "合計", "計算", "多少尾")))
        if explicit_calc:
            risk_class = "DETERMINISTIC_CALCULATION"
        exact_ok = not page_errors and bool(quote) and page_offset is not None and page_text[page_offset:page_offset + len(quote)] == quote
        numbers = re.findall(r"(?<![A-Za-z0-9_])\d[\d,]*(?:\.\d+)?", answer)
        q_and_evidence_nums = set(re.findall(r"(?<![A-Za-z0-9_])\d[\d,]*(?:\.\d+)?", question + " " + quote + " " + fact_card))
        answer_numeric_supported = all(n in q_and_evidence_nums for n in numbers)
        # Arithmetic answer variants are verified below with exact decimal math.
        calculation_protocol = None
        calculation_status = "NOT_APPLICABLE"
        if explicit_calc and area_match and rate_match:
            area = Decimal(area_match.group(1).replace(",", ""))
            rate = Decimal(rate_match.group(1).replace(",", ""))
            computed = format(area * rate, "f")
            answer_total = numbers[-1] if numbers else ""
            calculation_status = "PASS" if computed == answer_total.replace(",", "") else "FAIL"
            calculation_protocol = {"operation": "Decimal multiplication", "formula": "area_ha × stocking_rate_fish_per_ha", "inputs": {"area_ha": str(area), "stocking_rate_fish_per_ha": str(rate)}, "units": "ha × fish/ha = fish", "recomputed_result": computed, "answer_value": answer_total, "tolerance": "0 fish (exact integer arithmetic)"}
            answer_numeric_supported = calculation_status == "PASS"
        # Generic comparison diagnostics are based on the wording and source
        # values, never on question IDs. They are not a substitute for a
        # domain-specific formula or an expert-validated answer key.
        asks_comparison = any(term in question for term in ("相對", "是否落在", "是否位於", "高於", "低於", "最接近", "範圍內"))
        q_values = [Decimal(x.replace(",", "")) for x in re.findall(r"(?<![A-Za-z0-9_])\d[\d,]*(?:\.\d+)?", question)]
        q_value_unit = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(°C|℃|psu|尾\s*/\s*公頃|公斤\s*/\s*立方公尺)", question, re.I)
        source_range = re.search(r"(?<![A-Za-z0-9_])(\d[\d,]*(?:\.\d+)?)\s*(?:–|—|~|～|至|到|- )\s*(\d[\d,]*(?:\.\d+)?)\s*(°C|℃|psu|尾\s*/\s*公頃|公斤\s*/\s*立方公尺)", quote, re.I)
        if asks_comparison and q_value_unit and source_range and calculation_status == "NOT_APPLICABLE":
            q_unit = q_value_unit.group(2).casefold().replace("℃", "°c").replace(" ", "")
            src_unit = source_range.group(3).casefold().replace("℃", "°c").replace(" ", "")
            if q_unit != src_unit:
                q_value_unit = None
        if asks_comparison and q_value_unit and source_range and calculation_status == "NOT_APPLICABLE":
            value = Decimal(q_value_unit.group(1).replace(",", ""))
            lower, upper = (Decimal(x.replace(",", "")) for x in source_range.groups()[:2])
            calculation_status = "PASS" if lower <= value <= upper else "FAIL"
            calculation_protocol = {
                "operation": "Generic interval membership diagnostic",
                "method": "Extract a value from the question and a unit-bound interval from the cited source span; compare inclusively.",
                "value": str(value), "interval": [str(lower), str(upper)], "unit": source_range.group(3),
                "tolerance": "exact Decimal interval comparison", "domain_formula_claim": False,
            }
        source_species_ok = source_page_scope in {"VERIFIED_IN_DECLARED_PAGE", "VERIFIED_IN_SOURCE_DOCUMENT_METADATA"}
        status = "SOURCE_VERIFIED_AUTOMATED" if exact_ok and source_species_ok and answer_numeric_supported and not page_errors else "PARTIALLY_SUPPORTED"
        if risk_class == "DISEASE_DIAGNOSIS" and status == "SOURCE_VERIFIED_AUTOMATED":
            status = "SOURCE_VERIFIED_AUTOMATED_HIGH_RISK_NO_AUTO_EXTRACTION"
        row = {
            "question_id": r["question_id"], "species": species, "effective_target_species_from_question": effective_species, "category": cat,
            "original_question": question, "source_id": source_id, "source_title": r.get("source_title"),
            "source_file": str(path), "source_version": r.get("source_version"),
            "source_sha256_expected": r.get("source_sha256_expected"), "source_sha256_actual": actual,
            "sha256_match": actual == r.get("source_sha256_expected"), "physical_page": page_no,
            "exact_source_locator": r.get("exact_source_locator"), "exact_evidence_span": quote,
            "span_start_char": page_offset, "span_end_char": page_offset + len(quote) if page_offset is not None else None,
            "span_exact_on_declared_page": exact_ok, "page_text_sha256": hashlib.sha256(page_text.encode("utf-8")).hexdigest() if page_text else None,
            "fact_card_text": fact_card, "required_answer_elements": r.get("required_answer_elements", []),
            "expected_answer": answer, "answer_numeric_values_supported": answer_numeric_supported,
            "formula_or_protocol": calculation_protocol, "deterministic_calculation_status": calculation_status,
            "species_page_scope_status": source_page_scope, "species_scope_evidence": scope_evidence, "risk_class": risk_class,
            "source_usage_basis": r.get("source_usage_basis"), "source_use_status": usage,
            "full_text_indexing_claimed": False, "formal_corpus_admission": False,
            "verification_status": status, "human_gold_status": "NOT_HUMAN_GOLD",
            "limitations": r.get("limitations"), "prior_candidate_rubric_sha256": r.get("rubric_sha256"),
            "new_freeze_created_at": datetime.now(timezone.utc).isoformat(),
        }
        canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        row["phase_z_reference_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        frozen.append(row)
        by_id[row["question_id"]] = {"row": row, "page_text": page_text}
    write_jsonl(OUT / "reference_answers_frozen.jsonl", frozen)
    return frozen, by_id


def build_rubrics(refs: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [r for r in refs if r["verification_status"] == "SOURCE_VERIFIED_AUTOMATED"]
    rows = []
    for r in refs:
        rubric = {
            "question_id": r["question_id"],
            "version": "phase_z_rubric_v1",
            "source_reference_sha256": r["phase_z_reference_sha256"],
            "required_answer_elements": r["required_answer_elements"],
            "source_id": r["source_id"], "source_version": r["source_version"],
            "evidence_locator": r["exact_source_locator"], "evidence_span": r["exact_evidence_span"],
            "answer_key": r["expected_answer"],
            "logical_rubric": {
                "must_match_source_scope": True,
                "must_include_required_values_or_conditions": r["required_answer_elements"],
                "must_not_generalize_beyond_source_scope": True,
                "incorrect_if": ["unsupported_species_transfer", "invented numerical value", "missing required condition"],
                "assessment_status": "AUTO_SOURCE_CHECKED_ONLY" if r["verification_status"] == "SOURCE_VERIFIED_AUTOMATED" else "NOT_EVALUABLE",
            },
            "arithmetic_protocol": r["formula_or_protocol"],
            "arithmetic_status": r["deterministic_calculation_status"],
            "expected_abstention": r["verification_status"] != "SOURCE_VERIFIED_AUTOMATED" or r["risk_class"] in {"DISEASE_DIAGNOSIS", "MEDICATION", "WITHDRAWAL_PERIOD", "LEGAL_INTERPRETATION"},
            "rubric_status": "FROZEN_AUTO_SOURCE_CHECKED" if r["verification_status"] in {"SOURCE_VERIFIED_AUTOMATED", "SOURCE_VERIFIED_AUTOMATED_HIGH_RISK_NO_AUTO_EXTRACTION"} else "NOT_EVALUABLE",
            "not_human_gold": True,
        }
        rows.append(rubric)
    write_jsonl(OUT / "evaluation_rubrics_frozen.jsonl", rows)
    summary = {
        "version": "phase_z_rubric_v1", "freeze_created_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_before_phase_z_generator_calls": True, "candidate_count": len(rows),
        "source_verified_automated_count": sum(r["verification_status"] == "SOURCE_VERIFIED_AUTOMATED" for r in refs),
        "high_risk_source_checked_but_auto_extraction_blocked": sum(r["verification_status"] == "SOURCE_VERIFIED_AUTOMATED_HIGH_RISK_NO_AUTO_EXTRACTION" for r in refs),
        "not_evaluable_count": sum(r["verification_status"] == "PARTIALLY_SUPPORTED" for r in refs),
        "human_gold_count": 0, "method": "Before new model calls; based only on original question, local source PDF, exact page span, existing researcher-authored fact card, and deterministic calculations.",
        "formal_accuracy_claim": False,
    }
    write_json(OUT / "evaluation_rubrics_frozen.json", summary)
    return summary


def make_independent_tests(by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    # New question IDs and formulations, frozen before any Phase Z call. The
    # underlying source knowledge has appeared in the historic corpus, so this
    # is operationally independent from prompt tuning, not a pristine holdout.
    templates = [
        ("Z-IND-MULLET-AGE2-RATE", "烏魚", "Fact", "依水產試驗所技術手冊17的烏魚章，2齡以上的建議放養密度是多少？", "FT-mullet-Q02", ["5,000", "6,000", "每公頃"], "手冊記載，烏魚2齡以上建議每公頃5,000–6,000尾。"),
        ("Z-IND-MILKFISH-WINTER-DENSITY", "虱目魚", "Climate / Cold", "漁業署防寒須知對越冬溝內虱目魚密度提出什麼上限？", "FT-milkfish-Q04", ["1.3", "公斤", "立方公尺"], "虱目魚在越冬溝內的建議密度為每立方公尺1.3公斤以下。"),
        ("Z-IND-GROUPER-TEMP-RANGE", "石斑魚", "Water Quality", "依手冊所指的石斑魚組別，最適成長及存活水溫範圍為何？", "FT-grouper-Q01", ["25", "30", "℃"], "手冊所指的石斑魚組別，最適成長及存活水溫為25–30°C。"),
        ("Z-IND-GOLD-SEABASS-TEMP", "金目鱸", "Water Quality", "依金目鱸章，最佳成長水溫的上下界是多少？", "FT-seabass-Q01", ["28", "32", "℃"], "金目鱸最佳成長水溫為28–32°C。"),
        ("Z-IND-TILAPIA-COLD-THRESHOLD", "吳郭魚", "Climate / Cold", "防寒須知記載水溫低於何值時應採緊急措施？", "FT-tilapia-Q10", ["15", "℃"], "水溫低於15°C時，漁業署建議採取緊急措施，例如加溫。"),
        ("Z-IND-MULLET-AGE1-RATE", "烏魚", "Fact", "手冊對烏魚1齡養殖列出的每公頃放養密度約為多少？", "FT-mullet-Q01", ["10,000", "20,000", "尾/公頃"], "手冊記載，烏魚1齡每公頃約可放養1–2萬尾。"),
        ("Z-IND-SEABASS-SALINITY", "金目鱸", "Water Quality", "金目鱸章建議的較佳鹽度下限是多少？", "FT-seabass-Q03", ["5", "psu"], "手冊建議金目鱸養殖鹽度維持5 psu以上較佳。"),
    ]
    tests = []
    for test_id, species, category, question, refid, literals, answer_text in templates:
        source = by_id[refid]["row"]
        scope = source["species_page_scope_status"]
        required_values = [x for x in literals if re.search(r"\d", str(x))]
        nonnumeric_literals = [str(x) for x in literals if not re.search(r"\d", str(x))]
        literal_groups = []
        if any(x in " ".join(nonnumeric_literals) for x in ("尾", "公頃")):
            literal_groups.append(["尾/公頃", "尾 / 公頃", "每公頃"])
        if any(x in " ".join(nonnumeric_literals) for x in ("公斤", "立方公尺")):
            literal_groups.append(["公斤/立方公尺", "公斤 / 立方公尺", "每立方公尺", "kg/m3", "kg/m³"])
        if any(x in " ".join(nonnumeric_literals) for x in ("℃", "°C")):
            literal_groups.append(["℃", "°C"])
        if any("psu" in x.lower() for x in nonnumeric_literals):
            literal_groups.append(["psu"])
        span_id = "span-" + hashlib.sha256((test_id + source["source_id"] + str(source["physical_page"])).encode()).hexdigest()[:16]
        if species == "石斑魚":
            app = {"status": "VERIFIED_GROUP", "basis": "Local page text labels the fact as the manual's grouper group; it is not a claim for every grouper species."}
        elif species == "金目鱸":
            app = {"status": "VERIFIED_EXACT", "basis": "Original page and chapter identify Lates calcarifer / 金目鱸."}
        elif source["source_id"] == "FA-385-COLD" and species not in source["exact_evidence_span"]:
            app = {"status": "VERIFIED_GROUP", "basis": "The page identifies milkfish and tilapia among tropical species; the <15°C emergency action is a general cold-weather advisory, not a species-specific physiological threshold."}
        else:
            app = {"status": "VERIFIED_EXACT", "basis": "Target species is named in the declared original source page." if scope == "VERIFIED_IN_DECLARED_PAGE" else "Source scope not sufficient; block if page does not name target."}
        risk = "LOW_RISK_FACT"
        if not source["span_exact_on_declared_page"] or scope not in {"VERIFIED_IN_DECLARED_PAGE", "VERIFIED_IN_SOURCE_DOCUMENT_METADATA"}:
            risk = "UNCLASSIFIED"
        tests.append({
            "test_id": test_id, "question_id": test_id, "question_text": question,
            "target_species": species, "category": category, "risk_class": risk,
            "species_applicability": app,
            "required_answer_elements": [{"element_id": "source_fact", "required": True, "required_literals": required_values, "required_literal_groups": literal_groups, "evidence_span_ids": [span_id]}],
            "pre_frozen_answer_text": answer_text,
            "source_reference_question_id": refid, "source_id": source["source_id"],
            "source_version": source["source_version"], "source_sha256": source["source_sha256_actual"],
            "source_locator": source["exact_source_locator"], "span_id": span_id,
            "exact_evidence_span": source["exact_evidence_span"], "fact_card_text": source["fact_card_text"],
            "processing_scope": "RESEARCH_FACT_CARD_NONPUBLIC", "full_text_indexing": False,
            "test_set_status": "FROZEN_BEFORE_PHASE_Z_GENERATOR_CALLS",
            "test_independence_limit": "New question ID and wording, but its source knowledge appeared in the previously exposed Phase V corpus / Fish Test history; not an unseen benchmark holdout.",
            "human_gold_status": "NOT_HUMAN_GOLD",
        })
    # A negative, no-evidence operational test for an uncovered species/topic.
    tests.append({
        "test_id": "Z-NEG-EEL-WATER-QUALITY", "question_id": "Z-NEG-EEL-WATER-QUALITY",
        "question_text": "鰻魚養殖的溶氧最低安全值是多少 mg/L？", "target_species": "鰻魚",
        "category": "Water Quality", "risk_class": "LOW_RISK_FACT", "species_applicability": {"status": "VERIFIED_EXACT", "basis": "No suitable source span is supplied; the guard must abstain."},
        "required_answer_elements": [{"element_id": "oxygen_threshold", "required": True, "required_literals": ["mg/L"], "evidence_span_ids": []}],
        "pre_frozen_answer_text": None, "source_reference_question_id": None, "source_id": None,
        "source_version": None, "source_sha256": None, "source_locator": None, "span_id": None,
        "exact_evidence_span": None, "fact_card_text": None, "processing_scope": None,
        "full_text_indexing": False, "test_set_status": "FROZEN_EXPECTED_ABSTENTION_NO_EVIDENCE",
        "test_independence_limit": "Operational negative test only; no reference numeric threshold is asserted.", "human_gold_status": "NOT_HUMAN_GOLD",
    })
    # Species mismatch and high-risk cases test deterministic guards, not facts.
    mismatch = dict(tests[0])
    mismatch.update({"test_id": "Z-NEG-MULLET-EVIDENCE-FOR-TILAPIA", "question_id": "Z-NEG-MULLET-EVIDENCE-FOR-TILAPIA", "question_text": "吳郭魚的1齡放養密度是多少？", "target_species": "吳郭魚", "risk_class": "LOW_RISK_FACT", "species_applicability": {"status": "VERIFIED_EXACT", "basis": "The supplied source is specific to 烏魚; no cross-species basis."}, "test_set_status": "FROZEN_EXPECTED_SCOPE_BLOCK"})
    tests.append(mismatch)
    highrisk = dict(tests[0])
    highrisk.update({"test_id": "Z-NEG-SPECIFIC-DRUG-DOSE", "question_id": "Z-NEG-SPECIFIC-DRUG-DOSE", "question_text": "某魚病應使用何種藥物及劑量？", "target_species": "烏魚", "category": "Medication / Law", "risk_class": "MEDICATION", "species_applicability": {"status": "VERIFIED_EXACT", "basis": "No product-specific authority supplied."}, "high_risk_authority_verified": False, "test_set_status": "FROZEN_EXPECTED_HIGH_RISK_BLOCK"})
    tests.append(highrisk)
    write_jsonl(OUT / "independent_test_set.jsonl", tests)
    return tests


def audit_50_sources() -> dict[str, Any]:
    try:
        import pymupdf
    except Exception:
        import fitz as pymupdf  # type: ignore[no-redef]
    rows = read_jsonl(V / "source_blocker_resolution_50.jsonl")
    results = []
    for row in rows:
        path = Path(row["local_file"])
        if not path.is_absolute():
            path = ROOT / path
        actual = sha_or_none(path)
        fmt = path.suffix.lower() if path.exists() else None
        meta: dict[str, Any] = {}
        text = ""
        pages = 0
        empty_pages = 0
        parse_error = None
        if path.is_file() and fmt == ".pdf":
            try:
                doc = pymupdf.open(path)
                pages = len(doc)
                meta = {str(k): str(v) for k, v in (doc.metadata or {}).items() if v}
                page_texts = [p.get_text() for p in doc]
                empty_pages = sum(not x.strip() for x in page_texts)
                text = "\n".join(page_texts)
                doc.close()
            except Exception as exc:
                parse_error = f"{type(exc).__name__}: {exc}"
        elif path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")[:500000]
            except Exception as exc:
                parse_error = f"{type(exc).__name__}: {exc}"
        copyright_hits = []
        for phrase in ("版權所有", "著作權所有", "copyright", "all rights reserved", "©", "Creative Commons", "CC BY", "授權條款"):
            if phrase.casefold() in text.casefold():
                copyright_hits.append(phrase)
        source_identity = "UNRESOLVED"
        if row.get("source_id") not in (None, "unverified") and row.get("publisher") not in (None, "UNVERIFIED"):
            source_identity = "PARTIALLY_IDENTIFIED"
        if path.is_file() and fmt == ".pdf" and (meta.get("title") or meta.get("author") or re.search(r"(?:出版|著作|編者|作者|農業部|水產試驗所|漁業署|行政院|ISBN|GPN)", text[:6000])):
            source_identity = "IDENTITY_EVIDENCE_IN_FILE_REQUIRES_EXTERNAL_CROSSCHECK"
        explicit_license = bool(re.search(r"Creative Commons|CC BY|CC-BY|政府資料開放授權條款", text, re.I))
        results.append({
            "source_record_id": row.get("source_record_id"), "source_id": row.get("source_id"),
            "title_recorded": row.get("title"), "local_file": str(path), "file_exists": path.is_file(),
            "sha256_expected": row.get("sha256_expected"), "sha256_actual": actual,
            "sha256_match": actual is not None and actual == row.get("sha256_expected"), "format": fmt,
            "publisher_recorded": row.get("publisher"), "official_url_recorded": row.get("official_url"),
            "document_version_recorded": row.get("document_version"), "pdf_metadata": meta,
            "page_count": pages or None, "extracted_characters": len(text), "empty_or_unextractable_pages": empty_pages if fmt == ".pdf" else None,
            "parser_error": parse_error, "source_identity_followup": source_identity,
            "explicit_license_text_found_in_file": explicit_license, "rights_notice_terms_found": copyright_hits,
            "full_text_indexing_rights": "UNVERIFIED_BLOCKED" if not explicit_license else "LICENSE_CANDIDATE_REQUIRES_PUBLICATION_LEVEL_REVIEW",
            "species_applicability": "REQUIRES_SOURCE_CONTENT_AND_EXPERT_SCOPE_CHECK",
            "version_resolution": "INTERNAL_METADATA_CANDIDATE_ONLY; official publication record not uniformly matched",
            "owner_decision": "APPROVED_FOR_PROCESSING_DECISION_ONLY", "formal_corpus_admission": False,
            "next_specific_action": "Use official publication page or explicit license evidence to reconcile document identity/version; no full-text indexing until scope is documented.",
        })
    write_jsonl(OUT / "source_blocker_review_50.jsonl", results)
    counts = Counter(x["full_text_indexing_rights"] for x in results)
    return {
        "records_reviewed": len(results), "files_present": sum(x["file_exists"] for x in results),
        "sha256_match": sum(x["sha256_match"] for x in results), "pdfs": sum(x["format"] == ".pdf" for x in results),
        "internal_publisher_or_date_metadata_extracted": sum(bool(x["pdf_metadata"].get("author") or x["pdf_metadata"].get("title") or x["pdf_metadata"].get("creationDate")) for x in results),
        "explicit_license_text_found": sum(x["explicit_license_text_found_in_file"] for x in results),
        "full_text_index_rights_unverified_or_pending": sum(x["full_text_indexing_rights"] != "VERIFIED" for x in results),
        "formal_admissions_added": 0, "status_counts": dict(counts),
        "note": "SHA-256 verifies the local file identity only; it does not establish copyright permission, current version, or species applicability.",
    }


def main() -> None:
    refs, by_id = build_reference_records()
    rubric_summary = build_rubrics(refs)
    tests = make_independent_tests(by_id)
    blocked = audit_50_sources()
    manifest = read_json(CORPUS / "corpus_v3_final_manifest.json")
    sources = read_jsonl(CORPUS / "source_registry_v3.jsonl")
    chunks = read_jsonl(CORPUS / "corpus_chunks_v3_final.jsonl")
    source_counts = Counter(x.get("source_id") for x in chunks)
    species = ["虱目魚", "吳郭魚", "石斑魚", "鱸魚", "烏魚", "鰻魚"]
    corpus_source_coverage = []
    for sp in species:
        matched = []
        for src in sources:
            if sp in str(src.get("usage_scope", "")) or sp in str(src.get("title", "")) or sp in str(src.get("species_scope", "")):
                matched.append(src.get("source_id"))
        corpus_source_coverage.append({"species": sp, "source_ids_with_explicit_name_or_scope": sorted(set(matched)), "retrieval_eligible_chunks": sum(1 for c in chunks if c.get("retrieval_eligible") and sp in str(json.loads(c.get("metadata_json") or "{}").get("species_scope", ""))), "caveat": "Corpus metadata coverage only; not a rights or answer-quality determination."})
    source_progress = {
        "phase_y_unique_source_records": 57, "distinct_sha256_source_files": 55,
        "phase_y_blocked_source_files_reexamined": blocked,
        "new_formal_source_admissions": 0, "newly_licensed_fulltext_sources": 0,
        "phase_v_corpus_version": manifest.get("corpus_version"),
        "phase_v_chunk_count": manifest.get("total_chunk_count"),
        "phase_v_retrieval_eligible_chunk_count": manifest.get("retrieval_eligible_chunk_count"),
        "chunk_count_by_source": dict(source_counts), "six_species_corpus_metadata_coverage": corpus_source_coverage,
        "alternative_official_source_candidates": [
            {"source_id": "TFRI-EEL-HEALTH-SPECIAL-8-PAGE", "official_url": "https://www.tfrin.gov.tw/ws.php?id=205", "publisher": "農業部水產試驗所", "source_metadata_verified": "Official page lists publication no. 8, title, date 2006-04-01, page last modified 2019-06-19; the page describes eel aquaculture health management.", "content_scope": "Eel health/disease management; historical publication. Use only for source-bound historical facts, not current diagnosis/treatment.", "rights_status": "TFRI page footer says copyright owned; linked website open-data declaration could not be retrieved in this environment; no full-text index permission established.", "corpus_admission": "NOT_ADMITTED"},
            {"source_id": "TFRI-EEL-FUNGAL-DISEASE-PAGE", "official_url": "https://www.tfrin.gov.tw/theme_data.php?id=190&theme=aquatic_technology", "publisher": "農業部水產試驗所", "source_metadata_verified": "Official search-indexed page identifies the article as from Special No. 8, chapter 4, author Huang Shih-ling and Chen Hsiu-nan, page length 10; content describes 1988 disease-case counts.", "content_scope": "Historical eel disease cases only; not current prevalence or treatment advice.", "rights_status": "Page rights terms not confirmed; no local source bytes/checksum in this phase.", "corpus_admission": "NOT_ADMITTED"},
            {"source_id": "FAO-GSA-2025", "official_url": "https://www.fao.org/guidelines-sustainable-aquaculture/en", "publisher": "FAO", "source_metadata_verified": "Official FAO page lists Guidelines for Sustainable Aquaculture publication dated 2025-01-20.", "content_scope": "General policy/practice guidance, not six-species numerical husbandry evidence.", "rights_status": "FAO general policy permits copying/downloading for private research/noncommercial use with attribution except where otherwise indicated; publication-level license and terms still require checking before indexing.", "corpus_admission": "NOT_ADMITTED"},
            {"source_id": "FAO-LEGACY-AQUACULTURE-WATER-PAGES", "official_url": "https://www.fao.org/4/ac415e/ac415e00.htm", "publisher": "FAO", "source_metadata_verified": "Official legacy aquaculture handbook page contains general water-quality discussion; publication is older.", "content_scope": "General water-quality concepts only; source itself warns fish requirements depend on species and life stage.", "rights_status": "FAO says older publication original licensing terms may apply; no publication-specific license verified.", "corpus_admission": "NOT_ADMITTED"},
        ],
        "researcher_action": "Keep Phase V corpus immutable. Continue using only source-bound, concise researcher-authored fact cards under the existing nonpublic scope; separate new official candidate pages from admitted/retrieval-eligible sources.",
    }
    write_json(OUT / "source_coverage_progress.json", source_progress)
    write_json(OUT / "evidence_extraction_validation.json", {
        "engine_version": "grounded_answer_engine_v2", "source_reference_count": len(refs),
        "exact_pdf_page_span_verified": sum(bool(r["span_exact_on_declared_page"]) for r in refs),
        "source_sha256_match": sum(bool(r["sha256_match"]) for r in refs),
        "species_named_on_declared_page": sum(r["species_page_scope_status"] == "VERIFIED_IN_DECLARED_PAGE" for r in refs),
        "source_verified_automated_after_recheck": sum(r["verification_status"] == "SOURCE_VERIFIED_AUTOMATED" for r in refs),
        "high_risk_source_checked_but_no_extraction": sum(r["verification_status"] == "SOURCE_VERIFIED_AUTOMATED_HIGH_RISK_NO_AUTO_EXTRACTION" for r in refs),
        "partial_or_not_evaluable": sum(r["verification_status"] == "PARTIALLY_SUPPORTED" for r in refs),
        "deterministic_calculations": {r["question_id"]: {"status": r["deterministic_calculation_status"], "protocol": r["formula_or_protocol"]} for r in refs if r["deterministic_calculation_status"] not in (None, "NOT_APPLICABLE")},
        "human_gold": 0,
        "limitations": ["Exact source spans and checksums establish traceability, not correctness by themselves.", "Fact-card-only use does not mean source full-text indexing was licensed.", "Disease, drug, and uncertain legal claims are blocked from deterministic extraction."],
    })
    write_json(OUT / "phase_z_preparation_status.json", {
        "reference_registry_frozen_before_model_calls": True,
        "rubric_registry_frozen_before_model_calls": True,
        "independent_operational_test_set_frozen_before_model_calls": True,
        "reference_count": len(refs), "test_case_count": len(tests),
        "reference_status_counts": dict(Counter(r["verification_status"] for r in refs)),
        "rubric_summary": rubric_summary,
        "test_set_hash": hashlib.sha256((OUT / "independent_test_set.jsonl").read_bytes()).hexdigest(),
        "reference_file_hash": hashlib.sha256((OUT / "reference_answers_frozen.jsonl").read_bytes()).hexdigest(),
        "rubric_file_hash": hashlib.sha256((OUT / "evaluation_rubrics_frozen.jsonl").read_bytes()).hexdigest(),
        "freeze_timestamp_utc": datetime.now(timezone.utc).isoformat(),
    })
    print(json.dumps({"references": len(refs), "tests": len(tests), "blocked_sources": blocked, "status": dict(Counter(r["verification_status"] for r in refs))}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
