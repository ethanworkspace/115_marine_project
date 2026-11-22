from __future__ import annotations
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[2]
DB = WORK / "corpus" / "marine_hybrid_rag_corpus_v3.sqlite3"
BUILD = WORK / "build_corpus_v3.py"


def main():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("corpus_v3_builder", BUILD)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = []
    for r in con.execute("SELECT source_record_id,source_id,source_record_locator,source_record_sha256,eligibility_status,eligibility_reason,original_record_json,duplicate_group_id FROM source_records"):
        rows.append({**dict(r), "original_record_json": json.loads(r["original_record_json"])})
    groups = module.assign_duplicate_groups(rows)
    con.execute("UPDATE source_records SET duplicate_group_id=NULL")
    con.executemany("UPDATE source_records SET duplicate_group_id=? WHERE source_record_id=?", [(r.get("duplicate_group_id"), r["source_record_id"]) for r in rows if r.get("duplicate_group_id")])
    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    current = [dict(r) for r in con.execute("SELECT source_record_id,source_id,source_record_locator,source_record_sha256,eligibility_status,eligibility_reason,duplicate_group_id FROM source_records ORDER BY source_record_id")]
    chunk_rows = [dict(r) for r in con.execute("SELECT c.chunk_id,c.source_id,c.source_record_id,s.duplicate_group_id,c.source_sha256,c.source_version,c.locator,c.source_quote,c.raw_field_pointer,c.quote_start,c.quote_end,c.species_scope,c.category_scope,c.source_cluster_id,c.retrieval_status,c.retrieval_eligible,c.restrictions_json FROM chunks c JOIN source_records s USING(source_record_id) ORDER BY c.chunk_id")]
    con.close()
    module.write_jsonl(WORK / "source_record_duplicate_groups.jsonl", groups)
    module.write_jsonl(WORK / "source_record_status_registry.jsonl", current)
    for row in chunk_rows:
        row["restrictions"] = json.loads(row.pop("restrictions_json"))
        row["species_scope_list"] = [x for x in str(row.pop("species_scope") or "").split("|") if x]
        row["category_scope_list"] = json.loads(row.pop("category_scope"))
    module.write_jsonl(WORK / "corpus_chunk_source_registry.jsonl", chunk_rows)
    report = {"status":"PASS" if integrity=="ok" else "FAIL", "integrity_check":integrity,"duplicate_group_count":len(groups),
              "duplicate_member_record_count":sum(g["member_count"] for g in groups),"groups":groups,
              "source_records":len(current),"chunk_records":len(chunk_rows),"deduplication_policy":"preserve every original source record; retain duplicate group provenance; retrieval chooses best-ranked record per duplicate group"}
    module.write_json(WORK / "duplicate_group_registration_validation.json", report)
    print(json.dumps({"status":report["status"],"groups":groups,"records":len(current),"chunks":len(chunk_rows)},ensure_ascii=False))

if __name__ == "__main__":
    main()
