import pathlib,pymupdf,json,re
repo=pathlib.Path(r'C:\my project\115_marine_project')
for fn,pg in [('tfrin_technical_manual_17_lower_full.pdf',91),('tfrin_golden_seabass_biosecurity_handbook_final_2025.pdf',52)]:
 d=pymupdf.open(repo/'data/recovery/raw_sources'/fn)
 for ix in [pg-1,pg-2,pg]:
  if 0<=ix<len(d):
   t=d[ix].get_text()
   print(json.dumps({'file':fn,'index0':ix,'sample':t[:3000]},ensure_ascii=True))
