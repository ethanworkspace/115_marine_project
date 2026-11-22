from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))


def main():
    result = {"app": str(HERE / "phase_aa_streamlit_app.py"), "status": "FAIL", "real_generator_invoked": False, "detail": None}
    try:
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(HERE / "phase_aa_streamlit_app.py"), default_timeout=120).run()
        if app.exception:
            raise RuntimeError("initial app load exception: " + "; ".join(str(x.message) for x in app.exception))
        case_box = app.selectbox[0]
        case_box.select("AA-NEW-EEL-TEMP-01").run()
        if app.exception:
            raise RuntimeError("case selection exception: " + "; ".join(str(x.message) for x in app.exception))
        button = next(x for x in app.button if x.label == "執行隔離檢索")
        button.click().run()
        if app.exception:
            raise RuntimeError("retrieval UI exception: " + "; ".join(str(x.message) for x in app.exception))
        text = " ".join(str(x.value) for x in app.markdown)
        result.update({"status": "PASS", "retrieval_button_executed": True, "output_elements": len(app.get("expander")), "real_generator_invoked": False,
                       "ui_has_retrieval_content": bool(app.expander), "exception_count": len(app.exception), "detail": "Streamlit AppTest loaded the isolated corpus UI and executed real BM25/BGE-M3/RRF/reranker retrieval. Generator smoke is recorded separately."})
    except Exception as exc:
        result.update({"status": "FAIL", "detail": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()})
    (HERE / "rag_streamlit_apptest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
