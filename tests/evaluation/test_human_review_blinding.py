import copy
import json
import unittest
from pathlib import Path
from src.evaluation.human_support.core import blind_view, validate_record
from src.evaluation.human_support.workflow import load_blind, second_reviewer_subset, PHASE18
from src.evaluation.human_support.history import read_jsonl
from tests.evaluation.human_support_fixtures import record


class BlindingTest(unittest.TestCase):
    def test_allowlist_removes_private_fields_at_all_levels(self):
        r=record();r['generator']='PRIVATE_MODEL';r['AI_label']='entailed';r['primary_metrics']={'score':.9}
        r['claims'][0]['judge_score']=.8;r['contexts'][0]['model_digest']='PRIVATE_DIGEST'
        output=json.dumps(blind_view(r))
        for v in ('PRIVATE_MODEL','AI_label','primary_metrics','judge_score','PRIVATE_DIGEST'):
            self.assertNotIn(v,output)

    def test_real_frozen_sample_not_resampled(self):
        rows,manifest=load_blind()
        self.assertEqual(len(rows),48)
        self.assertEqual(sum(len(r['claims']) for r in rows),122)
        self.assertEqual(sum(len(c['audit_citation_set']) for r in rows for c in r['claims']),310)
        self.assertTrue(all(validate_record(r) for r in rows))
        self.assertEqual(manifest['frozen_counts']['primary_claims'],122)

    def test_ui_does_not_read_private_or_ai_results(self):
        text=Path('tools/human_claim_citation_review_app.py').read_text(encoding='utf-8')
        for name in ('claim_citation_ai_audit','claim_citation_sample','primary_metrics','reference_answer'):
            self.assertNotIn(name,text)
        self.assertIn('index=None',text)

    def test_optional_second_subset_fixed_without_labels(self):
        rows,m=load_blind();private=read_jsonl(PHASE18/'claim_citation_sample.jsonl')
        a=second_reviewer_subset(rows,private)
        other=copy.deepcopy(private)
        for r in other:r['primary_metrics']={'unrelated':1}
        self.assertEqual(a,second_reviewer_subset(rows,other))
        self.assertEqual([r['claim_id'] for r in a],m['second_reviewer_claim_ids'])
        self.assertEqual(len(a),36)
