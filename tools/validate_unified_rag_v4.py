"""Mechanical checks, explicitly not an expert semantic correctness benchmark."""
import json
import sqlite3
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.unified_rag_v4.common import clean,digest,dump,sha_file
from src.unified_rag_v4.extraction import create_archive_schema,add_element,local_caption
from src.unified_rag_v4.segmentation import segment_document,split_long
from src.unified_rag_v4.retrieval import UnifiedRetriever
from src.unified_rag_v4.evidence import span_registry,bind_quotes,output_schema

pointer=json.loads((ROOT/'research_staging/unified_rag_active.json').read_text(encoding='utf-8'));work=Path(pointer['workspace']);report=Path(json.loads((ROOT/'research_staging/unified_rag_build_pointer.json').read_text())['report_directory'])
checks=[]
def check(name,condition,detail=None):
    checks.append({'name':name,'passed':bool(condition),'detail':detail})
check('Cleaning preserves chemical units and fish distinctions',clean('吳郭魚\x00\r\n烏魚 5 mg/L ㎎ μg ℃')=='吳郭魚\n烏魚 5 mg/L ㎎ μg ℃')
sentence='若水溫低於18℃，須保留原文條件。' * 120
parts=split_long(sentence)
check('Sentence splitting preserves every numeric and condition character',''.join(parts).replace('\n','')==sentence)
check('Cross-column figure captions are rejected',local_caption([(1,[400,220,580,260],'圖2 鰻魚')],[20,100,180,210])=='')
check('A same-column caption is bound to the nearest image',local_caption([(1,[20,220,180,260],'圖2 鰻魚')],[20,100,180,210])=='圖2 鰻魚')
fake=UnifiedRetriever.__new__(UnifiedRetriever)
fishrow={'chunk_id':'test','source_id':'test','species_scope':['烏魚'],'taxonomy_level':'SPECIES_EXPLICIT','restrictions_json':{}}
fake.map={'test':fishrow};check('Tilapia is not mullet',not fake.scope_check('吳郭魚如何管理','吳郭魚',fishrow)[0])
fishrow['species_scope']=['鱸魚','金目鱸'];check('Narrow sea-bass physiology is not generalized',not fake.scope_check('鱸魚的適溫','鱸魚',fishrow)[0])
statrow={'chunk_id':'test','source_id':'DGBAS-79395-2020','species_scope':[],'taxonomy_level':'STATISTICAL_NATIVE_FIELDS_ONLY','restrictions_json':{'scope_kind':'STATISTICAL_NATIVE_FIELDS_ONLY'}}
check('Statistical areas cannot become disease evidence',not fake.scope_check('2020年鰻魚疾病統計','鰻魚',statrow)[0])
check('Single-year admission cannot become a cross-year comparison',not fake.scope_check('比較2015與2020養殖統計','鰻魚',statrow)[0])
code={'chunk_id':'test','source_id':'FA-SPECIES-CODE','species_scope':[],'taxonomy_level':'NAME_CODE_LOOKUP_ONLY','restrictions_json':{'scope_kind':'NAME_CODE_LOOKUP_ONLY','native_record':{'中文名稱':'黑(魚或)','學名':'Atrobucca nibe','俗名':'黑喉、臭魚、黑口、烏喉'}}}
check('Blackmouth croaker is not mullet even though 烏喉 contains 烏',not fake.scope_check('烏魚的學名欄位','烏魚',code)[0])
code['restrictions_json']['native_record']={'中文名稱':'鯔','學名':'Mugil cephalus','俗名':'正烏、烏魚'}
check('Mullet original scientific name and exact common-name field qualify',fake.scope_check('烏魚的學名欄位','烏魚',code)[0])
code['restrictions_json']['native_record']={'中文名稱':'日本真鱸','學名':'Lateolabrax japonicus','俗名':'七星鱸、花鱸、鱸魚'}
check('Narrow barramundi query cannot use Japanese sea perch name code',not fake.scope_check('金目鱸的分類代碼與學名','鱸魚',code)[0])
code['restrictions_json']['native_record']={'中文名稱':'四指馬鮁','學名':'Eleutheronema tetradactylum','俗名':'午仔魚'}
check('Fourfinger threadfin code is never an eel name record',not fake.scope_check('鰻魚的官方學名','鰻魚',code)[0])
mem=sqlite3.connect(':memory:');mem.row_factory=sqlite3.Row;create_archive_schema(mem)
add_element(mem,'D',1,'TABLE','魚種 | 溶氧\n吳郭魚 | 5',metadata={'cells':[['魚種','溶氧(mg/L)'],['吳郭魚','5']],'missing_cells':0})
segments=segment_document(mem,'D');check('A complete small table preserves its header and value',len(segments)==1 and '溶氧(mg/L)' in segments[0]['text'] and '5' in segments[0]['text']);mem.close()
mem=sqlite3.connect(':memory:');mem.row_factory=sqlite3.Row;create_archive_schema(mem)
add_element(mem,'LIST',1,'PARAGRAPH','1991年，種類包括其他「如田貝',ordinal=0)
add_element(mem,'LIST',1,'PARAGRAPH','幼生寄生症及其他種類」等。',ordinal=1)
joined=segment_document(mem,'LIST');check('PDF soft wraps do not sever an open species list',len(joined)==1 and '田貝幼生' in joined[0]['text']);mem.close()
c={'chunk_id':'C1','text':'1991年，來源記載車輪蟲與指環蟲。','source_quote':'1991年，來源記載車輪蟲與指環蟲。'}
registry=span_registry([c]);sid=next(iter(registry))
converted,bound=bind_quotes({'answer':'來源提到車輪蟲。','answer_status':'ANSWERED_PARTIAL','missing_information':[],'evidence':[{'span_ids':[sid],'supported_answer_element':'原文所列寄生蟲'}]},registry,[c])
check('Source identities and full condition context are program-owned',converted['supporting_chunk_ids']==['C1'] and converted['evidence'][0]['quote']==c['text'])
rejected=False
try: bind_quotes({'evidence':[{'span_ids':['DOES_NOT_EXIST'],'supported_answer_element':'invalid'}]},registry,[c])
except ValueError: rejected=True
check('Nonexistent evidence span identifiers are rejected',rejected)
p=Path(json.loads((work/'corpus_manifest.json').read_text(encoding='utf-8'))['database']);con=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True);con.row_factory=sqlite3.Row
files=list(con.execute('SELECT * FROM document_files'))
bad=[r['path'] for r in files if sha_file(r['path'])!=r['sha256']]
check('Every raw file still has the input SHA-256',not bad,{'files':len(files),'changed':bad})
check('All 53 my_data files have extracted elements',con.execute('SELECT count(DISTINCT f.path) FROM document_files f JOIN document_elements e USING(document_id) WHERE is_my_data=1').fetchone()[0]==53)
unindexed=con.execute('SELECT count(*) FROM chunks WHERE retrieval_eligible=1 AND (embedding IS NULL OR length(embedding)!=4096 OR embedding_dimension!=1024)').fetchone()[0]
check('Every eligible text/table/caption vector has 1024 Float32 dimensions',unindexed==0,unindexed)
leaks=con.execute("SELECT count(*) FROM unified_fts f JOIN chunks c USING(chunk_id) JOIN sources s USING(source_id) WHERE s.source_id LIKE 'MYDATA-%' AND s.license_scope_status IN ('FULLTEXT_USAGE_BASIS_UNVERIFIED','EXPLICIT_RESTRICTION_FULLTEXT_QUARANTINED')").fetchone()[0]
check('Restricted document fulltext is absent from the answer FTS',leaks==0)
bad_images=con.execute('SELECT count(*) FROM image_embeddings WHERE length(embedding)!=dimension*4 OR dimension!=512').fetchone()[0]
check('Actual CLIP image vectors have 512 Float32 dimensions',bad_images==0)
check('No synthetic test or fish-test questions were put in chunks',con.execute("SELECT count(*) FROM chunks WHERE chunk_id LIKE 'FT-%' OR source_id LIKE 'TEST-%'").fetchone()[0]==0)
check('SQLite integrity passes',con.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
con.close()
result={'check_count':len(checks),'passed':sum(r['passed'] for r in checks),'failed':sum(not r['passed'] for r in checks),'checks':checks,'not_human_gold':True,'semantic_expert_accuracy_measured':False}
dump(report/'pipeline_validation.json',result);print(json.dumps(result,ensure_ascii=False))
if result['failed']: raise SystemExit(1)
