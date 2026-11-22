"""Create a successor without mutating the released v4 database or Production."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
import argparse,json,shutil,sqlite3
ROOT=Path(__file__).resolve().parents[1]
active=json.loads((ROOT/'research_staging/unified_rag_active.json').read_text(encoding='utf-8'))
args=argparse.ArgumentParser();args.add_argument('--parent-workspace');args=args.parse_args()
if args.parent_workspace:
    chosen=Path(args.parent_workspace);prior=json.loads((chosen/'corpus_manifest.json').read_text(encoding='utf-8'))
    active={'workspace':str(chosen),'database':prior['database'],'database_sha256':prior['database_sha256'],'version':prior['version']}
stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
work=ROOT/'research_staging'/('unified_rag_v5_'+stamp)
report=ROOT/'reports/evaluation'/('unified_rag_v5_'+stamp)
work.mkdir();report.mkdir()
for name in ('logs','official_laws','checkpoints','assets','live_smoke'): (work/name).mkdir()
parent=Path(active['workspace'])
config=json.loads((parent/'build_config.json').read_text(encoding='utf-8'))
config.update(version='marine-unified-v5-'+stamp,workspace=str(work),report_directory=str(report),
    parent_database=active['database'],parent_database_sha256=active['database_sha256'],
    source_frozen_database=active['database'],database_filename='marine_unified_v5.sqlite3',
    source_asset_workspace=str(parent),clip_model_directory=config.get('clip_model_directory',str(parent/'models/clip-vit-base-patch32')),
    user_use_attestation={'at':datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'statement':'全部文件皆可使用，幫我解析並加入資料庫，法規幫我進行核對；所有資料都幫我清洗、切分、加入向量資料庫',
        'scope':'User-provided originals for this local research RAG and semantic archive',
        'third_party_license_independently_verified':False,'existing_notices_preserved':True,
        'not_new_public_redistribution_permission':True})
for name,value in [('build_config.json',config),('parent_active_snapshot.json',active)]:
    (work/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
for name in ('source_inventory.json','word_conversion_results.json'):
    if (parent/name).exists():shutil.copyfile(parent/name,work/name)
src=sqlite3.connect(Path(active['database']).as_uri()+'?mode=ro',uri=True)
dst=sqlite3.connect(work/config['database_filename']);src.backup(dst);dst.close();src.close()
pointer={'workspace':str(work),'report_directory':str(report)}
(ROOT/'research_staging/unified_rag_v5_build_pointer.json').write_text(json.dumps(pointer,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(pointer))
