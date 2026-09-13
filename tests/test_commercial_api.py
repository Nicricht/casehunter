import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from casehunter.repository import import_candidate
from casehunter.webapp import create_app


def candidate():
    return {
        "audience_id": "COMM-API-1",
        "date": "2026-09-13",
        "detail_url": "https://www.leylobby.gob.cl/detail",
        "source_url": "https://www.leylobby.gob.cl/list",
        "safis": [],
        "amounts_clp": [50000000],
        "problems": [{"type": "PAYMENT_PENDING", "matched_patterns": ["pago pendiente"]}],
        "confidence": {"score": 0.95, "label": "HIGH"},
        "represented_entities": ["Empresa Comercial API SpA"],
        "works_for": [],
        "agency": "Organismo Público",
        "contract_ref": "Contrato API",
        "raw_text": "pago pendiente",
        "detail_text": "pago pendiente",
    }


class CommercialApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "commercial-api.db"
        self.context = TestClient(create_app(self.db))
        self.client = self.context.__enter__()
        self.case_id = import_candidate(candidate(), db_path=self.db)["case"]["id"]

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_get_and_patch_commercial_state(self):
        current = self.client.get(f"/api/cases/{self.case_id}/commercial")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["status"], "OPEN")

        proposed = self.client.patch(
            f"/api/cases/{self.case_id}/commercial",
            json={
                "status": "PILOT_PROPOSED",
                "pilot_price_clp": 0,
                "monthly_price_clp": 149000,
                "expected_value_clp": 600000,
                "note": "Propuesta enviada",
            },
        )
        self.assertEqual(proposed.status_code, 200)
        self.assertEqual(proposed.json()["status"], "PILOT_PROPOSED")
        self.assertEqual(proposed.json()["expected_value_clp"], 600000)

        active = self.client.patch(
            f"/api/cases/{self.case_id}/commercial",
            json={"status": "PILOT_ACTIVE", "note": "Piloto aceptado"},
        )
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["status"], "PILOT_ACTIVE")

    def test_lost_requires_reason(self):
        response = self.client.patch(
            f"/api/cases/{self.case_id}/commercial",
            json={"status": "LOST"},
        )
        self.assertEqual(response.status_code, 400)

    def test_metrics_and_pilot_proposal_endpoints(self):
        metrics = self.client.get("/api/commercial/metrics")
        self.assertEqual(metrics.status_code, 200)
        self.assertIn("pilots_active", metrics.json())
        self.assertIn("delivery_rate", metrics.json())

        proposal = self.client.get(
            f"/api/cases/{self.case_id}/pilot-proposal?cases_limit=5&pilot_days=30"
        )
        self.assertEqual(proposal.status_code, 200)
        payload = proposal.json()
        self.assertEqual(payload["cases_limit"], 5)
        self.assertEqual(payload["pilot_days"], 30)
        self.assertIn("Empresa Comercial API SpA", payload["title"])

    def test_missing_case_is_404(self):
        self.assertEqual(self.client.get("/api/cases/999/commercial").status_code, 404)
        self.assertEqual(self.client.get("/api/cases/999/pilot-proposal").status_code, 404)


if __name__ == "__main__":
    unittest.main()
