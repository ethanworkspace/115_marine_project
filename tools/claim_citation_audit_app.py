"""Independent, blind human audit UI; never writes frozen research/production data."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.generation.frozen import read_jsonl
from src.evaluation.validity.core import human_review_event, human_no_assertion_event, digest
from src.evaluation.validity.report import human_progress
from src.evaluation.ragas_eval.runtime import append_jsonl

OUT = ROOT / 'reports/evaluation/validity/phase18'


def load_blind_records():
    records = read_jsonl(OUT / 'blind_audit_records_v2.jsonl')
    # This UI reads ONLY the public allowlisted snapshots, never private samples,
    # AI verdicts, model identity or any reference/judge score files.
    forbidden = {'generator', 'model', 'metrics', 'primary_metrics', 'judge_score', 'reference_answer'}
    for row in records:
        if set(row) & forbidden or digest(row['answer']) != row['answer_sha256']:
            raise ValueError('Blind snapshot contract violated')
    return records


def main():
    st.set_page_config(page_title='Claim-Citation 人工覆核', layout='wide')
    st.title('Claim-Citation 人工覆核')
    st.caption('盲化評估：只依回答與所引用的原文判定。這裡不顯示 AI 判定或模型身分。')
    try:
        records = load_blind_records()
    except (OSError, ValueError) as exc:
        st.error(str(exc)); st.stop()
    path = OUT / 'human_reviews.jsonl'
    events = read_jsonl(path) if path.exists() else []
    progress = human_progress(records, events)
    a,b,c = st.columns(3)
    a.metric('覆核回答', f'{progress["human_completed_outputs"]} / {progress["target_outputs"]}')
    b.metric('覆核主張', f'{progress["human_reviewed_claims"]} / {progress["total_claims"]}')
    c.metric('無可抽取主張的回答', progress['outputs_without_extracted_assertions'])
    reviewer = st.text_input('Reviewer 姓名或識別碼')
    done = {e['claim_id'] for e in events if e.get('review_source') == 'human'}
    queue = st.selectbox('覆核佇列', ['全部', '尚未完整覆核', '已完整覆核'])
    pool = records
    if queue == '尚未完整覆核':
        pool = [r for r in records if r['answer_id'] not in progress['completed_answer_ids']]
    if queue == '已完整覆核':
        pool = [r for r in records if r['answer_id'] in progress['completed_answer_ids']]
    if not pool:
        st.info('目前這個佇列沒有資料。'); st.stop()
    selected = st.selectbox('回答識別碼', [r['answer_id'] for r in pool])
    record = next(r for r in pool if r['answer_id'] == selected)
    st.subheader('Question'); st.write(record['question'])
    st.subheader('Frozen Answer'); st.text(record['answer'])
    st.write('Answer-level citations:', record['citations'])
    if not record['claims']:
        st.warning('此回答沒有抽出可判定主張。請人工確認抽取是否遺漏；覆核完成不代表答案獲 evidence 支持。')
        with st.form('no_assertion_review'):
            notes=st.text_area('人工觀察／抽取問題')
            confirm=st.checkbox('我已閱讀原文，確認目前沒有可評估主張或需要另外拆解')
            if st.form_submit_button('保存人工檢查'):
                if not reviewer.strip() or not notes.strip() or not confirm:
                    st.error('請填 reviewer、notes 並確認閱讀。')
                else:
                    event=human_no_assertion_event(record,reviewer,notes,datetime.now(timezone.utc).isoformat())
                    append_jsonl(path,event)
                    updated=human_progress(records,events+[event])
                    (OUT/'human_audit_progress.json').write_text(json.dumps(updated,indent=2)+'\n',encoding='utf-8')
                    st.success('已保存人工檢查；沒有建立不存在的 claim。')
        st.stop()
    claim_id = st.selectbox('原文主張', [c['claim_id'] for c in record['claims']])
    claim = next(c for c in record['claims'] if c['claim_id'] == claim_id)
    st.subheader('Atomic claim candidate'); st.text(claim['claim_text'])
    st.caption(f'來源位置：answer[{claim["answer_start"]}:{claim["answer_end"]}]；引用綁定：{claim["citation_binding"]}')
    if claim.get('context_heading'):
        st.write('回答原文 heading：', claim['context_heading'])
    if claim['warnings']:
        st.warning('可能含多個主張或需要表頭資訊；請在 notes 記錄。')
    contexts = {c['context_id']:c for c in record['contexts']}
    st.subheader('Cited evidence')
    for cid in claim['audit_citation_set']:
        context = contexts.get(cid)
        if context is None:
            st.error(f'{cid} 不存在於本題 context'); continue
        with st.expander(f'{cid} | document {context["document_id"]} | page {context["page"]}', expanded=True):
            st.caption(f'chunk: {context["chunk_id"]} | checksum: {context["content_checksum"]}')
            st.text(context['text'])
    if not claim['audit_citation_set']:
        st.warning('此主張沒有宣告引用。')
    with st.form('human_support_review'):
        citation_judgments={}
        for cid in claim['audit_citation_set']:
            citation_judgments[cid]=st.selectbox(f'{cid} 對此主張的支持程度',
                ['entailed','partially_entailed','not_entailed','cannot_determine'],index=None)
        verdict = st.radio('整個主張的人工判定', ['entailed','partially_entailed','not_entailed','cannot_determine'], index=None)
        notes = st.text_area('Notes：請記錄支持文字、不支持部分、綁定或 atomicity 問題')
        confirmed = st.checkbox('我已閱讀 claim 與引用原文，這是我的人工判定')
        if st.form_submit_button('保存人工覆核'):
            if not reviewer.strip() or verdict is None or not confirmed or any(v is None for v in citation_judgments.values()):
                st.error('請填 reviewer、選擇判定並確認閱讀。')
            else:
                event = human_review_event(record, claim_id, reviewer, verdict, notes,
                    datetime.now(timezone.utc).isoformat(),citation_judgments)
                append_jsonl(path, event)
                updated = human_progress(records, events + [event])
                (OUT / 'human_audit_progress.json').write_text(json.dumps(updated,indent=2)+'\n',encoding='utf-8')
                st.success('已保存人工覆核；不會修改回答、evidence 或 AI 判定。')


if __name__ == '__main__':
    main()
