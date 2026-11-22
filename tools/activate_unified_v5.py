"""Point only the existing isolated research app at the validated successor."""
from pathlib import Path
import ast,json,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.unified_rag_v4.common import sha_file,dump
p=json.loads((ROOT/'research_staging/unified_rag_v5_build_pointer.json').read_text(encoding='utf-8'))
w=Path(p['workspace']);r=Path(p['report_directory']);m=json.loads((w/'corpus_manifest.json').read_text(encoding='utf-8'))
assert json.loads((r/'all_document_vector_integrity.json').read_text(encoding='utf-8'))['passed']
assert sha_file(Path(m['database']))==m['database_sha256']
stage=w/'app_staged';app=ROOT/'research_staging/app_sessions/launch_20261118_154253'
for name in ('professional_platform.py','unified_question_engine.py'):
    ast.parse((stage/name).read_text(encoding='utf-8'));shutil.copyfile(stage/name,app/name)
pointer={'workspace':str(w),'database':m['database'],'database_sha256':m['database_sha256'],'version':m['version'],
    'isolation':True,'production_changed':False,'all_originals_semantically_indexed':True,'engine_module':'src.unified_rag_v5.retrieval'}
dump(ROOT/'research_staging/unified_rag_active.json',pointer)
info=json.loads((app/'launch_info.json').read_text(encoding='utf-8-sig'))
info.update(unified_corpus_version=m['version'],unified_database=m['database'],unified_database_sha256=m['database_sha256'],
    unified_prompt_version='unified-v5-all-documents-law-verified-20261121-v1',all_documents_search_enabled=True,official_law_review_enabled=True)
dump(app/'launch_info.json',info);dump(r/'isolated_app_activation.json',pointer)
print(json.dumps(pointer,ensure_ascii=False))
