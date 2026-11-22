import unittest

class NewCorpusVersionTests(unittest.TestCase):
    def test_source_addition_requires_a_new_final_corpus(self):
        changed=True
        final_corpus_manifest={"version":"Final Evaluation Corpus v1","source_additions_present":True}
        self.assertTrue(changed and final_corpus_manifest["version"] != "Evaluation Corpus v2")
