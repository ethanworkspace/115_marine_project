import json
import unittest
from src.evaluation.validity.core import blind_record,extract_claims,judge_payload,human_review_event,human_no_assertion_event
from src.evaluation.validity.report import human_progress
from tests.evaluation.phase18_fixtures import row


class BlindTest(unittest.TestCase):
    def record(self):
        r=row();return blind_record(r,extract_claims(r))

    def test_generator_and_score_absent(self):
        r=self.record();payload=judge_payload(r,r['claims'][0])
        for text in (json.dumps(r),json.dumps(payload)):
            self.assertNotIn('gemma2:9b',text);self.assertNotIn('metrics',text)
            self.assertNotIn('reference_answer',text)

    def test_manual_review_required(self):
        r=self.record()
        with self.assertRaises(ValueError):human_review_event(r,r['claims'][0]['claim_id'],'','entailed','','now')

    def test_ai_event_never_human(self):
        r=self.record();e=human_review_event(r,r['claims'][0]['claim_id'],'human','entailed','','now')
        e['review_source']='ai'
        self.assertEqual(human_progress([r],[e])['human_reviewed_claims'],0)

    def test_valid_human_event(self):
        r=self.record();e=human_review_event(r,r['claims'][0]['claim_id'],'human','entailed','','now')
        self.assertEqual(human_progress([r],[e])['human_completed_outputs'],1)

    def test_pair_judgments_must_cover_citations(self):
        r=self.record()
        with self.assertRaises(ValueError):
            human_review_event(r,r['claims'][0]['claim_id'],'human','entailed','','now',{})

    def test_no_assertion_output_needs_explicit_human_review(self):
        r=row(answer='管理項目如下：');record=blind_record(r,extract_claims(r))
        self.assertEqual(human_progress([record],[])['human_completed_outputs'],0)
        e=human_no_assertion_event(record,'human','needs source-span review','now')
        self.assertEqual(human_progress([record],[e])['human_completed_outputs'],1)
        self.assertFalse(e['claim_support_verified'])
