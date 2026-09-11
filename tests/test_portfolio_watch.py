import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db
from casehunter.portfolio_watch import list_portfolios
from casehunter.repository import import_candidate, update_case_status


def candidate(aid, amount, agency="Municipalidad"):
    return {
        "audience_id": aid,
        "date": "2026-09-11",
        "detail_url": f"https://example.test/{aid}",
        "source_url": "https://example.test",
        "amounts_clp": [amount],
        "problems": [{"type": "PAYMENT_PENDING", "matched_patterns": ["factura pendiente"]}],
        "confidence": {"score": 0.95, "label": "HIGH"},
        "represented_entities": ["Empresa Recurrente SpA"],
        "works_for": [],
        "agency": agency,
        "contract_ref": aid,
        "raw_text": "factura pendiente de pago",
        "detail_text": "factura pendiente de pago",
    }


class PortfolioWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_groups_recurring_company_cases(self):
        first = import_candidate(candidate("PORT-1", 1000000), db_path=self.db)["case"]
        second = import_candidate(candidate("PORT-2", 2000000), db_path=self.db)["case"]
        update_case_status(first["id"], "BLOCKER_IDENTIFIED", self.db)
        update_case_status(second["id"], "FOLLOW_UP", self.db)

        result = list_portfolios(db_path=self.db)
        self.assertEqual(len(result), 1)
        portfolio = result[0]
        self.assertEqual(portfolio["company_name"], "Empresa Recurrente SpA")
        self.assertEqual(portfolio["case_count"], 2)
        self.assertEqual(portfolio["open_case_count"], 2)
        self.assertEqual(portfolio["confirmed_public_amount_clp"], 3000000)
        self.assertIsNotNone(portfolio["priority_case"]["next_action"])

    def test_min_cases_filters_single_case_company(self):
        case = import_candidate(candidate("PORT-3", 500000), db_path=self.db)["case"]
        update_case_status(case["id"], "FOLLOW_UP", self.db)
        self.assertEqual(list_portfolios(db_path=self.db), [])
        self.assertEqual(len(list_portfolios(min_cases=1, db_path=self.db)), 1)


if __name__ == "__main__":
    unittest.main()
