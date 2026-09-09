import unittest

from casehunter.blocker_engine import diagnose
from casehunter.financial import calculate_priority, summarize_amounts


class DomainTests(unittest.TestCase):
    def test_missing_document_is_primary(self):
        result = diagnose(["RETENTION_PENDING", "DOCUMENT_MISSING"])
        self.assertEqual(result["primary_blocker"], "DOCUMENT_MISSING")
        self.assertTrue(any(d["code"] == "SUPPORTING_DOCUMENTS" for d in result["documents"]))

    def test_liquidation_generates_actions(self):
        result = diagnose(["LIQUIDATION_PENDING"])
        self.assertEqual(result["primary_blocker"], "LIQUIDATION_PENDING")
        self.assertGreaterEqual(len(result["actions"]), 3)

    def test_contract_modification_blocker(self):
        result = diagnose(["CONTRACT_MODIFICATION_PENDING"])
        self.assertEqual(result["primary_blocker"], "CONTRACT_MODIFICATION_PENDING")

    def test_unknown_fallback(self):
        result = diagnose([])
        self.assertEqual(result["primary_blocker"], "UNKNOWN_BLOCKER")

    def test_priority_high_value(self):
        score = calculate_priority([1_500_000_000], ["PAYMENT_PENDING", "RETENTION_PENDING"], "HIGH")
        self.assertGreaterEqual(score, 80)

    def test_priority_is_capped(self):
        score = calculate_priority([5_000_000_000], list(range(100)), "HIGH")
        self.assertLessEqual(score, 100)

    def test_financial_summary_deduplicates(self):
        data = summarize_amounts([100, 100, 50])
        self.assertEqual(data["observed_amounts_clp"], [100, 50])
        self.assertEqual(data["sum_observed_amounts_clp"], 150)


if __name__ == "__main__": unittest.main()
