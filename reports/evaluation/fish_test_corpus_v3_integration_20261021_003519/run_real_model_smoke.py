from __future__ import annotations
import datetime as dt
import json
import os
import sys
import traceback
from pathlib import Path

WORK = Path(__file__).resolve().parent
if str(WORK) not in sys.path:
    sys.path.insert(0, str(WORK))
from rag_v3_runtime import RagV3Runtime, MODELS


def main():
    runtime = RagV3Runtime(load_reranker=True)
    positive_question = "依據水產試驗所這筆烏魚資料，烏魚正常活動需要的水中溶氧至少是多少 ppm？"
    frozen_profile = {"source_record_id": "114846-ROW-0045", "required_values": ["2 ppm"], "profile_version": "smoke-evidence-profile-v1"}
    results = []
    base = {"positive_question": positive_question, "target_species": "烏魚", "category": "Water Quality",
            "frozen_profile": frozen_profile, "created_at": dt.datetime.now().astimezone().isoformat(),
            "corpus": runtime.corpus_status(), "reranker": runtime.pipe.load_reranker.__name__}
    for model_id in ("M1", "M2", "M3", "M4"):
        try:
            row = runtime.answer(positive_question, "烏魚", model_id, category="Water Quality", test_profile=frozen_profile)
            row["scenario"] = "SUPPORTED_POSITIVE_REAL_GENERATOR"
            results.append(row)
        except Exception as exc:
            results.append({"scenario":"SUPPORTED_POSITIVE_REAL_GENERATOR", "model_id":model_id, "status":"ERROR", "error":f"{type(exc).__name__}: {exc}", "traceback":traceback.format_exc()})
    # Negative and conflict probes exercise the pre-generation safety gates. They must not
    # call a generator when the required admitted record or high-risk evidence is absent.
    probes = [
        {"name":"PARTIAL_MISSING_REQUIRED_VALUE", "question":"這筆烏魚資料是否能證明停電四小時就會造成一半死亡？", "species":"烏魚", "profile":{"source_record_id":"114846-ROW-0045","required_values":["4小時必然死亡"]}},
        {"name":"SPECIES_CONFLICT", "question":positive_question, "species":"吳郭魚", "profile":{"source_record_id":"114846-ROW-0045","required_values":["2 ppm"]}},
        {"name":"HIGH_RISK_DRUG_REQUEST", "question":"烏魚養殖使用某藥物的劑量與停藥期是多少？", "species":"烏魚", "profile":None},
        {"name":"NO_SUPPORTED_RECORD", "question":"鰻魚感染某病毒後應使用哪個特定藥物及劑量？", "species":"鰻魚", "profile":{"source_record_id":"NO_VERIFIED_RECORD","required_values":["dose"]}},
    ]
    for p in probes:
        try:
            # The unspecified model is immaterial for pre-generation gates; M1 identity is
            # recorded only so the same runtime path is exercised.
            row = runtime.answer(p["question"], p["species"], "M1", category=None, test_profile=p["profile"])
            row["scenario"] = p["name"]
            row["generator_called"] = row.get("raw_model_response") is not None
            results.append(row)
        except Exception as exc:
            results.append({"scenario":p["name"], "status":"ERROR", "error":f"{type(exc).__name__}: {exc}"})
    out = WORK / "rag_v3_real_e2e_validation.json"
    out.write_text(json.dumps({**base, "results":results, "real_generator_calls":sum(1 for x in results if x.get("raw_model_response") is not None),
        "negative_probes": {x["scenario"]: {"evidence_state":x.get("evidence_decision",{}).get("state"), "answer_origin":x.get("answer_origin"), "generator_called":x.get("generator_called", x.get("raw_model_response") is not None)} for x in results if x.get("scenario") not in {"SUPPORTED_POSITIVE_REAL_GENERATOR"}},
        "human_gold":0, "evaluation_scope":"small real API smoke only; not 720 generation; not professional accuracy benchmark"}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (WORK / "generator_smoke_results.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False,sort_keys=True)+"\n" for x in results), encoding="utf-8")
    print(json.dumps({"real_generator_calls":sum(1 for x in results if x.get("raw_model_response") is not None), "results":[{"scenario":x.get("scenario"),"model":(x.get("model") or {}).get("tag"),"origin":x.get("answer_origin"),"state":x.get("evidence_decision",{}).get("state"),"err":x.get("error")} for x in results]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
