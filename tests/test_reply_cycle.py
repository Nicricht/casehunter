import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from casehunter.database import init_db, transaction
from casehunter.followup import list_followups, process_due_followups
from casehunter.outreach import approve_outreach, ensure_outreach_draft, send_outreach
from casehunter.reply_monitor import classify_reply, ingest_reply, list_replies
from casehunter.repository import get_case, import_candidate


def candidate(aid="REPLY-CYCLE-1"):
    return {
        "audience_id": aid,
        "date": "2026-09-09",
        "detail_url": "https://example.test/case",
        "source_url": "https://example.test",
        "safis": ["777"],
        "amounts_clp": [120000000],
        "problems": [{"type": "RETENTION_PENDING", "matched_patterns": ["retenciones"]}],
        "confidence": {"score": 0.95, "label": "HIGH"},
        "represented_entities": ["Empresa Respuesta SpA"],
        "works_for": [],
        "agency": "MOP",
        "contract_ref": "SAFI 777",
        "raw_text": "retenciones pendientes",
        "detail_text": "retenciones pendientes",
    }


class ReplyCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        init_db(self.db)
        self.case = import_candidate(candidate(), db_path=self.db)["case"]

    def tearDown(self):
        self.tmp.cleanup()

    def _sent_outreach(self):
        draft = ensure_outreach_draft(self.case["id"], "contacto@empresa.cl", db_path=self.db)["message"]
        approve_outreach(draft["id"], db_path=self.db)
        return send_outreach(draft["id"], db_path=self.db, sender=lambda *_: "<first@example.test>")

    def test_classifier_core_intents(self):
        self.assertEqual(classify_reply("Sí, por favor envíamela"), "REQUESTS_INFO")
        self.assertEqual(classify_reply("El pago sigue pendiente"), "STILL_PENDING")
        self.assertEqual(classify_reply("Gracias, ya está resuelto"), "RESOLVED")
        self.assertEqual(classify_reply("No nos interesa, gracias"), "NOT_INTERESTED")

    def test_classifier_detects_agency_no_response(self):
        self.assertEqual(
            classify_reply("Después del 28/07 no hemos recibido más información y el correo del 26/08 quedó sin respuesta."),
            "NO_AGENCY_RESPONSE",
        )

    def test_sent_message_schedules_followup(self):
        sent = self._sent_outreach()
        self.assertEqual(sent["status"], "SENT")
        followups = list_followups(db_path=self.db)
        self.assertEqual(len(followups), 1)
        self.assertEqual(followups[0]["status"], "PENDING")

    def test_positive_reply_updates_case_and_cancels_followup(self):
        sent = self._sent_outreach()
        result = ingest_reply({
            "outreach_id": sent["id"],
            "case_id": self.case["id"],
            "provider_message_id": "<reply-1@example.test>",
            "in_reply_to": "<first@example.test>",
            "sender_email": "contacto@empresa.cl",
            "subject": "Re: Antecedentes públicos",
            "body": "Sí, por favor envíamela.",
            "received_at": "2026-09-09T12:00:00-03:00",
        }, db_path=self.db)
        self.assertTrue(result["created"])
        self.assertEqual(result["reply"]["classification"], "REQUESTS_INFO")
        self.assertEqual(get_case(self.case["id"], self.db)["status"], "VALIDATING")
        self.assertEqual(list_followups(db_path=self.db)[0]["status"], "CANCELLED")
        self.assertEqual(len(list_replies(case_id=self.case["id"], db_path=self.db)), 1)

    def test_no_agency_response_marks_blocker_identified(self):
        sent = self._sent_outreach()
        result = ingest_reply({
            "outreach_id": sent["id"],
            "case_id": self.case["id"],
            "provider_message_id": "<reply-no-response@example.test>",
            "sender_email": "contacto@empresa.cl",
            "subject": "Re: antecedentes",
            "body": "No hemos recibido más información del municipio y nuestro correo quedó sin respuesta.",
        }, db_path=self.db)
        self.assertEqual(result["reply"]["classification"], "NO_AGENCY_RESPONSE")
        self.assertEqual(get_case(self.case["id"], self.db)["status"], "BLOCKER_IDENTIFIED")

    def test_resolved_reply_closes_case(self):
        sent = self._sent_outreach()
        ingest_reply({
            "outreach_id": sent["id"],
            "case_id": self.case["id"],
            "provider_message_id": "<reply-resolved@example.test>",
            "sender_email": "contacto@empresa.cl",
            "subject": "Re: antecedentes",
            "body": "Gracias, ya está resuelto y cerrado.",
        }, db_path=self.db)
        self.assertEqual(get_case(self.case["id"], self.db)["status"], "RESOLVED")

    def test_duplicate_gmail_contact_is_not_sent(self):
        draft = ensure_outreach_draft(self.case["id"], "contacto@empresa.cl", db_path=self.db)["message"]
        approve_outreach(draft["id"], db_path=self.db)
        with patch("casehunter.gmail_service.imap_configured", return_value=True), patch(
            "casehunter.gmail_service.was_recipient_contacted", return_value=True
        ):
            result = send_outreach(draft["id"], db_path=self.db)
        self.assertEqual(result["status"], "SKIPPED_DUPLICATE")

    def test_due_followup_can_send_once(self):
        self._sent_outreach()
        with transaction(self.db) as conn:
            conn.execute("UPDATE followups SET due_at='2000-01-01T00:00:00+00:00'")
        result = process_due_followups(db_path=self.db, send=True, sender=lambda *_: "<followup@example.test>")
        self.assertEqual(result["sent"], 1)
        self.assertEqual(list_followups(db_path=self.db)[0]["status"], "SENT")


if __name__ == "__main__":
    unittest.main()
