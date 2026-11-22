"""Versioned successor only. No writes to the source snapshot or Production."""
from pathlib import Path
import json, sqlite3, hashlib, sys, re, datetime
import numpy as np
import requests

W=Path(__file__).resolve().parent
ROOT=W.parents[2]
DB=W/'corpus/marine_hybrid_rag_corpus_v3.sqlite3'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(n,x): (W/n).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def jl(n,x): (W/n).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in x),encoding='utf-8')
def textsha(t): return hashlib.sha256(t.encode()).hexdigest()

def main():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
 if c.execute("select count(*) from sources where source_id='FA385-LIMITED-FACTS'").fetchone()[0]:
  print('Build already completed; refusing duplicate mutation.');return
 sys.path.insert(0,str(ROOT/'.venv/Lib/site-packages'))
 import fitz
 oldrefs=[json.loads(s) for s in (ROOT/'reports/evaluation/fish_test_phase_aa_20261019_220906/reference_answers_frozen.jsonl').read_text(encoding='utf-8').splitlines()]
 owner=[json.loads(s) for s in (ROOT/'reports/evaluation/fish_test_phase_u_20261018_195823/source_owner_decision_update_57.jsonl').read_text(encoding='utf-8').splitlines()]
 dump('owner_decision_57_preserved.json',{'reference':'Phase U source_owner_decision_update_57.jsonl','rows':owner,'not_third_party_license':True})
 # Exact, finite, original representations of facts already reviewed in AA/Z.
 specs=[
 ('FA385-LIMITED-FACTS','FA-385-COLD',1,'cold_emergency',['虱目魚','吳郭魚'],'Cold event: trigger below 15 degrees Celsius; emergency action example: increase water temperature.','寒流侵襲或停滯；水溫低於15°C時採取緊急措施，例如加溫。','水溫若低於15℃時，應採緊急措施，如加溫以提高水溫，俾減輕死亡。'),
 ('FA385-LIMITED-FACTS','FA-385-COLD',1,'winter_density',['虱目魚'],'Milkfish overwintering trench density reference <=1.3 kg/m3.','虱目魚越冬溝；密度參考上限1.3 kg/m³，並非所有魚種共用密度。','越冬溝內之密度以虱目魚在每立方公尺1.3公斤以下為宜。'),
 ('FA385-LIMITED-FACTS','FA-385-COLD',1,'windbreak',['虱目魚','吳郭魚'],'Winter pond windbreak: north side; cover-water angle strictly less than 30 degrees.','寒流防範設施：魚塭北側；棚蓋與水面夾角<30度。','於魚塭北側搭蓋防風棚，且棚蓋與水面之角度應小於30度'),
 ('FA385-LIMITED-FACTS','FA-385-COLD',1,'cold_operations',['虱目魚','吳郭魚'],'Cold event: avoid feeding, water exchange and unnecessary waterwheel switching that disturb fish; resume discretionary feeding on warming days.','寒流期間避免投餌、換水及無謂開關水車；待氣溫回升暖和時依情況酌投。','寒流來襲時，儘量避免有驚動魚塭內魚群之行為，例如：投餌、換水及無謂地開關水車。'),
 ('FA385-LIMITED-FACTS','FA-385-COLD',1,'floating_fish',['虱目魚','吳郭魚'],'After cold event remove fish bodies floating at surface promptly to prevent deterioration of water quality.','寒流後及時撿除浮於水面的魚體，目的為防止水質惡化。','寒流來襲後，浮於水面之魚體須馬上撿除，防止水質惡化。'),
 ('M17-SEABASS-LIMITED-FACTS','TFRI-M17-GOLD-SEABASS',2,'seabass_temperature',['鱸魚'],'Lates calcarifer only: growth temperature 28-32 C; appetite declines below 23 C with secondary water-mould infection risk; no deterministic death time.','僅金目鱸 Lates calcarifer：最佳成長水溫28–32°C；低於23°C攝食降低並有水黴二次感染風險。','最佳成長溫度為28 ～32℃，溫度低於23℃，食慾會降低，且\n容易因水黴病造成疾病的二次感染。'),
 ('M17-SEABASS-LIMITED-FACTS','TFRI-M17-GOLD-SEABASS',2,'seabass_salinity',['鱸魚'],'Lates calcarifer only: salinity reference at least 5 psu, not universal fish threshold.','僅金目鱸養殖場域：建議鹽度≥5 psu較佳。','建議維持鹽度在5 psu 以上較佳。'),
 ('M17-SEABASS-LIMITED-FACTS','TFRI-M17-GOLD-SEABASS',5,'seabass_stocking',['鱸魚'],'Lates calcarifer fry: 40000-80000 tails/ha; fry length approximately >=6 cm; historical manual conditions.','僅金目鱸魚苗；建議40,000–80,000尾/公頃；體長約6 cm以上。','建議魚苗放養40,000 ～80,000 尾/ 公頃，體長約6 公\n分以上'),
 ]
 facts=[];added=[]
 for sid,oldid,page,key,scopes,en,statement,quote in specs:
  ref=next(r for r in oldrefs if r.get('source_id')==oldid)
  path=Path(ref['source_file']); expected=ref['source_sha256_expected'];assert sha(path)==expected
  # Approval is matched by immutable file identity, not a title similarity.
  owner_hits=[r for r in owner if expected in json.dumps(r,ensure_ascii=False)]
  assert owner_hits, f'Owner SHA not in the retained 57 decisions: {oldid}'
  doc=fitz.open(path); pt=doc[page-1].get_text(); doc.close(); pos=pt.find(quote)
  assert pos>=0,(oldid,key,'quote not found')
  recid=sid+'-'+key;cid=recid+'-C01'
  audit={'fact_id':key,'source_id':sid,'source_record_id':recid,'chunk_id':cid,'original_file':str(path),'original_sha256':expected,'source_version':ref['source_version'],'physical_page':page,'printed_page':('3-2-'+str(page)) if oldid.startswith('TFRI') else 'official print page 1','page_text_sha256':textsha(pt),'exact_original_quote':quote,'quote_start':pos,'quote_end':pos+len(quote),'own_structured_statement':statement,'original_expression_indexed':False,'species_scope':scopes,'owner_approval_reference':owner_hits,'fulltext_license_claimed':False,'usage_basis':'Finite factual values/conditions in original representation; private research only; Copyright Act Art 10-1; no whole-document/fulltext indexing permission asserted.','usage_basis_urls':['https://www.tipo.gov.tw/tw/copyright/694-17731.html','https://www.tipo.gov.tw/tw/copyright/692-16409.html'],'human_gold':False}
  facts.append(audit)
  if not c.execute('select 1 from sources where source_id=?',(sid,)).fetchone():
   oldsource=next(dict(r) for r in c.execute('select * from sources'))
   oldsource.update(source_id=sid,dataset_id="NOT_AN_OPEN_DATA_DATASET",title=ref['source_title']+'（有限原創結構化事實）',publisher='農業部漁業署' if sid.startswith('FA') else '農業部水產試驗所',dataset_url="NOT_APPLICABLE_LOCAL_PUBLISHED_ORIGINAL",resource_url='https://www.fa.gov.tw/view.php?id=385' if sid.startswith('FA') else "LOCAL_PUBLISHED_CHAPTER",source_sha256=expected,file_size_bytes=path.stat().st_size,source_file=str(path),license='NO_FULLTEXT_LICENSE_CLAIMED; ORIGINAL_FACT_REPRESENTATION',license_url='https://www.tipo.gov.tw/tw/copyright/694-17731.html',attribution=ref['source_title']+'；'+ref['source_version']+'；原件SHA-256 '+expected,owner_admission_status='EXISTING_57_OWNER_RESEARCH_PROCESSING_APPROVAL',license_scope_status='LIMITED_ORIGINAL_FACTS_ONLY; FULLTEXT_RIGHTS_UNVERIFIED',identity_status='LOCAL_ORIGINAL_SHA_AND_PUBLICATION_VERIFIED',version_status=ref['source_version'],applicability_status='FINITE_FACT_LEVEL_SCOPE_VERIFIED',completeness_status='FINITE_SELECTED_FACTS_NOT_COMPLETE_DOCUMENT',processing_scope='Index only original structured factual representations, not original PDF text; exact supporting quotations kept outside FTS/embedding for provenance audit.',source_cluster_id='SC-'+oldid,metadata_json=json.dumps({'predecessor_source_id':oldid,'owner_reference':'owner_decision_57_preserved.json','legal_basis_not_express_license':True},ensure_ascii=False))
   keys=list(oldsource);c.execute('insert into sources ('+','.join(keys)+') values ('+','.join('?'*len(keys))+')',[oldsource[k] for k in keys])
  payload=json.dumps(audit,ensure_ascii=False)
  c.execute('insert into source_records values (?,?,?,?,?,?,?,?)',(recid,sid,f'PDF physical page {page}; character [{pos},{pos+len(quote)})',textsha(payload),'RETRIEVAL_ELIGIBLE','Finite original fact representation; original quotation audit-only',payload,None))
  template=dict(c.execute('select * from chunks limit 1').fetchone())
  indexed=statement+'\n'+en
  template.update(chunk_id=cid,source_id=sid,source_record_id=recid,source_sha256=expected,source_version=ref['source_version'],locator=f'PDF physical page {page}; original text [{pos},{pos+len(quote)})',text=indexed,content_sha256=textsha(indexed),source_quote=statement,raw_field_pointer='exact_original_quote (audit-only); original file/page/character locator',quote_start=0,quote_end=len(statement),species_scope='|'.join(scopes),scientific_scope='Lates calcarifer' if oldid.startswith('TFRI') else '',taxonomy_level='EXACT_SPECIES' if oldid.startswith('TFRI') else 'EXPLICIT_WINTER_POND_SCOPE',category_scope=json.dumps(['Climate / Cold','Water Quality','Fact','Calculation']),source_cluster_id='SC-'+oldid,processing_scope='LIMITED_ORIGINAL_FACT_REPRESENTATION_NO_PDF_FULLTEXT',source_path=str(path),source_page=page,retrieval_status='RETRIEVAL_ELIGIBLE',retrieval_eligible=1,human_gold=0,formal_admission=1,embedding=None,embedding_model='bge-m3:latest',embedding_digest='7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab',embedding_dimension=1024,transform_rule='Original structured restatement of finite factual values; exact original quote stored audit-only in source_records and evidence fact registry.',restrictions_json=json.dumps({'no_fulltext_license':True,'no_cross_species_extension':True,'no_current_medication_advice':True},ensure_ascii=False))
  keys=list(template);c.execute('insert into chunks ('+','.join(keys)+') values ('+','.join('?'*len(keys))+')',[template[k] for k in keys]);added.append((cid,indexed))
 # Chunk-level overrides are grounded in explicit paragraph subjects, not record-wide fish mentions.
 overrides=[]
 for row in c.execute("select chunk_id,text,species_scope,source_id from chunks where source_id in ('MOA-TFRI-OPEN-114846','MOA-ANIMAL-DRUG-OPEN-7274')").fetchall():
  cid,t,scope,sid=row; new=None;reason=None
  if sid.endswith('7274') and '吳郭魚除外' in t:
   new='|'.join(s for s in scope.split('|') if s!='吳郭魚');reason='Explicit negative species clause 吳郭魚除外 overrides positive keyword presence.'
  if sid.endswith('114846'):
   n=int(cid.split('-')[2]); para=int(cid.split('-C')[1])
   # Known taxa are not aliases of the target taxa.
   wrong={22:'淡水石斑（非Epinephelus）',202:'寶石鱸 Scortum barcoo',471:'寶石鱸 Scortum barcoo',513:'午魚（非鰻魚）',553:'圓翅燕魚 Platax pinnatus',589:'銀鱸／寶石鱸（非Lates）',594:'七星鱧／澳洲銀鱸（非Lates）',698:'奇力魚 Hemiculter'}
   if n in wrong: new='OTHER_SPECIES';reason=wrong[n]
   if (n==452 and para in (5,6,7)) or n==333:
    new='OTHER_SPECIES';reason='Paragraph concerns shrimp culture, not record-wide mullet/milkfish label.'
   if n==644 or n==365 or (n==529 and para in (7,8,12)):
    new='OTHER_SPECIES';reason='Paragraph describes clam husbandry; no tilapia numeric applicability.'
   if n==470 and para<=10: new='OTHER_SPECIES';reason='Crucian carp paragraph, not Japanese eel.'
   if n==107 and para in (2,4,5,6): new='OTHER_SPECIES';reason='Beanfish-specific husbandry numbers, not mullet/milkfish.'
   if n in (348,436,472):
    if '傳統的日本鰻養殖' in t: new='鰻魚';reason='Only explicit Japanese-eel grading clause applicable; other giant-mottled-eel claims remain out of scope.'
    elif '浮性' in t and '30' in t: new='GENERAL_FEED_PHYSICAL';reason='Floating-feed physical/device property; no biological rates transferred.'
    else: new='GIANT_MOTTLED_EEL_ONLY';reason='Article explicitly concerns 鱸鰻; Anguilla japonica applicability not established.'
   if n==434 and para==1: new='GENERAL_AQUACULTURE';reason='Explicit general pond organic-load and oxygen mechanism; no species-specific threshold.'
   if n==742 and para in (3,4,5,6): new='GENERAL_DIAGNOSTIC_PROCESS';reason='General seek-diagnosis principle only; historical legal citations are not verified current law.'
  if new is not None and new!=scope:
   c.execute('update chunks set species_scope=? where chunk_id=?',(new,cid));overrides.append({'chunk_id':cid,'old_scope':scope,'new_scope':new,'basis':reason,'method':'source paragraph / explicitly named taxon review; NOT_HUMAN_GOLD'})
 # Fragmented unpaired numerical cells and anecdotal interpretation are not standalone evidence.
 quality_ex=[]
 for cid in ['TFRI-114846-0411-C10','TFRI-114846-0411-C15','TFRI-114846-0411-C16','TFRI-114846-0750-C01','TFRI-114846-0750-C02']:
  if c.execute('select 1 from chunks where chunk_id=?',(cid,)).fetchone():
   c.execute("update chunks set retrieval_eligible=0,retrieval_status='CONTEXT_ONLY' where chunk_id=?",(cid,));quality_ex.append(cid)
 # Add exact Japanese-eel clause and the feed-device fact as independent spans of existing OGL records.
 # They retain the existing source-record identity (not new independent sources).
 for key,parent,needle,scope in [
 ('JAPAN-GRADING','TFRI-114846-0348-C09','傳統的日本鰻養殖，是放養後2個月開始篩選，然後每約1個月或1個半月篩選1次。','鰻魚'),
 ('FEED-FRAME','TFRI-114846-0348-C20','浮性飼料是經高溫與高壓製粒，一般投餵後能漂浮在水面超過30分鐘以上','GENERAL_FEED_PHYSICAL')]:
  row=dict(c.execute('select * from chunks where chunk_id=?',(parent,)).fetchone());rec=dict(c.execute('select * from source_records where source_record_id=?',(row['source_record_id'],)).fetchone());payload=json.loads(rec['original_record_json']);raw=payload['description'];pos=raw.find(needle)
  if pos<0 and key=='FEED-FRAME':
   needle='一般投餵後能漂浮在水面超過30分鐘以上';pos=raw.find(needle)
  assert pos>=0
  # Kept as a fact audit anchor. No duplicate chunk: the original supporting chunk remains indexed.
  facts.append({'fact_id':key,'source_id':row['source_id'],'source_record_id':row['source_record_id'],'chunk_id':parent,'source_version':row['source_version'],'original_sha256':row['source_sha256'],'raw_field_pointer':'/description','exact_original_quote':needle,'quote_start':pos,'quote_end':pos+len(needle),'species_scope':scope.split('|'),'not_independent_of_parent_record':True})
 c.commit()
 # Only the newly added original fact representations need new embeddings.
 tags=requests.get('http://127.0.0.1:11434/api/tags',timeout=20).json()['models'];assert any(r['name']=='bge-m3:latest' and r['digest'].removeprefix('sha256:')=='7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab' for r in tags)
 res=requests.post('http://127.0.0.1:11434/api/embed',json={'model':'bge-m3:latest','input':[t for _,t in added]},timeout=240);res.raise_for_status();vecs=res.json()['embeddings'];assert len(vecs)==len(added)
 for (cid,t),v in zip(added,vecs):
  a=np.asarray(v,dtype=np.float32);assert a.shape==(1024,) and np.isfinite(a).all();a/=np.linalg.norm(a);c.execute('update chunks set embedding=? where chunk_id=?',(a.tobytes(),cid))
 # Rebuild FTS only in the copied, successor database.
 def toks(t):
  out=[]
  for s in re.findall(r'[\u3400-\u9fff]+',t):out.extend(s[i:i+2] for i in range(max(1,len(s)-1)))
  out+=re.findall(r'[a-z0-9]+(?:[._/-][a-z0-9]+)*',t.lower());return ' '.join(out)
 c.execute('delete from chunks_fts')
 for cid,t,sid in c.execute('select chunk_id,text,source_id from chunks where retrieval_eligible=1').fetchall():c.execute('insert into chunks_fts(chunk_id,fts_text,source_id) values (?,?,?)',(cid,toks(t),sid))
 c.commit();integrity=c.execute('pragma integrity_check').fetchone()[0];assert integrity=='ok'
 counts={k:c.execute(sql).fetchone()[0] for k,sql in {'sources':'select count(*) from sources','unique_raw_sha256':'select count(distinct source_sha256) from sources','chunks':'select count(*) from chunks','retrieval_eligible_chunks':'select count(*) from chunks where retrieval_eligible=1','context_only_chunks':"select count(*) from chunks where retrieval_status='CONTEXT_ONLY'",'fts_rows':'select count(*) from chunks_fts','embedding_1024':'select count(*) from chunks where retrieval_eligible=1 and embedding_dimension=1024 and length(embedding)=4096'}.items()}
 source_rows=[dict(r) for r in c.execute('select source_id,count(*) as chunks,sum(retrieval_eligible) as eligible from chunks group by source_id')]
 c.close();jl('finite_fact_provenance.jsonl',facts);jl('chunk_scope_corrections.jsonl',overrides)
 dump('corpus_successor_manifest.json',{'corpus_version':'3.0.1-evidence-alignment','parent_version':'3.0.0','parent_sha256':'323f9c4c1913d9d7322d695f68d021b8c20323bab30cf8a094083d8dab5cd821','database':str(DB),'database_sha256':sha(DB),'counts':counts,'sources':source_rows,'new_finite_original_fact_records':len(added),'new_pdf_fulltexts_ingested':0,'scope_override_count':len(overrides),'context_only_quality_blocks':quality_ex,'sqlite_integrity':integrity,'historical_snapshot_modified':False})
 print(json.dumps(counts));print('Scope corrections',len(overrides),'finite fact records',len(added))

if __name__=='__main__':main()


