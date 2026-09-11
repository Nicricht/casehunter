import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from casehunter.repository import import_candidate, update_case_status
from casehunter.webapp import create_app


def candidate(aid, amount):
    return {
        "audience_id": aid,
        "date": "2026-09-11",
        "detail_url": f"https://example.test/{aid}",
        "source_url": "https://example.test",
        "amounts_clp": [amount],
        "problems": [{"type": "PAYMENT_PENDING", "matched_patterns": ["factura pendiente"]}],
        "confidence": {"score": 0.95, "label": "HIGH"},
        "represented_entities": ["Empresa Cartera SpA"],
        "works_for": [],
        "agency": "Municipalidad Demo",
        "contract_ref": aid,
        "raw_text": "factura pendiente",
        "detail_text": "factura pendiente",
    }


class PortfolioApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "api.db"
        self.client_context = TestClient(create_app(self.db))
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_portfolios_endpoint_groups_recurring_company(self):
        first = import_candidate(candidate("API-PORT-1", 1000000), db_path=self.db)["case"]
        second = import_candidate(candidate("API-PORT-2", 2000000), db_path=self.db)["case"]
        update_case_status(first["id"], "BLOCKER_IDENTIFIED", self.db)
        update_case_status(second["id"], "FOLLOW_UP", self.db)

        response = self.client.get("/api/portfolios")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["company_name"], "Empresa Cartera SpA")
        self.assertEqual(payload[0]["case_count"], 2)
        self.assertEqual(payload[0]["confirmed_public_amount_clp"], 3000000)
        self.assertIsNotNone(payload[0]["priority_case"]["next_action"])

    def test_portfolios_endpoint_validates_min_cases(self):
        response = self.client.get("/api/portfolios?min_cases=0")
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
