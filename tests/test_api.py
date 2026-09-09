import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from casehunter.webapp import create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "api.db"
        self.client_context = TestClient(create_app(self.db))
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_frontend_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Case Hunter Resolve", response.text)

    def test_company_crud(self):
        created = self.client.post("/api/companies", json={"name":"Empresa Uno", "rut":"76.000.001-1"})
        self.assertEqual(created.status_code, 201)
        rows = self.client.get("/api/companies").json()
        self.assertEqual(rows[0]["name"], "Empresa Uno")

    def test_invalid_company_rejected(self):
        response = self.client.post("/api/companies", json={"name":"A"})
        self.assertEqual(response.status_code, 422)

    @patch("casehunter.scanner_service.scan_ley_lobby_listing")
    def test_scan_endpoint_imports_case(self, mocked):
        mocked.return_value = {
            "source":"LEY_DEL_LOBBY", "source_url":"https://www.leylobby.gob.cl/list", "pages_scanned":1,
            "candidate_count":1, "enrichment_errors":[],
            "candidates":[{
                "audience_id":"AM002AW2052621", "date":"2026-01-21", "detail_url":"https://www.leylobby.gob.cl/detail",
                "source_url":"https://www.leylobby.gob.cl/list", "safis":["319892"], "amounts_clp":[100000000],
                "problems":[{"type":"LIQUIDATION_PENDING","matched_patterns":["liquidacion del contrato"]}],
                "confidence":{"score":1.0,"label":"HIGH"}, "represented_entities":["EMPRESA DEMO SPA"], "works_for":[],
                "raw_text":"SAFI 319.892 liquidacion del contrato $100.000.000"
            }]
        }
        response = self.client.post("/api/scans/ley-lobby", json={"url":"https://www.leylobby.gob.cl/list", "max_pages":1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["import"]["created"], 1)
        cases = self.client.get("/api/cases").json()
        self.assertEqual(len(cases), 1)


    @patch("casehunter.scanner_service.scan_ley_lobby_listing")
    def test_confirm_blocker_switches_resolution_playbook(self, mocked):
        mocked.return_value = {
            "source":"LEY_DEL_LOBBY", "source_url":"https://www.leylobby.gob.cl/list", "pages_scanned":1,
            "candidate_count":1, "enrichment_errors":[],
            "candidates":[{
                "audience_id":"ICH-DEMO-1", "date":"2026-01-21", "detail_url":"https://www.leylobby.gob.cl/detail",
                "source_url":"https://www.leylobby.gob.cl/list", "safis":["385256"], "amounts_clp":[42000000],
                "problems":[{"type":"LIQUIDATION_PENDING","matched_patterns":["liquidacion pendiente"]}],
                "confidence":{"score":1.0,"label":"HIGH"}, "represented_entities":["ICH INGENIERIA"], "works_for":[],
                "raw_text":"SAFI 385256 liquidacion pendiente $42.000.000"
            }]
        }
        self.client.post("/api/scans/ley-lobby", json={"url":"https://www.leylobby.gob.cl/list", "max_pages":1})
        case_id = self.client.get("/api/cases").json()[0]["id"]
        response = self.client.patch(
            f"/api/cases/{case_id}/blocker",
            json={"blocker":"DOCUMENT_MISSING", "reason":"Ricardo confirma antecedentes faltantes"},
        )
        self.assertEqual(response.status_code, 200)
        case = response.json()
        self.assertEqual(case["current_blocker"], "DOCUMENT_MISSING")
        self.assertEqual(case["playbook"]["blocker"], "DOCUMENT_MISSING")
        self.assertTrue(any(a["action_type"] == "SUBMIT_MISSING_DOCUMENT" for a in case["actions"]))
        self.assertTrue(any(e["event_type"] == "BLOCKER_CONFIRMED" for e in case["timeline"]))

    def test_playbook_catalog_endpoint(self):
        response = self.client.get("/api/playbooks")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(row["blocker"] == "DOCUMENT_MISSING" for row in response.json()))

    def test_missing_case_is_404(self):
        response = self.client.get("/api/cases/999")
        self.assertEqual(response.status_code, 404)

    def test_optional_basic_auth(self):
        import base64
        with tempfile.TemporaryDirectory() as td:
            client_context = TestClient(create_app(Path(td) / "auth.db", auth_username="admin", auth_password="secret"))
            client = client_context.__enter__()
            try:
                self.assertEqual(client.get("/api/health").status_code, 401)
                token = base64.b64encode(b"admin:secret").decode()
                response = client.get("/api/health", headers={"Authorization": f"Basic {token}"})
                self.assertEqual(response.status_code, 200)
            finally:
                client_context.__exit__(None, None, None)


if __name__ == "__main__": unittest.main()
