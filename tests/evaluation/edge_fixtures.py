"""Synthetic fixtures: no physical-device requests and no real benchmark results."""
import json
import platform
from copy import deepcopy
from pathlib import Path
from src.evaluation.edge.core import digest


def target():
    t=json.loads(Path('configs/edge_target_device.yaml').read_text(encoding='utf-8'))
    t.update(target_device_confirmed=True,device_name='Synthetic test target',device_id='synthetic-only',execution_node=platform.node())
    t['CPU']['name']='Synthetic CPU';t['RAM']['bytes']=16*1024**3
    t['GPU'].update(available=False);t['NPU'].update(available=False)
    t['OS'].update(name='Synthetic OS',version='test')
    t['runtime'].update(name='Ollama',version='0.35.0',endpoint='http://127.0.0.1:11434')
    t['storage']['device']='synthetic'
    return t


class FakeResponse:
    def __init__(self,events):self.events=events;self.encoding=None
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def raise_for_status(self):pass
    def iter_lines(self,**kwargs):
        for e in self.events:yield json.dumps(e,ensure_ascii=False)


class FakeSession:
    def __init__(self,events):self.events=events;self.bodies=[]
    def post(self,*args,**kwargs):self.bodies.append(kwargs['json']);return FakeResponse(self.events)


def events():
    raw=json.dumps({'question_id':'test_q','status':'answered','answer':'測試回答','citations':['C1']},ensure_ascii=False)
    return [{'message':{'thinking':'synthetic thought'}},
            {'message':{'content':raw}}, {'done':True,'done_reason':'stop','eval_count':10,'eval_duration':1000000000,
            'prompt_eval_count':100,'load_duration':1000}]
