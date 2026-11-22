"""Activate only the isolated research website after source integrity passes."""
import ast,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
import complete_and_catalog_rag_v6 as b
w,r,cfg=b.paths();m=b.read(w/'corpus_manifest.json')
assert b.read(r/'all_document_media_integrity.json')['passed']
assert b.sha(m['database'])==m['database_sha256']
app=ROOT/'research_staging/app_sessions/launch_20261118_154253'
text=(w/'app_backup/unified_question_engine.py').read_text(encoding='utf-8')
assert 'from src.unified_rag_v5.retrieval import UnifiedRetriever' in text
text=text.replace('from src.unified_rag_v5.retrieval import UnifiedRetriever','from src.unified_rag_v6.retrieval import UnifiedRetriever')
text=text.replace('unified-v5-all-documents-law-verified-20261121-v1','unified-v6-complete-media-organized-sources-20261121-v1')
ast.parse(text);(app/'unified_question_engine.py').write_text(text,encoding='utf-8')
text=(w/'app_backup/professional_platform.py').read_text(encoding='utf-8')
text=text.replace('from src.unified_rag_v5.presentation import all_data_search,law_review','from src.unified_rag_v6.presentation import all_data_search,law_review,organized_source_catalog')
text=text.replace('def load():','def load(corpus_version=None):')
text=text.replace('runtime, questions, sources = load()',"runtime, questions, sources = load(json.loads((Path(r'C:\\my project\\115_marine_project')/'research_staging/unified_rag_active.json').read_text(encoding='utf-8'))['version'])")
text=text.replace('    all_data_search(runtime)','    organized_source_catalog(runtime)\n    all_data_search(runtime)')
text=text.replace("e.kind IN ('IMAGE','PAGE_RENDER')","e.kind IN ('IMAGE','PAGE_RENDER','LEGACY_IMAGE')")
ast.parse(text);(app/'professional_platform.py').write_text(text,encoding='utf-8')
pointer={'workspace':str(w),'database':m['database'],'database_sha256':m['database_sha256'],'version':m['version'],'isolation':True,'production_changed':False,'all_originals_semantically_indexed':True,'engine_module':'src.unified_rag_v6.retrieval','source_catalog_directory':cfg['source_catalog_directory'],'legacy_media_files_bound':m['counts']['media_files']}
b.dump(ROOT/'research_staging/unified_rag_active.json',pointer)
info=b.read(app/'launch_info.json');info.update(unified_corpus_version=m['version'],unified_database=m['database'],unified_database_sha256=m['database_sha256'],unified_prompt_version='unified-v6-complete-media-organized-sources-20261121-v1',source_catalog_directory=cfg['source_catalog_directory'],all_legacy_media_indexed=True)
b.dump(app/'launch_info.json',info);b.dump(r/'isolated_app_activation.json',pointer)
b.emit(pointer)
