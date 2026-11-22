from __future__ import annotations

import json
from pathlib import Path
from streamlit.testing.v1 import AppTest

RUN = Path(__file__).resolve().parents[1]
APP = RUN / "rag_v2" / "phase_s_app.py"

test = AppTest.from_file(str(APP)).run(timeout=30)
errors = [str(x.value) for x in test.error]
exceptions = [str(x.value) for x in test.exception]
result = {
    "app_path": str(APP),
    "isolated_from_production": True,
    "streamlit_test_runtime": "streamlit.testing.v1.AppTest",
    "exception_count": len(exceptions),
    "exceptions": exceptions,
    "visible_error_count": len(errors),
    "visible_errors": errors,
    "title_rendered": any("Phase S" in str(x.value) for x in test.title),
    "reranker_block_visible": any("BGE Reranker" in e for e in errors),
    "fail_closed": any("BGE Reranker" in e for e in errors) and not exceptions,
    "streamlit_smoke_status": "PASS_FAIL_CLOSED" if any("BGE Reranker" in e for e in errors) and not exceptions else "FAILED",
    "production_switch": False,
}
(RUN / "streamlit_integration_status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
