import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from casehunter.auto_service import run_auto_cycle
from casehunter.contact_discovery import save_contacts
from casehunter.database import init_db, transaction, utc_now
from casehunter.outreach import ensure_outreach_draft, list_outreach
from casehunter.repository import import_candidate


def candidate(aid="AUTO-CYCLE-1", company="Empresa Auto SpA", contract="SAFI 999"):
    return {
        "audience_id": aid,
        "date": "2026-09-09",
        "detail_url": "https://example.test/a",
        "source_url": "https://example.test",
        "safis": [contract.replace("SAFI ", "")],
        "amounts_clp": [150000000],
        "problems": [{"type": "RETENTION_PENDING", "matched_patterns": ["retenciones"]}],
        "confidence": {"score": 0.95, "label": "HIGH"},
        "represented_entities": [company],
        "works_for": [],
        "agency": "MOP",
        "contract_ref": contract,
        "raw_text": "retenciones",
        "detail_text": "retenciones",
    }


class AutoServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        init_db(self.db)
        # Unit tests must never consult the operator's real Gmail account,
        # even when CI happens to expose production credentials.
        self.monitor_patcher = patch("casehunter.auto_service.AUTO_MONITOR_REPLIES", False)
        self.imap_patcher = patch("casehunter.gmail_service.imap_configured", return_value=False)
        self.monitor_patcher.start()
        self.imap_patcher.start()

    def tearDown(self):
        self.imap_patcher.stop()
        self.monitor_patcher.stop()
        self.tmp.cleanup()

    def _run_with_contact(self, case_id, saved, smtp_id="<policy-test@casehunter>", daily_limit=10):
        fake_scan = {"import": {"created": 0, "updated": 1, "case_ids": [case_id]}}
        fake_contacts = {"created": 0, "contacts": saved["contacts"]}
        patches = (
            patch("casehunter.auto_service.run_ley_lobby_scan", return_value=fake_scan),
            patch("casehunter.auto_service.discover_contacts_for_case", return_value=fake_contacts),
            patch("casehunter.auto_service.AUTO_POLICY_SEND", True),
            patch("casehunter.auto_service.AUTO_SEND_MIN_PRIORITY", 0),
            patch("casehunter.auto_service.AUTO_MAX_FIRST_CONTACTS_PER_DAY", daily_limit),
            patch("casehunter.auto_service.smtp_configured", return_value=True),
            patch("casehunter.outreach._send_smtp", return_value=smtp_id),
        )
        for item in patches:
            item.start()
        try:
            return run_auto_cycle(
                source_urls=["https://example.test/list"], min_priority=0, send_approved=True, db_path=self.db
            )
        finally:
            for item in reversed(patches):
                item.stop()

    def test_cycle_creates_approval_draft_when_policy_is_off(self):
        imported = import_candidate(candidate(), db_path=self.db)
        case_id = imported["case"]["id"]
        saved = save_contacts(
            case_id,
            [{"email": "contacto@empresaauto.cl", "source_url": "https://empresaauto.cl/contacto", "confidence_label": "HIGH"}],
            self.db,
        )
        fake_scan = {"import": {"created": 0, "updated": 1, "case_ids": [case_id]}}
        fake_contacts = {"created": 0, "contacts": saved["contacts"]}
        with patch("casehunter.auto_service.run_ley_lobby_scan", return_value=fake_scan), patch(
            "casehunter.auto_service.discover_contacts_for_case", return_value=fake_contacts
        ), patch("casehunter.auto_service.AUTO_POLICY_SEND", False):
            result = run_auto_cycle(source_urls=["https://example.test/list"], min_priority=0, db_path=self.db)
        self.assertEqual(result["drafts_created"], 1)
        queue = list_outreach(db_path=self.db)
        self.assertEqual(queue[0]["status"], "READY_FOR_APPROVAL")
        self.assertEqual(queue[0]["recipient_email"], "contacto@empresaauto.cl")

    def test_high_confidence_official_contact_is_sent_without_manual_approval(self):
        imported = import_candidate(candidate("AUTO-SEND-1", "Constructora Valko S.A.", "SAFI 278592"), db_path=self.db)
        case_id = imported["case"]["id"]
        saved = save_contacts(
            case_id,
            [{"email": "contacto@valko.cl", "source_url": "https://www.valko.cl/contacto", "confidence_label": "HIGH"}],
            self.db,
        )
        result = self._run_with_contact(case_id, saved)
        self.assertEqual(result["messages_sent"], 1)
        self.assertEqual(result["policy_auto_send"]["auto_approved"], 1)
        self.assertEqual(result["policy_auto_send"]["auto_sent"], 1)
        queue = list_outreach(db_path=self.db)
        self.assertEqual(queue[0]["status"], "SENT")

    def test_official_company_site_can_validate_gmail_address(self):
        imported = import_candidate(candidate("AUTO-SEND-GMAIL", "Prevcons SpA", "SAFI 407848"), db_path=self.db)
        case_id = imported["case"]["id"]
        saved = save_contacts(
            case_id,
            [{"email": "prevcons@gmail.com", "source_url": "https://prevcons.cl/contacto", "confidence_label": "MEDIUM"}],
            self.db,
        )
        result = self._run_with_contact(case_id, saved, smtp_id="<gmail-policy@casehunter>")
        self.assertEqual(result["messages_sent"], 1)
        self.assertEqual(result["policy_auto_send"]["auto_sent"], 1)
        queue = list_outreach(db_path=self.db)
        self.assertEqual(queue[0]["recipient_email"], "prevcons@gmail.com")
        self.assertEqual(queue[0]["status"], "SENT")

    def test_company_domain_mismatch_is_not_auto_sent(self):
        imported = import_candidate(candidate("AUTO-SEND-2", "Constructora Valko S.A.", "SAFI 278593"), db_path=self.db)
        case_id = imported["case"]["id"]
        saved = save_contacts(
            case_id,
            [{"email": "contacto@otraempresa.cl", "source_url": "https://otraempresa.cl/contacto", "confidence_label": "HIGH"}],
            self.db,
        )
        result = self._run_with_contact(case_id, saved, smtp_id="<should-not-send@casehunter>")
        self.assertEqual(result["messages_sent"], 0)
        queue = list_outreach(db_path=self.db)
        self.assertEqual(queue[0]["status"], "NEEDS_CONTACT")
        self.assertIsNone(queue[0]["recipient_email"])

    def test_daily_limit_blocks_additional_first_contact(self):
        first = import_candidate(candidate("AUTO-LIMIT-OLD", "Rincor SpA", "SAFI 100"), db_path=self.db)["case"]["id"]
        old_message = ensure_outreach_draft(first, "contacto@rincor.cl", db_path=self.db)["message"]
        with transaction(self.db) as conn:
            conn.execute(
                "UPDATE outreach_messages SET status='SENT',sent_at=?,updated_at=? WHERE id=?",
                (utc_now(), utc_now(), old_message["id"]),
            )

        imported = import_candidate(candidate("AUTO-LIMIT-NEW", "Constructora Valko S.A.", "SAFI 101"), db_path=self.db)
        case_id = imported["case"]["id"]
        saved = save_contacts(
            case_id,
            [{"email": "contacto@valko.cl", "source_url": "https://valko.cl/contacto", "confidence_label": "HIGH"}],
            self.db,
        )
        result = self._run_with_contact(case_id, saved, smtp_id="<should-not-send@casehunter>", daily_limit=1)
        self.assertEqual(result["messages_sent"], 0)
        self.assertTrue(result["policy_auto_send"]["limit_reached"])


if __name__ == "__main__":
    unittest.main()
