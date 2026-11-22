import pathlib,pymupdf,json,re
repo=pathlib.Path(r'C:\my project\115_marine_project')
for fn, terms in [('tfrin_technical_manual_17_lower_full.pdf',['5 psu','鹽度在5 psu','冬季或氣候不佳時','ORP 在養殖期間','成魚養殖池水深']),('tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf',['5 psu','Piscicola sp.'])]:
 d=pymupdf.open(repo/'data/recovery/raw_sources'/fn)
 for term in terms:
  hits=[]
  norm=lambda s: re.sub(r'\s+','',s)
  for i,p in enumerate(d):
   t=p.get_text()
   if norm(term) in norm(t): hits.append({'page_index1':i+1,'text':t[:180]})
  print(json.dumps({'file':fn,'term':term,'hits':hits[:10]},ensure_ascii=True))
