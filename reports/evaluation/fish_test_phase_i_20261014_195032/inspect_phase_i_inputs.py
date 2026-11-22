import collections, hashlib, json, pathlib

root = pathlib.Path.cwd()
run = root / 'reports/evaluation/fish_test_run_20261012_152244'
h = root / 'reports/evaluation/fish_test_phase_h/20261014_185653'
out = h.parent.parent / 'fish_test_phase_i_20261014_195032'
def jl(p):
    return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
questions = jl(run/'fish_test_questions_normalized.jsonl')
traces = jl(run/'retrieval_trace.jsonl')
source_rows = jl(h/'source_mapping_recovery_180.jsonl')
qmap = {q['question_id']: q for q in questions}
tmap = {t['question_id']: t for t in traces}
selection = jl(h/'pilot_10_question_annotation_results.jsonl')
# Keep the prior Phase H six-species pilot and ensure the known mullet-vs-tilapia control is included.
selected_ids = list(dict.fromkeys(r['question_id'] for r in selection if r.get('question_id')))
if 'FT-tilapia-Q01' not in selected_ids:
    selected_ids = ['FT-tilapia-Q01'] + selected_ids
selected_ids = selected_ids[:10]
selected = []
for qid in selected_ids:
    q=qmap[qid]; t=tmap[qid]
    contexts=[]
    for c in sorted(t.get('contexts',[]), key=lambda x:x.get('top5_rank',999)):
        text=c.get('text') or ''
        contexts.append({'rank':c.get('top5_rank'),'chunk_id':c.get('chunk_id'),'document_id':c.get('document_id'),
                         'page':c.get('page'),'text_chars':len(text),'sha256_matches':hashlib.sha256(text.encode()).hexdigest()==c.get('text_sha256'),
                         'text_sha256':c.get('text_sha256'),'text':text})
    selected.append({'question_id':qid,'species':q.get('species_chinese'),'question_text':q.get('question_text'),
                     'category':q.get('inferred_category'),'contexts':contexts})
all_local={}
for r in source_rows:
    for f in r.get('local_originals') or []:
        if f.get('exists') and f.get('checksum_match'):
            all_local.setdefault(f.get('path'), {'sha256':f.get('actual_sha256'),'source_url':f.get('source_url'),'version':f.get('version'),'questions':[]})
            all_local[f.get('path')]['questions'].append(r['question_id'])
out.joinpath('pilot_question_selection.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with out.joinpath('source_documents_29_mapping.jsonl').open('w',encoding='utf-8',newline='\n') as f:
    for path,row in all_local.items(): f.write(json.dumps({'path':path,**row},ensure_ascii=False)+'\n')
summary={'questions':len(questions),'unique_question_ids':len(qmap),'retrieval_questions':len(traces),
         'retrieval_contexts':sum(len(t.get('contexts',[])) for t in traces),'pilot_ids':selected_ids,
         'pilot_species':dict(collections.Counter(x['species'] for x in selected)),
         'pilot_context_count':sum(len(x['contexts']) for x in selected),
         'pilot_full_text_sha_matches':sum(c['sha256_matches'] for x in selected for c in x['contexts']),
         'pilot_expected_context_count':50,'verified_local_source_files':all_local,
         'unique_local_source_count':len(all_local)}
out.joinpath('phase_i_preflight.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
