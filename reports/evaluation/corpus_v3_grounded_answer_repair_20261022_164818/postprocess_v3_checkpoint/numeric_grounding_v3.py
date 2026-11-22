"""Domain-number tokenizer; identifiers and list markers are not measurements.

This is a uniform post-run parser correction, not a change to frozen generation.
No question ID, species, expected answer or known test value is embedded here.
"""
import re,unicodedata
def numeric(s,ignore_identifiers=()):
 s=unicodedata.normalize('NFKC',s)
 # Complete opaque document/chunk identifiers. Citation legitimacy is checked
 # separately against the actual supplied source IDs before this tokenizer.
 for identifier in sorted(set(ignore_identifiers),key=len,reverse=True):
  s=re.sub(r'(?<![A-Za-z0-9_-])'+re.escape(identifier)+r'(?![A-Za-z0-9_-])',' ',s)
 s=re.sub(r'(?:手冊|文件)\s*\d+(?![\d.°℃%])',' ',s)
 s=re.sub(r'(^|[\n:：;；。])\s*\d+\.\s+(?=\D)',r'\1',s)
 # Only true thousands separators are removed. Removing a punctuation comma
 # between "30°C,30°C" had concatenated a letter and a number, matching tail 0.
 s=re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))','',s)
 return re.findall(r'(?<![A-Za-z_0-9])\d+(?:\.\d+)?',s)
