import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from casehunter.client_auth import create_client_user
from casehunter.database import transaction
from casehunter.repository import create_company, import_candidate, link_case_company
from casehunter.webapp import create_app


def candidate(audience_id, company, agency, amount):
    return {
        "audience_id": audience_id,
        "date": "2026-09-01",
        "detail_url": f"https://www.leylobby.gob.cl/{audience_id}",
        "source_url": "https://www.leylobby.gob.cl/",
        "safis": [],
        "amounts_clp": [amount],
        "problems": [{"type": "LIQUIDATION_PENDING", "matched_patterns": ["pago pendiente"]}],
        "confidence": {"score": 1.0, "label": "HIGH"},
        "represented_entities": [company],
        "works_for": [],
        "agency": agency,
        "contract_ref": f"Contrato {audience_id}",
        "raw_text": f"{company} mantiene pago pendiente con {agency}",
        "detail_text": f"Antecedente público de {company} ante {agency}",
    }


class ClientPortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "portal.db"
        self.app = create_app(self.db, auth_username="admin", auth_password="admin-secret")
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

        self.company_a = create_company("Empresa Alpha SpA", "76.100.000-1", self.db)
        self.company_b = create_company("Empresa Beta SpA", "76.200.000-2", self.db)

        case_a = import_candidate(candidate("ALPHA-1", "Empresa Alpha SpA", "Municipalidad Alpha", 5_000_000), db_path=self.db)["case"]
        case_b = import_candidate(candidate("BETA-1", "Empresa Beta SpA", "Hospital Beta", 9_000_000), db_path=self.db)["case"]
        self.case_a = link_case_company(case_a["id"], self.company_a["id"], self.db)
        self.case_b = link_case_company(case_b["id"], self.company_b["id"], self.db)

        self.user_a = create_client_user(self.company_a["id"], "alpha@example.com", "Alpha-Password-2026!", db_path=self.db)
        self.user_b = create_client_user(self.company_b["id"], "beta@example.com", "Beta-Password-2026!!", db_path=self.db)

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_client_portal_is_public_but_portfolio_requires_session(self):
        page = self.client.get("/client")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Portal de cartera", page.text)

        response = self.client.get("/api/client/portfolio")
        self.assertEqual(response.status_code, 401)

    def test_login_scopes_portfolio_to_authenticated_company(self):
        bad = self.client.post("/api/client/login", json={"email":"alpha@example.com", "password":"wrong"})
        self.assertEqual(bad.status_code, 401)

        login = self.client.post(
            "/api/client/login",
            json={"email":"alpha@example.com", "password":"Alpha-Password-2026!"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("HttpOnly", login.headers.get("set-cookie", ""))

        portfolio = self.client.get("/api/client/portfolio")
        self.assertEqual(portfolio.status_code, 200)
        body = portfolio.json()
        self.assertEqual(body["company"]["id"], self.company_a["id"])
        self.assertEqual(body["company"]["name"], "Empresa Alpha SpA")
        self.assertEqual(len(body["cases"]), 1)
        self.assertEqual(body["cases"][0]["agency"], "Municipalidad Alpha")
        self.assertNotIn("Hospital Beta", portfolio.text)
        self.assertNotIn("Empresa Beta", portfolio.text)

    def test_client_session_does_not_unlock_internal_case_api(self):
        self.client.post(
            "/api/client/login",
            json={"email":"alpha@example.com", "password":"Alpha-Password-2026!"},
        )
        internal = self.client.get(f"/api/cases/{self.case_b['id']}")
        self.assertEqual(internal.status_code, 401)

        internal_admin = self.client.get(
            f"/api/cases/{self.case_b['id']}",
            auth=("admin", "admin-secret"),
        )
        self.assertEqual(internal_admin.status_code, 200)

    def test_session_token_is_not_stored_in_plain_text(self):
        self.client.post(
            "/api/client/login",
            json={"email":"alpha@example.com", "password":"Alpha-Password-2026!"},
        )
        token = self.client.cookies.get("case_hunter_client_session")
        self.assertTrue(token)
        with transaction(self.db) as conn:
            row = conn.execute("SELECT token_hash FROM client_sessions ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["token_hash"], token)
        self.assertEqual(len(row["token_hash"]), 64)

    def test_admin_can_disable_account_and_revoke_existing_session(self):
        self.client.post(
            "/api/client/login",
            json={"email":"alpha@example.com", "password":"Alpha-Password-2026!"},
        )
        self.assertEqual(self.client.get("/api/client/portfolio").status_code, 200)

        disabled = self.client.patch(
            f"/api/admin/client-users/{self.user_a['id']}/status",
            auth=("admin", "admin-secret"),
            json={"status":"DISABLED"},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(disabled.json()["status"], "DISABLED")
        self.assertEqual(self.client.get("/api/client/portfolio").status_code, 401)

    def test_admin_account_management_requires_basic_auth(self):
        denied = self.client.get("/api/admin/client-users")
        self.assertEqual(denied.status_code, 401)
        allowed = self.client.get("/api/admin/client-users", auth=("admin", "admin-secret"))
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(len(allowed.json()), 2)


class ClientPortalFailClosedTests(unittest.TestCase):
    def test_internal_console_fails_closed_without_admin_auth_when_client_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "locked.db"
            app = create_app(db, auth_username="", auth_password="")
            with TestClient(app) as client:
                company = create_company("Empresa Protegida", "76.300.000-3", db)
                create_client_user(company["id"], "secure@example.com", "Secure-Password-2026!", db_path=db)
                internal = client.get("/api/companies")
                self.assertEqual(internal.status_code, 503)
                self.assertEqual(client.get("/client").status_code, 200)


if __name__ == "__main__":
    unittest.main()
