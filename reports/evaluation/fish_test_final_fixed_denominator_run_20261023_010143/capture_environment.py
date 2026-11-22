import sys,json,importlib.metadata as md
from pathlib import Path
names=['pytest','streamlit','requests','jsonschema','psutil','numpy','torch','transformers','openpyxl']
versions={}
for name in names:
 try:versions[name]=md.version(name)
 except md.PackageNotFoundError:versions[name]={'version':None,'reason':'No distribution metadata visible in this interpreter/path; not a claim that runtime API or protected environments lack it'}
(Path(__file__).parent/'environment_versions.json').write_text(json.dumps({'interpreter':sys.executable,'python':sys.version,'sys_path':sys.path,'versions':versions},ensure_ascii=False,indent=2),encoding='utf-8')
print(versions)
