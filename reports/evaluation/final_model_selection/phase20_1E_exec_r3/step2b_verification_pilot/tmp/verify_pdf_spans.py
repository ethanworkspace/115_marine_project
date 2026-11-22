import hashlib,json,pathlib,re,sys
import pymupdf
repo=pathlib.Path(r'C:\my project\115_marine_project')
files={
 'manual':repo/'data/recovery/raw_sources/tfrin_technical_manual_17_lower_full.pdf',
 'biosecurity':repo/'data/recovery/raw_sources/tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf'}
spans={
 'manual':[(120,'不受污染之場地'),(124,'殘餌汙染水質'),(91,'冬季或氣候不佳時，可減少投餵頻率'),(88,'成魚養殖池水深建議至少2 公尺以深'),(94,'ORP 在養殖期間均維持在正電位')],
 'biosecurity':[(80,'臺灣常見魚蛭屬Piscicola sp.'),(52,'建議維持鹽度在5 psu 以上較佳')]}
for key,path in files.items():
 b=path.read_bytes(); doc=pymupdf.open(path)
 print(json.dumps({'file':str(path),'size':len(b),'sha256':hashlib.sha256(b).hexdigest(),'pages':len(doc),'checks':[
 {'source_page':pg,'snippet':s,'page_exact':s in doc[pg-1].get_text(),'matches_any_page':[i+1 for i in range(len(doc)) if s.replace('\n',' ') in doc[i].get_text().replace('\n',' ')][:3]} for pg,s in spans[key]]},ensure_ascii=True))
