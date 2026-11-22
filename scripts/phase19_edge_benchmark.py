"""Prepare by default. --execute is blocked until a real named target passes all gates."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--target',type=Path)
    args=parser.parse_args()
    if args.execute:
        from src.evaluation.edge.runner import execute
        from src.evaluation.edge.runtime import TargetBlocked
        try:
            folder=execute(target_path=args.target)
            from src.evaluation.edge.runner import read_rows
            from src.evaluation.edge.report import compile_reports,write_json
            manifest=json.loads((folder/'experiment_manifest.json').read_text(encoding='utf-8'))
            for name,value in compile_reports(manifest,read_rows(folder/'warm_runs.jsonl'),read_rows(folder/'cold_runs.jsonl')).items():
                write_json(folder/(name+'.json'),value)
            print(folder,flush=True)
        except TargetBlocked as exc:
            print(json.dumps({'edge_execution_ready':False,'status':'blocked','reason':str(exc)}),flush=True)
            raise SystemExit(2)
    else:
        from src.evaluation.edge.report import prepare
        m=prepare()
        print(json.dumps({k:m[k] for k in ('status','edge_execution_ready','acceptance_thresholds_defined','question_count','models')}),flush=True)
