from pathlib import Path
import html
from docx import Document
from docx.text.paragraph import Paragraph
from docx.table import Table
W=Path(__file__).resolve().parent;d=Document(W/'thesis_results_chapter_zh_tw.docx');parts=[];txt=[];sec=0;table_n=0
parts.append('<article id="section-0">')
for node in d.element.body:
 if node.tag.endswith('}p'):
  p=Paragraph(node,d);text=p.text
  if node.xpath('.//w:br[@w:type="page"]'):
   sec+=1;parts.append(f'</article><article id="section-{sec}">');continue
  if not text:continue
  style=p.style.name;tag='h1' if style=='Title' else 'h2' if style=='Heading 1' else 'h3' if style=='Heading 2' else 'p';cl='caption' if style=='Caption' else 'subtitle' if style=='Subtitle' else ''
  parts.append(f'<{tag} class="{cl}">{html.escape(text)}</{tag}>');txt.append(text)
 elif node.tag.endswith('}tbl'):
  table_n+=1;t=Table(node,d);parts.append(f'<div class="table-wrap" id="table-{table_n}"><table>')
  for ri,row in enumerate(t.rows):
   tag='th' if ri==0 else 'td';parts.append('<tr>'+''.join(f'<{tag}>'+html.escape(c.text).replace('\n','<br>')+f'</{tag}>' for c in row.cells)+'</tr>');txt.append('\t'.join(c.text.replace('\n',' ') for c in row.cells))
  parts.append('</table></div>')
parts.append('</article>')
style='''body{margin:0;background:#eef1f3;color:#111;font:16px/1.75 "Microsoft JhengHei",sans-serif}main{max-width:1050px;margin:28px auto;padding:0 16px}article{background:white;margin:0 0 24px;padding:42px 48px;border:1px solid #d7dce0}h1{font-size:30px;margin:0 0 12px}h2{font-size:23px;margin:0 0 18px}p{margin:0 0 16px}.subtitle{font-size:19px}.caption{font-size:13px;margin:14px 0 7px;color:#404750}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.6;margin:8px 0 12px}th,td{border:1px solid #d9d9d9;padding:9px 8px;vertical-align:middle}th{background:#e7eef4;color:black}td:not(:first-child){text-align:center}tr:nth-child(even)td{background:#f7f8fa}.notice{max-width:1050px;margin:20px auto 0;padding:0 16px;font-size:13px;color:#44515b}@media print{body{background:white;font-size:10pt}main{margin:0;max-width:none;padding:0}article{border:0;margin:0;padding:0;break-before:page}article:first-child{break-before:auto}.notice{display:none}tr{break-inside:avoid}thead{display:table-header-group}}'''
page='<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Corpus v3 凍結評測研究結果</title><style>'+style+'</style></head><body><div class="notice">來源核驗型探索性研究結果　Human Gold 0　所有表格由保存結果重算</div><main>'+''.join(parts)+'</main></body></html>'
(W/'thesis_results_chapter_zh_tw.html').write_text(page,encoding='utf-8');(W/'thesis_results_chapter_zh_tw.txt').write_text('\n\n'.join(txt)+'\n',encoding='utf-8');print('HTML and text chapter exported',sec+1,'sections')
