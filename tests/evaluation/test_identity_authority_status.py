import unittest

from src.evaluation.corpus_gaps import identity_authority_status


class IdentityAuthorityStatusTests(unittest.TestCase):
    def test_title_identity_does_not_verify_official_authority(self):
        self.assertEqual(identity_authority_status(identity_basis="exact_title", source_verified=False, source_tier=1), ("likely", "unverified"))

    def test_official_authority_requires_existing_verified_flag(self):
        self.assertEqual(identity_authority_status(identity_basis="exact_url", source_verified=True, source_tier=1), ("verified", "verified_official"))
        self.assertEqual(identity_authority_status(identity_basis="exact_url", source_verified=False, source_tier=1), ("verified", "unverified"))

    def test_legal_status_is_not_promoted(self):
        self.assertEqual(identity_authority_status(identity_basis="known_duplicate", source_verified=False, legal_status="unknown", source_tier=1), ("verified", "unverified"))
        self.assertEqual(identity_authority_status(identity_basis="strong_title", source_verified=None, legal_status="superseded"), ("likely", "superseded"))


if __name__ == "__main__":
    unittest.main()
