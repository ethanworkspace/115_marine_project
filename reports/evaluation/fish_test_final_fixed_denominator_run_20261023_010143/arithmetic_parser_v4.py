"""Select an explicitly claimed result by syntax/unit role, never by Gold matching."""
import re,unicodedata
from decimal import Decimal
def parse_arithmetic(answer,calc):
 text=unicodedata.normalize('NFKC',answer).translate(str.maketrans({'应':'應','对':'對','宽':'寬','为':'為','计':'計','总':'總','结':'結','减':'減'}))
 text=re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))','',text)
 unit=calc['unit'];num=r'(-?\d+(?:\.\d+)?)\s*(萬|万)?\s*'
 suffix={'尾':r'尾','kg':r'(?:kg|公斤|千克)','°C':r'(?:°\s*C|℃|攝氏度|度C?|度)','ppt':r'(?:ppt|‰)','psu':r'psu','個間隔':r'(?:個\s*(?:\d+(?:\.\d+)?\s*(?:個)?月(?:的)?)?\s*間隔|次)'}
 found=[]
 for m in re.finditer(num+suffix.get(unit,re.escape(unit)),text,re.I):found.append((m,m.group(1),m.group(2)))
 if unit=='ppt':
  for m in re.finditer(r'千分之\s*(\d+(?:\.\d+)?)',text):found.append((m,m.group(1),None))
 candidates=[]
 result_words=r'(?:計算結果|結果|答案|總重量|總重|總尾數|總數|總量|合計|對應|寬度|增量|增加量|增加(?:了)?|相差|差值|差|低(?:了|出)?|高(?:了|出)?|超出|超過建議值|大約有|約有|有|difference|diff|delta)\s*(?:最多|最少)?\s*(?:為|是|約為|應為|等於|:|=)?\s*$'
 rate_pat=r'^\s*(?:[/／]\s*(?:公頃|公顷|ha|立方(?:公尺|米)|平方(?:公里|公尺|米)|m[23]|m\^[23]|L|升)|每(?:公頃|公顷|立方(?:公尺|米)))'
 for m,n,scale in sorted(found,key=lambda x:x[0].start()):
  before=text[max(0,m.start()-60):m.start()];after=text[m.end():];is_rate=bool(re.match(rate_pat,after,re.I));operand=not is_rate and bool(re.match(r'^\s*(?:[-+×÷*/=]|減|加)',after))
  role='UNMARKED';priority=0
  if re.search(result_words,before,re.I):role='EXPLICIT_RESULT_LANGUAGE';priority=4
  elif re.search(r'(?:=|等於)\s*$',before):role='EQUATION_RHS';priority=3
  if operand:role='EXPRESSION_OPERAND';priority=0
  if re.match(r'^\s*的(?:建議|來源|門檻|上限|下限)',after):role='DESCRIBED_INPUT_VALUE';priority=0
  candidates.append({'value':str(Decimal(n)*(10000 if scale else 1)),'start':m.start(),'end':m.end(),'exact_text':m.group(0),'is_rate_not_requested_total':is_rate,'role':role,'priority':priority})
 usable=[c for c in candidates if not c['is_rate_not_requested_total']]
 base={'evaluable':False,'reason':'NO_UNAMBIGUOUS_REQUESTED_RESULT','candidates':candidates,'selection_uses_expected_value':False,'unit':unit}
 if not usable:
  explicit_wrong_dimension=[c for c in candidates if c['priority']>=3 and c['is_rate_not_requested_total']]
  if explicit_wrong_dimension:return {**base,'evaluable':True,'correct':False,'parsed':explicit_wrong_dimension[-1]['value'],'unit_valid':False,'reason':'EXPLICIT_TOTAL_RESULT_HAS_RATE_DIMENSION'}
  return {**base,'reason':'ONLY_INPUT_RATES_OR_REQUIRED_RESULT_UNIT_NOT_PRESENT'}
 best=max(c['priority'] for c in usable);choices=[c for c in usable if c['priority']==best]
 if best==0 and len(usable)>1:return base
 values={Decimal(c['value']) for c in choices}
 if len(values)!=1:return {**base,'reason':'CONFLICTING_OR_MULTIPLE_EXPLICIT_RESULT_VALUES'}
 result=next(iter(values));correct=abs(result-Decimal(calc['expected']))<=Decimal(calc['tolerance'])
 return {**base,'evaluable':True,'correct':correct,'parsed':str(result),'expected':calc['expected'],'unit_valid':True,'selected_result_evidence':choices,'reason':'EXPLICIT_RESULT_ROLE_OR_SINGLE_UNAMBIGUOUS_UNIT_VALUE'}
