from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
from streamlit.testing.v1 import AppTest

WORK = Path(__file__).resolve().parent
APP = WORK / "streamlit_v3_app.py"
question = "依據水產試驗所這筆烏魚資料，烏魚正常活動需要的水中溶氧至少是多少 ppm？"
result = {"app": str(APP), "started_at": dt.datetime.now().astimezone().isoformat(), "test_type": "Streamlit AppTest with real Corpus v3 runtime and one real M2 call", "status": "ERROR"}
try:
    at = AppTest.from_file(str(APP), default_timeout=300).run()
    at.selectbox(key="species").select("烏魚")
    at.selectbox(key="model_id").select("M2")
    at.text_area(key="question").set_value(question)
    at.button(key="run_query").click().run()
    errs = [str(e.value) for e in at.exception]
    try:
        state_result = at.session_state["last_result"]
    except KeyError:
        state_result = None
    rendered = "\n".join(str(getattr(x, "value", "")) for x in at)
    status = "PASS" if not errs and state_result and state_result.get("corpus", {}).get("corpus_id") == "marine_hybrid_rag_corpus_v3_research_isolated" else "FAIL"
    result.update({"status":status,"exceptions":errs,"rendered_text":rendered,"result":state_result,
                   "assertions":{"used_corpus_v3":bool(state_result and state_result.get("corpus",{}).get("corpus_id")=="marine_hybrid_rag_corpus_v3_research_isolated"),
                   "generator_called":bool(state_result and state_result.get("raw_model_response") is not None),
                   "citations_rendered":bool(state_result and (state_result.get("citation_validation") or {}).get("citations")),
                   "no_exception":not errs}})
except Exception as exc:
    result.update({"status":"ERROR","error":f"{type(exc).__name__}: {exc}"})
(WORK / "streamlit_v3_validation.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"status":result.get("status"),"assertions":result.get("assertions"),"exceptions":result.get("exceptions"),"error":result.get("error")},ensure_ascii=False))
