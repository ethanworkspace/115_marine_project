"""Explicit local-only Ollama adapters; native RAGAS metric prompts are unchanged."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Callable

import requests

ENDPOINT = 'http://127.0.0.1:11434'
JUDGE_MODEL = 'qwen2.5-coder:7b'
JUDGE_DIGEST = 'dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364'
EMBED_MODEL = 'bge-m3:latest'
EMBED_DIGEST = '7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab'
OPTIONS = {'temperature': 0, 'top_p': 1, 'seed': 16016, 'num_predict': 4096, 'num_ctx': 16384}
MAX_ATTEMPTS = 2
ADAPTER_VERSION = 'phase16_ollama_native_schema_v1'


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def append_jsonl(path: Path, row: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as out:
        out.write(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n')


def technical_retry(call: Callable[[], dict], validate: Callable[[str], object], save: Callable[[dict], None]) -> object:
    """Exactly one fresh retry on transport/JSON/schema failures; never repair text."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        start = time.perf_counter()
        response = {}
        raw = ''
        row = {'attempt_number': attempt, 'json_parse_status': False, 'schema_status': False,
               'raw_output': '', 'raw_output_sha256': sha_text(''), 'failure_reason': None}
        try:
            response = call()
            raw = str((response.get('message') or {}).get('content') or '')
            row.update(raw_output=raw, raw_output_sha256=sha_text(raw),
                       raw_response=response, thinking=(response.get('message') or {}).get('thinking'),
                       finish_reason=response.get('done_reason'), prompt_tokens=response.get('prompt_eval_count'),
                       completion_tokens=response.get('eval_count'))
            if response.get('done') is not True or response.get('done_reason') != 'stop':
                raise RuntimeError('technical_completion_failure:' + str(response.get('done_reason')))
            json.loads(raw)  # no extract_json, fence stripping, or semantic repair
            row['json_parse_status'] = True
            parsed = validate(raw)
            row['schema_status'] = True
            return parsed
        except Exception as exc:
            last_error = exc
            row['failure_reason'] = type(exc).__name__ + ': ' + str(exc)
        finally:
            row['latency_seconds'] = time.perf_counter() - start
            save(row)
    raise RuntimeError('judge_failed_after_two_attempts: ' + str(last_error)) from last_error


def schema_from_prompt(prompt: str) -> dict:
    marker = 'following schema as specified in JSON Schema:\n'
    if marker not in prompt:
        raise ValueError('Native RAGAS JSON schema not found in prompt; refusing a guess')
    return json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1])[0]


def local_inventory() -> dict:
    tags = requests.get(ENDPOINT + '/api/tags', timeout=20)
    tags.raise_for_status()
    version = requests.get(ENDPOINT + '/api/version', timeout=10)
    version.raise_for_status()
    models = tags.json().get('models') or []
    judge = next((m for m in models if m['name'] == JUDGE_MODEL), None)
    embedding = next((m for m in models if m['name'] == EMBED_MODEL), None)
    if judge is None or judge.get('digest') != JUDGE_DIGEST:
        raise RuntimeError('blocked_evaluator_runtime: specified local judge is absent or changed')
    if embedding is None or embedding.get('digest') != EMBED_DIGEST:
        raise RuntimeError('blocked_embedding_runtime: frozen BGE-M3 is absent or changed')
    if version.json().get('version') != '0.35.0':
        raise RuntimeError('Ollama runtime differs from frozen 0.35.0')
    show = requests.post(ENDPOINT + '/api/show', json={'model': JUDGE_MODEL}, timeout=30)
    show.raise_for_status()
    return {'available_models': models, 'selected_judge': JUDGE_MODEL, 'model_digest': JUDGE_DIGEST,
            'runtime': 'Ollama', 'runtime_version': version.json()['version'],
            'model_show': show.json(), 'context_length': OPTIONS['num_ctx'],
            'selection_rule': 'User explicitly approved the existing Qwen judge after DeepSeek-R1 8B exhausted the fixed 4096-token evaluation budget. All primary and repeatability scores use Qwen only after preflight; DeepSeek partial results remain diagnostic. No model acquisition or cloud judge.',
            'judge_limitation': 'Code-specialized local 7B judge; evaluator judgments are not human expert verification.',
            'self_judge': False, 'endpoint': ENDPOINT,
            'embedding': {'model': EMBED_MODEL, 'digest': EMBED_DIGEST, 'dimension': 1024,
                          'normalization': 'L2 per vector; cosine in RAGAS', 'runtime': 'Ollama 0.35.0'}}


def make_adapters(trace_path: Path):
    # Lazy imports keep the production environment free of evaluation dependencies.
    from jsonschema import Draft202012Validator
    from langchain_core.outputs import Generation, LLMResult
    from ragas.llms import BaseRagasLLM
    from ragas.embeddings import BaseRagasEmbeddings
    from ragas.run_config import RunConfig

    class OllamaJudge(BaseRagasLLM):
        def __init__(self):
            super().__init__(run_config=RunConfig(max_retries=1, timeout=1800))
            self.identity = {}
            self.call_count = 0
            self.retry_count = 0
            self.attempt_count = 0

        def is_finished(self, response):
            return True  # _call already requires done_reason=stop and schema-valid JSON

        def _call(self, prompt: str, sample_index: int) -> str:
            schema = schema_from_prompt(prompt)
            validator = Draft202012Validator(schema)
            payload = {'model': JUDGE_MODEL, 'messages': [{'role': 'user', 'content': prompt}],
                       'format': schema, 'stream': False, 'think': False,
                       'keep_alive': '30m', 'options': dict(OPTIONS)}
            self.call_count += 1
            call_id = self.call_count
            def call():
                r = requests.post(ENDPOINT + '/api/chat', json=payload, timeout=1800)
                r.raise_for_status()
                return r.json()
            def validate(raw):
                parsed = json.loads(raw)
                validator.validate(parsed)
                return raw
            def save(row):
                self.attempt_count += 1
                self.retry_count += int(row['attempt_number'] == 2)
                append_jsonl(trace_path, {**self.identity, 'call_id': call_id, 'sample_index': sample_index,
                            'prompt': prompt, 'prompt_sha256': sha_text(prompt), 'output_schema': schema,
                            'request_sha256': sha_text(json.dumps(payload, sort_keys=True)), **row})
            return technical_retry(call, validate, save)

        def generate_text(self, prompt, n=1, temperature=.01, stop=None, callbacks=None):
            # n=3 is the native AnswerRelevancy strictness. Each draw uses frozen options.
            return LLMResult(generations=[[Generation(text=self._call(prompt.to_string(), i)) for i in range(n)]])

        async def agenerate_text(self, prompt, n=1, temperature=.01, stop=None, callbacks=None):
            return self.generate_text(prompt, n, temperature, stop, callbacks)

        async def generate(self, prompt, n=1, temperature=None, stop=None, callbacks=None):
            # Bypass RAGAS transport retries. The adapter has exactly two attempts per call.
            return await self.agenerate_text(prompt, n, temperature, stop, callbacks)

    class OllamaEmbeddings(BaseRagasEmbeddings):
        def __init__(self):
            super().__init__()
            self.run_config = RunConfig(max_retries=1, timeout=300)
            self.memo = {}

        def embed_documents(self, texts):
            missing = list(dict.fromkeys(t for t in texts if t not in self.memo))
            if missing:
                r = requests.post(ENDPOINT + '/api/embed', json={'model': EMBED_MODEL, 'input': missing,
                                  'truncate': False, 'keep_alive': '30m'}, timeout=300)
                r.raise_for_status()
                vectors = r.json()['embeddings']
                if len(vectors) != len(missing):
                    raise ValueError('BGE-M3 embedding count mismatch')
                for text, vector in zip(missing, vectors):
                    norm = math.sqrt(sum(float(x) ** 2 for x in vector))
                    if len(vector) != 1024 or not math.isfinite(norm) or norm == 0:
                        raise ValueError('BGE-M3 dimension/finite/normalization check failed')
                    self.memo[text] = [float(x) / norm for x in vector]
            return [self.memo[t] for t in texts]

        def embed_query(self, text):
            return self.embed_documents([text])[0]

        async def aembed_documents(self, texts):
            return self.embed_documents(texts)

        async def aembed_query(self, text):
            return self.embed_query(text)

    return OllamaJudge(), OllamaEmbeddings()


def make_metrics(judge, embeddings):
    from ragas.metrics import Faithfulness, AnswerRelevancy, AnswerCorrectness
    from ragas.run_config import RunConfig
    metrics = {'faithfulness': Faithfulness(llm=judge),
               'answer_relevancy': AnswerRelevancy(llm=judge, embeddings=embeddings, strictness=3),
               'silver_reference_correctness': AnswerCorrectness(llm=judge, embeddings=embeddings, weights=[.75, .25], beta=1.0)}
    for metric in metrics.values():
        metric.init(RunConfig(max_retries=1, timeout=1800))
    return metrics
