"""Normal HTTPS downloads from the named upstream; no proxies or access bypasses."""
import hashlib
import json
import time
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
work = Path(json.loads((root / 'research_staging/unified_rag_build_pointer.json').read_text(encoding='utf-8'))['workspace'])
out = work / 'upstream'
out.mkdir(exist_ok=True)
manifest_path=out/'download_manifest.json'
records=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else []
def fetch(url, path):
    if path.exists() and path.stat().st_size:
        return
    started = time.monotonic()
    with urllib.request.urlopen(url, timeout=60) as response, path.open('wb') as target:
        size = 0
        while part := response.read(2**20):
            target.write(part)
            size += len(part)
            if size % (100*2**20) == 0:
                print(json.dumps({'download': path.name, 'bytes': size}), flush=True)
    records[:]=[r for r in records if r.get('file')!=str(path)]
    records.append({'url': url, 'file': str(path), 'bytes': path.stat().st_size,
                    'sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(),
                    'obtained_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'seconds': time.monotonic()-started})
    print(json.dumps(records[-1], ensure_ascii=False), flush=True)

try:
    metadata = json.load(urllib.request.urlopen('https://huggingface.co/api/models/openai/clip-vit-base-patch32', timeout=40))
    revision = metadata['sha']
    (out/'clip_upstream_metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    dest = work/'models/clip-vit-base-patch32'
    dest.mkdir(parents=True, exist_ok=True)
    for name in ['config.json', 'preprocessor_config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'vocab.json', 'merges.txt', 'pytorch_model.bin']:
        fetch('https://huggingface.co/openai/clip-vit-base-patch32/resolve/'+revision+'/'+name, dest/name)
    (dest/'revision.json').write_text(json.dumps({'model':'openai/clip-vit-base-patch32','revision':revision}),encoding='utf-8')
except Exception as exc:
    records.append({'component':'CLIP','error':repr(exc),'no_third_party_mirror_used':True})
for name,url in [
    ('tfrin_website_license.html','https://www.tfrin.gov.tw/ws.php?id=523'),
    ('tfrin_eel_parasites.pdf','https://www.tfrin.gov.tw/redirect_files.php?file_name=PLAkufpcOgoZRKZ9OwWGEqualG6pqTSq1sCzn6PFKbkjMbC2pX&id=13349'),
    ('tfrin_eel_other_parasites.pdf','https://www.tfrin.gov.tw/redirect_files.php?file_name=tWGPlusJZ1a0xapuQnH6CtBdy6UBkwO9xJ2d6ElYDIvVxlVO52qGnx2MAANQ69dSerSRd&id=13353'),
    ('tfrin_eel_mold.pdf','https://www.tfrin.gov.tw/redirect_files.php?file_name=IWGPlusRsGX3pv9XwE8txc0WGEqualUmWGPluslwUhgpFf90tBGSCnpVSNpA&id=13351'),
    ('tfrin_eel_gills.pdf','https://www.tfrin.gov.tw/redirect_files.php?file_name=585WpJUqMWGSlashvzqJAWGEqual7dYcLbz8DXnuP7Kez74zdvzOUx4B&id=13352'),
    ('tfrin_freshwater_disease.pdf','https://www.tfrin.gov.tw/redirect_files.php?file_name=JYDhZ4AHgWGEqualWGEqual8kP9vjWGPlusWGPlusFzh3X&id=13300')]:
    try: fetch(url, out/name)
    except Exception as exc: records.append({'url':url,'error':repr(exc)})
manifest_path.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
