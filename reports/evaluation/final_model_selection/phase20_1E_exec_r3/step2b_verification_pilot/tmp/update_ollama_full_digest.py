import json,pathlib,urllib.request
R=pathlib.Path(r'C:\my project\115_marine_project'); O=R/'reports/evaluation/final_model_selection/phase20_1E_exec_r3/step2b_verification_pilot'
p=O/'compatibility.json'; d=json.loads(p.read_text(encoding='utf-8'))
expected={'deepseek-r1:7b':'755ced02ce7befdb13b7ca74e1e4d08cddba4986afdb63a480f2c93d3140383f','qwen2.5-coder:7b':'dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364','hf.co/bartowski/DeepSeek-R1-Distill-Llama-8B-GGUF:Q4_K_M':'aab87d0e8a585cc6260d3a448e3f66ff2057d1cd6975c834151deeb1eae94b42','gemma2:9b':'ff02c3702f322b9e075e9568332d96c0a7028002f1a5a056e0a6784320a4db0b','mistral-nemo:12b-instruct-2407-q4_K_M':'daf6737417121831e572a9c482e92a221ee0c33537f35f1f857c7b4f7191df55'}
with urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=5) as r: tags=json.load(r)['models']
actual={x['name']:x for x in tags}; checks={n:{'expected_digest':v,'actual_digest':actual.get(n,{}).get('digest'),'size_bytes':actual.get(n,{}).get('size'),'matches':actual.get(n,{}).get('digest')==v} for n,v in expected.items()}
d['ollama_api_tags_full_digest_checks']=checks
d['overall_protected_compatibility_pass']=bool(d['overall_protected_compatibility_pass'] and all(x['matches'] for x in checks.values()))
p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'all_full_digests_match':all(x['matches'] for x in checks.values()),'models':checks},ensure_ascii=False))
