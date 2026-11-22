"""Real retrieval regression and CLIP branch, with no generated expert truth."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'research_staging/app_sessions/launch_20261118_154253')]
from unified_question_engine import UnifiedQuestionRag
from src.unified_rag_v4.common import dump

p=json.loads((ROOT/'research_staging/unified_rag_build_pointer.json').read_text())
report=Path(p['report_directory'])
runtime=UnifiedQuestionRag()
row=runtime.prepare_free_question('烏魚的官方分類代碼資料中，學名欄位記載什麼？','烏魚')
codes=[c for c in row['top5'] if c['taxonomy_level']=='NAME_CODE_LOOKUP_ONLY']
assert codes and all('Mugil cephalus' in c['text'] for c in codes)
assert not any('Atrobucca nibe' in c['text'] for c in row['top5'])
dump(report/'native_name_retrieval_regression.json',{
    'previous_live_error':{'question':row['question'],'wrong_answer':'Atrobucca nibe','wrong_record_common_name':'烏喉','failure':'Native name-code branch bypassed target-species checking'},
    'fix':'Complete original Chinese/common/scientific name fields must identify the target; narrow taxa remain distinct',
    'current_retrieval':row,'name_record_check_passed':True,'not_professional_husbandry_accuracy':True,
})
print('Native name regression passed',flush=True)
found=runtime.unified.visual_candidates('鰻魚寄生蟲顯微圖片','鰻魚')
allowed=[]
for rank,cid in found:
    c=runtime.unified.map[cid]
    ok,reason=runtime.unified.scope_check('鰻魚寄生蟲顯微圖片','鰻魚',c)
    if ok: allowed.append({'visual_rank':rank,'chunk_id':cid,'source_id':c['source_id'],'assets':c['media_assets'],'scope_reason':reason})
assert runtime.unified.clip is not None and allowed
dump(report/'image_retrieval_validation.json',{
    'model':'openai/clip-vit-base-patch32','dimension':512,
    'indexed_image_vectors':len(runtime.unified.image_rows),'visual_candidate_links':len(found),
    'applicable_candidate_links':len(allowed),'results':allowed,
    'real_text_image_similarity_executed':True,'diagnostic_or_expert_accuracy_measured':False,
})
print(json.dumps({'actual_clip_vectors':len(runtime.unified.image_rows),'applicable_candidate_links':len(allowed)}),flush=True)
