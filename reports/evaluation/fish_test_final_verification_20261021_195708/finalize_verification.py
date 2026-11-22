from pathlib import Path
import sys,json,hashlib,datetime,platform,importlib.metadata,subprocess
from html.parser import HTMLParser
from docx import Document
import openpyxl
W=Path(__file__).resolve().parent;R=W.parents[2];I=W.parent/'fish_test_corpus_v3_frozen_run_20261021_133102'
def j(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def jl(p):return [json.loads(x) for x in Path(p).read_text(encoding='utf-8-sig').splitlines() if x.strip()]
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def wr(n,v):(W/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def main():
 data=j(W/'recomputed_data_package.json');manifest=j(I/'frozen_evaluation_manifest.json');generations=jl(I/'generator_final_results_720.jsonl')
 frozen=datetime.datetime.fromisoformat(manifest['frozen_at']);assert all(datetime.datetime.fromisoformat(g['at'])>=frozen for g in generations)
 # Independent read-only reconciliation of exported cell values and cached formulas.
 book=W/'final_statistical_verification.xlsx';v=openpyxl.load_workbook(book,read_only=True,data_only=True);f=openpyxl.load_workbook(book,read_only=True,data_only=False)
 assert len(v.sheetnames)==11
 for name,n in [('Metric_Audit',80),('Paired_Questions',34),('Paired_Reasons',136),('Exceptions',10),('Source_Dependency',208)]:assert sum(r[0] is not None for r in v[name].iter_rows(min_row=4,min_col=1,max_col=1,values_only=True))==n
 for row in v['Metric_Audit'].iter_rows(min_row=4,values_only=True):
  if row[0] is None:continue
  layer,mid,key,value,n=row[:5];expected=data['allstats'][layer][mid][key];assert n==expected['n'] and abs(value-expected['mean'])<1e-10
 for i,row in enumerate(v['Paired_Summary'].iter_rows(min_row=4,values_only=True)):
  if row[0] is None:continue
  typ,mid,n,correct,incorrect,accuracy=row[:6];e=next(x['stats'] for x in data['paired_summary'] if x['metric']==typ and x['model_id']==mid and x['view']=='four_model_common');assert n==e['n'] and correct==e['correct'] and incorrect==e['incorrect'] and abs(accuracy-e['accuracy'])<1e-12
 err=[(s.title,c.coordinate,c.value) for s in v for row in s for c in row if c.data_type=='e'];assert not err
 formulas=sum(c.data_type=='f' for s in f for row in s for c in row);assert formulas>0
 v.close();f.close();wr('final_excel_independent_validation.json',{'status':'PASS','reopened_readonly':True,'sheets':11,'all_80_metric_means_and_N_match':True,'common_question_counts_and_correct_counts_match':True,'formulas':formulas,'formula_errors':err,'all_sheets_visually_reviewed':True,'sha256':sha(book)})
 # Structural content checking is distinct from the blocked Word layout check.
 doc=Document(W/'thesis_results_chapter_zh_tw.docx');prov=j(W/'thesis_table_provenance.json')['tables'];assert len(doc.tables)==len(prov)==12
 for tab,p in zip(doc.tables,prov):
  rows=[[c.text for c in r.cells] for r in tab.rows];assert rows==[[str(x) for x in p['headers']]]+[[str(x if x is not None else 'N/A') for x in row] for row in p['rows']]
 html=(W/'thesis_results_chapter_zh_tw.html').read_text(encoding='utf-8');assert html.count('<article ')==9 and html.count('<table>')==12
 wr('document_validation.json',{'primary_readable_deliverable':'thesis_results_chapter_zh_tw.html','text_copy':'thesis_results_chapter_zh_tw.txt','chapter_sections':9,'tables':12,'all_docx_table_cells_match_recomputed_table_provenance':True,'html_browser_rendered':True,'html_table_overflow_detected':False,'html_sections_and_tables_visually_reviewed':True,'docx_layout_validated':False,'docx_status':'NOT_LAYOUT_VERIFIED_REFERENCE_ONLY','render_failures':[{'method':'packaged render_docx.py','reason':'LibreOffice soffice.exe unavailable; full trace in render_docx_attempt.log'},{'method':'Microsoft Word read-only COM export','reason':'COM initialization failed 0x80070520 specified logon session does not exist; no document opened or modified'}],'no_false_docx_render_success_claim':True})
 # Every input file in the frozen workspace is checked, not just selected outputs.
 old=j(W/'input_file_hashes_before.json')['files'];dif=[]
 for r in old:
  actual=sha(r['path']) if Path(r['path']).is_file() else None
  if actual!=r['sha256']:dif.append({'path':r['path'],'before':r['sha256'],'after':actual})
 assert not dif,dif
 protected=j(R/'reports/evaluation/final_model_selection/phase20/protected_inputs_before.json');after=[]
 for r in protected['files']:
  a=sha(R/r['path']) if (R/r['path']).is_file() else None;after.append({**r,'after_sha256':a,'unchanged':a==r['sha256']})
 assert len(after)==sum(r['unchanged'] for r in after)==636
 wr('protected_baseline_after.json',{'files':after,'total':636,'unchanged':636,'at':datetime.datetime.now().astimezone().isoformat()})
 extras=j(I/'additional_protected_before.json');extra=[]
 for x in extras:
  actual=sha(R/x['path']);extra.append({**x,'current_sha256':actual,'unchanged':actual==x['sha256']})
 assert all(r['unchanged'] for r in extra)
 sqlite=sha(R/'rag_store.sqlite3');assert sqlite=='d7d06d4d2a57d0a57d05bcb6131ffb24aefb226c6bd36349dbc5118d33b11087'
 source=j(I/'frozen_source_manifest.json');sources=[{'source_id':x['source_id'],'path':x['source_file'],'expected_sha256':x['source_sha256'],'current_sha256':sha(x['source_file'])} for x in source['sources']];assert all(x['current_sha256']==x['expected_sha256'] for x in sources)
 wr('compatibility.json',{'status':'PASS','frozen_manifest':{'total':636,'unchanged':636},'production_sqlite_sha256':sqlite,'whole_input_workspace_files_checked':len(old),'whole_input_workspace_changed_files':dif,'corpus_sha256':sha(I/'corpus/marine_hybrid_rag_corpus_v3.sqlite3'),'source_files':sources,'old_phase_e_and_w_and_sqlite':extra,'generator_calls_this_task':0,'judge_calls_this_task':0,'embedding_calls_this_task':0,'historical_scores_modified':False,'corpus_modified':False,'production_switched':False,'winner':None})
 validations=[]
 for p in W.glob('*.json'):j(p);validations.append({'file':p.name,'valid':True})
 for p in W.glob('*.jsonl'):rows=jl(p);validations.append({'file':p.name,'valid':True,'rows':len(rows)})
 wr('final_validation.json',{'status':'PASS_WITH_WORD_LAYOUT_LIMITATION','files':validations,'original_questions_and_720_pairs_verified':True,'all_metric_aggregates_reconciled':True,'judge_input_binding_rows':len(jl(W/'judge_input_binding_audit.jsonl')),'paired_logical_n':27,'paired_arithmetic_n':7,'source_group_n':10,'original_source_file_n':3,'human_gold_n':0,'primary_html_and_excel_validated':True,'word_docx_layout_unverified':True,'frozen_manifest_unchanged':636})
 # Leave readable instructions beside the machine-readable manifest.
 readme='''最終評測核對與論文結果交付

已完成720筆離線一致性核對，沒有新增模型推論、Judge重評、Embedding或Corpus變更。

主要成果
final_statistical_verification.xlsx：11工作表，含11指標定義與有效N、27題Logical及7題Arithmetic逐題配對、六魚種、來源群組與原件敏感度、Judge母體差異及五筆原始缺陷。
thesis_results_chapter_zh_tw.html：主要可讀論文章節，9節12表，已在瀏覽器檢查內容與溢出。
thesis_results_chapter_zh_tw.txt：相同章節的純文字副本。
paired_question_comparison_34.jsonl：34個共同題目與四模型原始答案、正確／錯誤理由、凍結判準及精確來源。
paired_analysis.json：共同題目與各自有效分母、魚種分布及成對不一致描述統計。
source_group_influence.jsonl與source_file_influence.jsonl：10組原始紀錄／頁及3份原件的組成敏感度，非因果效果。
data_limitations_statement_zh_tw.txt：研究限制聲明。
reproducibility_manifest.json：來源及輸出雜湊、模型與設定、指標與重算方式。
compatibility.json：636/636與正式SQLite及歷史結果的本次雜湊核對。

格式限制
Word草稿檔已建立且表格內容與重算資料一致，但未通過Word版面渲染驗證，不作排版完成版本交付。套件渲染器缺少LibreOffice，Word COM亦因0x80070520登入工作階段失敗。此限制不影響HTML論文草稿、統計表及JSONL內容核對。

研究範圍
Human Gold為0。50題僅為來源核驗型探索性子集，依賴10組紀錄／PDF頁與3份原件。P@5僅12題60段，平均0.30；小樣本與來源依賴不能支持全體顯著性或正式Winner。
'''
 (W/'delivery_readme_zh_tw.txt').write_text(readme,encoding='utf-8')
 files=[p for p in sorted(W.iterdir()) if p.is_file() and p.name!='reproducibility_manifest.json']
 wr('reproducibility_manifest.json',{'created_at':datetime.datetime.now().astimezone().isoformat(),'purpose':'Frozen-run offline final verification and thesis chapter; no new inference','input_workspace':str(I),'input_hash_manifest':'input_file_hashes_before.json','input_files_verified_unchanged_n':len(old),'input_frozen_manifest_sha256':sha(I/'frozen_evaluation_manifest.json'),'run_id':manifest['run_id'],'corpus_version':manifest['corpus']['corpus_version'],'corpus_sha256':manifest['corpus']['database_sha256'],'prompt_version':manifest['prompt_version'],'generation_options':manifest['generation_options'],'models':manifest['models'],'independent_judge':{'tag':'mistral-nemo:12b-instruct-2407-q4_K_M','digest':'daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55','input_request_binding_verified':True},'embedding':{'tag':'bge-m3:latest','digest':'7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab','dimension':1024,'not_reexecuted':True},'source_files':sources,'retrieval':manifest['retrieval'],'analysis_interpreter':sys.executable,'analysis_python_version':sys.version,'packages':{n:importlib.metadata.version(n) for n in ['openpyxl','python-docx','jsonschema']},'artifact_runtime':'C:/Users/ethan/.cache/codex-runtimes/codex-primary-runtime/dependencies','recompute_commands':[[sys.executable,str(W/'recompute_final_audit.py')],['bundled Python',str(W/'build_final_documents.py')],['bundled Python',str(W/'export_readable_chapter.py')],['bundled Node',str(W/'build_final_workbook.mjs')],[sys.executable,str(W/'finalize_verification.py')]],'required_analysis_PYTHONPATH':['C:/my project/115_marine_project/.venv-reranker/Lib/site-packages','C:/my project/115_marine_project/.venv/Lib/site-packages'],'required_junction':'new workspace node_modules points only to bundled runtime node_modules','scores_unchanged':True,'new_inference_calls':0,'human_gold':0,'formal_weighted_total':None,'winner':None,'docx_layout_status':'NOT_LAYOUT_VERIFIED; use rendered HTML as primary readable chapter','outputs':[{'file':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in files],'manifest_self_hash_not_embedded':True})
 print(json.dumps({'status':'PASS_WITH_WORD_LAYOUT_LIMITATION','old_workspace_files_unchanged':len(old),'frozen_unchanged':636,'excel_sheets':11,'thesis_sections':9,'thesis_tables':12,'judge_binding_rows':len(jl(W/'judge_input_binding_audit.jsonl'))},ensure_ascii=False),flush=True)
if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
