from __future__ import annotations

import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

HERE = Path(__file__).resolve().parent
APP = HERE / "phase_z_streamlit_app.py"


def run_case(case_id: str, model_id: str):
    app = AppTest.from_file(str(APP)).run(timeout=60)
    app.selectbox[0].select(case_id)
    app.selectbox[1].select(model_id)
    app.run(timeout=60)
    app.button[0].click()
    app.run(timeout=600)
    if app.exception:
        raise RuntimeError("Streamlit AppTest raised: " + "; ".join(x.message for x in app.exception))
    try:
        result = app.session_state["phase_z_last_result"]
    except KeyError:
        result = None
    if result is None:
        raise RuntimeError("Streamlit AppTest did not retain a result")
    return {
        "test_case": case_id, "model_id": model_id,
        "answer_origin": result.get("answer_origin"),
        "generator_called": result.get("generator_called"),
        "evidence_state": (result.get("evidence_decision") or {}).get("state"),
        "final_status": (result.get("final_response") or {}).get("status"),
        "final_answer": (result.get("final_response") or {}).get("answer"),
        "citations": (result.get("final_response") or {}).get("citations", []),
        "citation_rendered": any("引用來源" in str(el.value) for el in app.markdown),
        "raw_json_valid": result.get("raw_json_valid"),
        "raw_citation_schema_valid": result.get("raw_citation_schema_valid"),
        "support_validation": result.get("support_validation"),
    }


def main() -> None:
    rows = [
        run_case("Z-IND-MULLET-AGE2-RATE", "M2"),
        run_case("Z-NEG-EEL-WATER-QUALITY", "M4"),
    ]
    out = {
        "streamlit_version": "1.63.0",
        "app_test_runs": len(rows),
        "positive_live_m2": rows[0],
        "no_evidence_guard": rows[1],
        "pass": rows[0]["final_status"] in {"answered", "abstain"} and bool(rows[0]["citations"]) and rows[1]["final_status"] == "abstain" and not rows[1]["generator_called"],
        "limitations": ["AppTest invokes the real local Ollama M2 once for the positive scenario; the no-evidence case is stopped by the deterministic gate.", "This tests rendering and the bounded controlled-fact-card workflow, not formal corpus deployment."],
    }
    (HERE / "rag_streamlit_test.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
