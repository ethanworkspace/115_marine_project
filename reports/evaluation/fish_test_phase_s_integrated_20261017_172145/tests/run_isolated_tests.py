from __future__ import annotations

import importlib.util
import io
import json
import unittest
from pathlib import Path

RUN = Path(__file__).resolve().parents[1]
TEST_FILE = Path(__file__).resolve().parent / "test_phase_s_isolated.py"
spec = importlib.util.spec_from_file_location("phase_s_isolated_tests", TEST_FILE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
suite = unittest.defaultTestLoader.loadTestsFromModule(module)
stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
payload = {
    "test_file": str(TEST_FILE), "tests_run": result.testsRun,
    "failures": [{"test": str(test), "traceback": detail} for test, detail in result.failures],
    "errors": [{"test": str(test), "traceback": detail} for test, detail in result.errors],
    "successful": result.wasSuccessful(), "output": stream.getvalue(),
    "scope": "isolated Phase S tests only; not full repository pytest",
}
(RUN / "isolated_unit_test_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: payload[k] for k in ("tests_run", "failures", "errors", "successful", "scope")}, ensure_ascii=False, indent=2))
if not result.wasSuccessful():
    raise SystemExit(1)
