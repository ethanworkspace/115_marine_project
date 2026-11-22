"""Phase 18.1 human-only blind UI. Never reads model identity or AI judgments."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.human_support.core import SUPPORT, ELSEWHERE, ATOMICITY, PROVENANCE, pairs_for, latest_events
from src.evaluation.human_support.history import ReviewStore, primary_state
from src.evaluation.human_support.workflow import OUT, load_blind


def show_context(c):
    st.caption(f'context {c["context_id"]} | chunk {c["chunk_id"]} | document {c["document_id"]} | page {c["page"]}')
    st.caption('文字 SHA-256：'+c['content_checksum'])
    st.text(c['text'])


def main():
    st.set_page_config(page_title='盲化 Claim-Citation 人工覆核', layout='wide')
    st.title('盲化 Claim-Citation 人工覆核')
    st.caption('請只依凍結的回答與本題 Evidence 判定。未受提供的 Evidence 支持，不代表現實世界事實錯誤。')
    try:
        records, manifest = load_blind()
        store = ReviewStore(OUT, records, manifest['second_reviewer_claim_ids'])
        state = store.read()
    except (OSError, ValueError, KeyError) as exc:
        st.error('凍結資料或 review history 驗證失敗：'+str(exc));st.stop()
    progress, _, _ = primary_state(records, state)
    a,b,c = st.columns(3)
    a.metric('完整覆核回答', f'{progress["outputs_reviewed"]} / 48')
    b.metric('Primary claims', f'{progress["claims_reviewed"]} / 122')
    c.metric('Claim-citation pairs', f'{progress["pairs_reviewed"]} / 310')
    st.info('所有判定需由人員明確選擇。本輪尚未進行人工 review；瀏覽不會產生 human labels。')
    with st.sidebar:
        st.subheader('Reviewer 登記')
        with st.form('register_human'):
            rid = st.text_input('Reviewer ID')
            role = st.text_input('Reviewer role（如研究生／研究員／養殖專業人員）')
            assignment = st.selectbox('覆核任務', ['primary','second'])
            confirm = st.checkbox('我是實際覆核者，這是我的識別碼與角色')
            if st.form_submit_button('登記 reviewer'):
                try:
                    store.register(rid, role, assignment, confirm)
                    st.success('已登記；沒有產生任何支持判定。');st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        reviewers = store.reviewers()
        selected_reviewer = st.selectbox('本次覆核者', [r['reviewer_id'] for r in reviewers], index=None)
        st.caption('第二位 reviewer 使用預先固定的 36 claims；看不到第一位的判定。')
    reviewer = next((r for r in reviewers if r['reviewer_id']==selected_reviewer), None)
    own_claims = {k[1]:v for k,v in latest_events(state['claims'], 'claim_id').items() if k[0]==selected_reviewer}
    queue = st.selectbox('佇列', ['全部','本人尚未覆核','本人已覆核'])
    pool = records
    if reviewer and reviewer['assignment']=='second':
        pool = [r for r in pool if any(c['claim_id'] in store.second_claims for c in r['claims'])]
    if queue != '全部':
        done = queue == '本人已覆核'
        pool = [r for r in pool if any((c['claim_id'] in own_claims)==done for c in r['claims'])
                or (not r['claims'] and not done)]
    if not pool:
        st.info('此佇列目前沒有回答。');st.stop()
    selected = st.selectbox('回答識別碼', [r['answer_id'] for r in pool])
    record = next(r for r in pool if r['answer_id']==selected)
    st.caption('Question ID：'+record['question_id']+' | answer SHA-256：'+record['answer_sha256'])
    st.subheader('Question');st.text(record['question'])
    st.subheader('Frozen answer');st.text(record['answer'])
    st.write('Answer-level citation IDs：', record['citations'])
    if not record['claims']:
        st.warning('本回答沒有 frozen primary claim。只能保存閱讀紀錄；不得新增或重新抽取 claim。')
        with st.expander('本題全部 provided context'):
            for context in record['contexts']:
                show_context(context)
        with st.form('no_claim_inspection'):
            notes = st.text_area('無 frozen claim 的回答：人工閱讀 notes')
            checked = st.checkbox('我已閱讀回答及 context；這不代表 claim support 驗證')
            if st.form_submit_button('保存閱讀紀錄', disabled=reviewer is None):
                try:
                    store.submit_no_claim_output(record['answer_id'], selected_reviewer, notes, checked)
                    st.success('已保存 append-only 閱讀紀錄。');st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        return
    candidates = record['claims']
    if reviewer and reviewer['assignment']=='second':
        candidates = [c for c in candidates if c['claim_id'] in store.second_claims]
    cid = st.selectbox('Frozen claim', [c['claim_id'] for c in candidates])
    claim = next(c for c in candidates if c['claim_id']==cid)
    st.subheader('原文 Claim');st.text(claim['claim_text'])
    st.caption(f'位置 answer[{claim["answer_start"]}:{claim["answer_end"]}] | SHA-256 {claim["claim_text_sha256"]}')
    st.caption('Citation binding：'+claim['citation_binding'])
    if claim.get('context_heading'):
        st.text('原文 heading：'+claim['context_heading'])
    if claim['citation_binding']=='answer_level_only':
        st.warning('目前只有 answer-level citation set；這不是已證明的 claim-level binding，請人工檢查。')
    contexts = {c['context_id']:c for c in record['contexts']}
    frozen_pairs = pairs_for(record, claim)
    for p in frozen_pairs:
        with st.expander(f'引用 {p["context_id"]}（第 {p["citation_ordinal"]} 筆）', expanded=True):
            if p['context_id'] in contexts:
                show_context(contexts[p['context_id']])
            else:
                st.warning('此 citation ID 不存在於本題提供的 context，沒有可顯示的 chunk provenance。')
    with st.expander('其他 provided context（只可使用本題凍結內容）', expanded=True):
        for context in record['contexts']:
            if context['context_id'] not in claim['audit_citation_set']:
                show_context(context)
    if cid in own_claims:
        with st.expander('本人上次提交（不會預填此次判定）'):
            st.json(own_claims[cid]['new_value'])
        st.caption('再次提交會新增 revision，保留前次值。')
    with st.form('claim_support_form_'+cid):
        decisions = []
        for p in frozen_pairs:
            st.subheader('Citation '+str(p['citation_ordinal'])+'：'+p['context_id'])
            support = st.selectbox('此 cited chunk 支持程度', SUPPORT, index=None, key=p['pair_id']+'_support')
            provenance = st.selectbox('顯示的 context/chunk/document/page provenance 是否一致', PROVENANCE,
                                      index=None, key=p['pair_id']+'_provenance')
            elsewhere = st.selectbox('除了這筆 cited chunk，其他 provided context 的支持情形', ELSEWHERE,
                                     index=None, key=p['pair_id']+'_elsewhere')
            alternative = st.multiselect('若其他 context 支持，請選其 IDs',
                [x for x in contexts if x!=p['context_id']], key=p['pair_id']+'_alternatives')
            notes = st.text_area('此 citation 的 notes', key=p['pair_id']+'_notes')
            decisions.append(dict(pair_id=p['pair_id'], support=support, provenance=provenance,
                                  elsewhere_support=elsewhere, elsewhere_context_ids=alternative, notes=notes))
        st.subheader('Claim 整體判定')
        st.caption('整個 cited set 可共同支持 claim；不要只因其中一筆 partial 就推論整體 fully supported。')
        set_support = st.selectbox('全部 cited chunks 合併後支持程度', SUPPORT, index=None)
        elsewhere = st.selectbox('cited set 之外的其他 provided context 支持情形', ELSEWHERE, index=None)
        alternatives = st.multiselect('支持這個 claim 的其他 context IDs',
            [x for x in contexts if x not in claim['audit_citation_set']])
        atomicity = st.selectbox('Claim atomicity', ATOMICITY, index=None)
        notes = st.text_area('整體 notes：支持原文、缺少條件、atomicity 問題等')
        confirm = st.checkbox('我已閱讀回答、claim、引用及其他 context，以上是我的人工判定')
        if st.form_submit_button('保存人工覆核（append-only）', disabled=reviewer is None):
            submission = dict(atomicity=atomicity, cited_set_support=set_support, elsewhere_support=elsewhere,
                              elsewhere_context_ids=alternatives, notes=notes, citations=decisions, human_confirmed=confirm)
            try:
                tx = store.submit(record['answer_id'], cid, selected_reviewer, submission)
                st.success('已保存 transaction '+tx['transaction_id']+'；舊判定與 AI audit 保持不變。');st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.caption('報告由獨立 reporting tool 更新；此介面不讀模型身分或 AI 判定。')


if __name__=='__main__':
    main()
