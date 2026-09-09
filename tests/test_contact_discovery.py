import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from casehunter.auto_service import run_auto_cycle
from casehunter.contact_discovery import (
    contact_assessment,
    extract_emails,
    is_verified_corporate_contact,
    quarantine_unsafe_contacts,
    search_company_websites,
)
from casehunter.database import init_db, transaction, utc_now
from casehunter.outreach import ensure_outreach_draft, list_outreach
from casehunter.repository import import_candidate


def candidate(aid="CONTACT-SAFETY-1"):
    return {
        "audience_id": aid,
        "date": "2026-09-09",
        "detail_url": "https://example.test/case",
        "source_url": "https://example.test",
        "safis": ["999"],
        "amounts_clp": [150000000],
        "problems": [{"type": "RETENTION_PENDING", "matched_patterns": ["retenciones"]}],
        "confidence": {"score": 0.95, "label": "HIGH"},
        "represented_entities": ["Empresa Segura SpA"],
        "works_for": [],
        "agency": "MOP",
        "contract_ref": "SAFI 999",
        "raw_text": "retenciones",
        "detail_text": "retenciones",
    }


class ContactDiscoverySafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_duckduckgo_email_is_rejected(self):
        emails = extract_emails("Contacto real contacto@empresa.cl y soporte dmca@duckduckgo.com")
        self.assertEqual(emails, ["contacto@empresa.cl"])

    def test_verified_corporate_contact_accepts_matching_company_site(self):
        self.assertTrue(
            is_verified_corporate_contact(
                "contacto@valko.cl",
                "https://www.valko.cl/contacto",
                "HIGH",
                "Constructora Valko S.A.",
            )
        )
        self.assertFalse(
            is_verified_corporate_contact(
                "contacto@otraempresa.cl",
                "https://www.otraempresa.cl/contacto",
                "HIGH",
                "Constructora Valko S.A.",
            )
        )

    def test_external_gmail_can_be_verified_when_company_publishes_it(self):
        assessment = contact_assessment(
            "prevcons@gmail.com",
            "https://prevcons.cl/contacto",
            "MEDIUM",
            "PREVCONS SpA",
        )
        self.assertIsNotNone(assessment)
        self.assertGreaterEqual(assessment.score, 70)
        self.assertEqual(assessment.decision, "AUTO_SEND")
        self.assertTrue(
            is_verified_corporate_contact(
                "prevcons@gmail.com",
                "https://prevcons.cl/contacto",
                "MEDIUM",
                "PREVCONS SpA",
            )
        )

    def test_external_email_from_unrelated_site_is_not_verified(self):
        self.assertFalse(
            is_verified_corporate_contact(
                "prevcons@gmail.com",
                "https://directorio-random.example/contacto",
                "HIGH",
                "PREVCONS SpA",
            )
        )

    @patch("casehunter.contact_discovery._fetch_text")
    def test_search_results_do_not_return_duckduckgo_as_company_site(self, mocked):
        mocked.return_value = """
        <a href="https://duckduckgo.com/about">DuckDuckGo</a>
        <a href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fempresa.cl%2Fcontacto">Empresa</a>
        """
        sites = search_company_websites("Empresa Segura SpA", max_results=3)
        self.assertEqual(sites, ["https://empresa.cl/"])

    def test_quarantine_rejects_stale_search_engine_recipient(self):
        case_id = import_candidate(candidate(), db_path=self.db)["case"]["id"]
        now = utc_now()
        with transaction(self.db) as conn:
            cur = conn.execute(
                """INSERT INTO contacts(case_id,company_name,email,source_url,confidence_label,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,'DISCOVERED',?,?)""",
                (case_id, "Empresa Segura SpA", "dmca@duckduckgo.com", "https://duckduckgo.com/", "HIGH", now, now),
            )
            contact_id = cur.lastrowid
        message = ensure_outreach_draft(case_id, "dmca@duckduckgo.com", contact_id, self.db)["message"]
        self.assertEqual(message["status"], "READY_FOR_APPROVAL")

        result = quarantine_unsafe_contacts(self.db)
        self.assertEqual(result["contacts_rejected"], 1)
        self.assertEqual(result["messages_rejected"], 1)
        queue = list_outreach(db_path=self.db)
        self.assertEqual(queue[0]["status"], "REJECTED")

    def test_quarantine_rejects_contact_from_blocked_source_even_if_email_domain_is_external(self):
        case_id = import_candidate(candidate("CONTACT-SAFETY-SOURCE"), db_path=self.db)["case"]["id"]
        now = utc_now()
        with transaction(self.db) as conn:
            conn.execute(
                """INSERT INTO contacts(case_id,company_name,email,source_url,confidence_label,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,'DISCOVERED',?,?)""",
                (case_id, "Empresa Segura SpA", "eurep@itgovernance.eu", "https://duckduckgo.com/contact", "MEDIUM", now, now),
            )
        result = quarantine_unsafe_contacts(self.db)
        self.assertEqual(result["contacts_rejected"], 1)
        with transaction(self.db) as conn:
            row = conn.execute("SELECT status FROM contacts WHERE case_id=?", (case_id,)).fetchone()
        self.assertEqual(row["status"], "REJECTED")

    def test_medium_unrelated_contact_stays_needs_contact_in_auto_cycle(self):
        imported = import_candidate(candidate("CONTACT-SAFETY-2"), db_path=self.db)
        fake_scan = {"import": {"created": 0, "updated": 1, "case_ids": [imported["case"]["id"]]}}
        fake_contacts = {
            "created": 1,
            "contacts": [{"id": 1, "email": "empresa.segura@gmail.com", "source_url": "https://otro.example/contacto", "confidence_label": "MEDIUM", "status": "DISCOVERED"}],
        }
        with patch("casehunter.auto_service.run_ley_lobby_scan", return_value=fake_scan), patch(
            "casehunter.auto_service.discover_contacts_for_case", return_value=fake_contacts
        ):
            result = run_auto_cycle(source_urls=["https://example.test/list"], min_priority=0, db_path=self.db)
        self.assertEqual(result["drafts_created"], 1)
        queue = list_outreach(db_path=self.db)
        self.assertEqual(queue[0]["status"], "NEEDS_CONTACT")
        self.assertIsNone(queue[0]["recipient_email"])


if __name__ == "__main__":
    unittest.main()
