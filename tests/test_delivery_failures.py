import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db, transaction, utc_now
from casehunter.delivery_health import get_delivery_failure, is_unusable_email
from casehunter.delivery_monitor import classify_delivery_failure
from casehunter.followup import list_followups
from casehunter.outreach import approve_outreach, ensure_outreach_draft, get_outreach, send_outreach
from casehunter.prospecting import build_prospect_dossier
from casehunter.reply_monitor import ingest_delivery_failure, list_replies
from casehunter.repository import get_case, import_candidate


def candidate(aid="DELIVERY-1"):
    return {
        "audience_id": aid,
        "date": "2026-09-13",
        "detail_url": "https://example.test/case",
        "source_url": "https://example.test",
        "safis": ["901"],
        "amounts_clp": [45000000],
        "problems": [{"type": "PAYMENT_PENDING", "matched_patterns": ["pago pendiente"]}],
        "confidence": {"score": 0.95, "label": "HIGH"},
        "represented_entities": ["Empresa Rebote SpA"],
        "works_for": [],
        "agency": "Hospital Público",
        "contract_ref": "OC 901",
        "raw_text": "pago pendiente",
        "detail_text": "pago pendiente",
    }


class DeliveryFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        init_db(self.db)
        self.case = import_candidate(candidate(), db_path=self.db)["case"]

    def tearDown(self):
        self.tmp.cleanup()

    def _contact(self, email, score=95):
        now = utc_now()
        with transaction(self.db) as conn:
            cur = conn.execute(
                """INSERT INTO contacts(case_id,company_name,email,source_url,confidence_label,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,'VERIFIED',?,?)""",
                (
                    self.case["id"], "Empresa Rebote SpA", email,
                    "https://empresa.test/contacto", "HIGH", now, now,
                ),
            )
            contact_id = int(cur.lastrowid)
            conn.execute(
                """INSERT INTO contact_assessments(
                       contact_id,trust_score,decision,reasons,source_host,email_domain,assessed_at
                   ) VALUES(?,?,'AUTO_SEND','[]','empresa.test','empresa.test',?)""",
                (contact_id, score, now),
            )
        return contact_id

    def _sent(self, email="cobranza@empresa.test"):
        contact_id = self._contact(email)
        draft = ensure_outreach_draft(
            self.case["id"], email, contact_id=contact_id, db_path=self.db
        )["message"]
        approve_outreach(draft["id"], db_path=self.db)
        return send_outreach(
            draft["id"], db_path=self.db, sender=lambda *_: "<sent@example.test>"
        )

    def test_delivery_failure_classifier_distinguishes_invalid_and_blocked(self):
        self.assertEqual(
            classify_delivery_failure(
                "Delivery Status Notification (Failure)",
                "No se encontró la dirección. Respuesta: 550 5.1.1 No Such User",
            ),
            "INVALID",
        )
        self.assertEqual(
            classify_delivery_failure(
                "Delivery Status Notification (Failure)",
                "El mensaje se bloqueó. Se bloqueó tu mensaje para contacto@empresa.cl.",
            ),
            "BLOCKED",
        )

    def test_invalid_address_is_suppressed_and_creates_alternate_contact_action(self):
        sent = self._sent()
        result = ingest_delivery_failure({
            "outreach_id": sent["id"],
            "case_id": self.case["id"],
            "contact_id": sent["contact_id"],
            "recipient_email": sent["recipient_email"],
            "provider_message_id": "<dsn-invalid@example.test>",
            "failure_kind": "INVALID",
            "reason": "550 5.1.1 No Such User",
        }, db_path=self.db)

        self.assertTrue(result["created"])
        self.assertEqual(result["status"], "BOUNCED")
        self.assertEqual(get_outreach(sent["id"], self.db)["status"], "BOUNCED")
        self.assertTrue(is_unusable_email("cobranza@empresa.test", self.db))
        self.assertEqual(get_delivery_failure("cobranza@empresa.test", self.db)["failure_kind"], "INVALID")
        self.assertEqual(list_followups(db_path=self.db)[0]["status"], "CANCELLED")
        self.assertEqual(len(list_replies(case_id=self.case["id"], db_path=self.db)), 0)

        case = get_case(self.case["id"], self.db)
        self.assertTrue(any(a["action_type"] == "FIND_ALTERNATE_CONTACT" for a in case["actions"]))
        with transaction(self.db) as conn:
            contact = conn.execute("SELECT status FROM contacts WHERE id=?", (sent["contact_id"],)).fetchone()
        self.assertEqual(contact["status"], "REJECTED")

        with self.assertRaisesRegex(ValueError, "suprimido"):
            ensure_outreach_draft(self.case["id"], "cobranza@empresa.test", db_path=self.db)

    def test_blocked_delivery_is_distinct_from_invalid_address(self):
        sent = self._sent("finanzas@empresa.test")
        result = ingest_delivery_failure({
            "outreach_id": sent["id"],
            "case_id": self.case["id"],
            "recipient_email": "finanzas@empresa.test",
            "provider_message_id": "<dsn-blocked@example.test>",
            "failure_kind": "BLOCKED",
            "reason": "Message blocked by destination policy",
        }, db_path=self.db)
        self.assertEqual(result["status"], "DELIVERY_BLOCKED")
        self.assertEqual(get_outreach(sent["id"], self.db)["status"], "DELIVERY_BLOCKED")
        self.assertEqual(get_delivery_failure("finanzas@empresa.test", self.db)["failure_kind"], "BLOCKED")

    def test_dossier_chooses_alternate_contact_after_bounce(self):
        sent = self._sent("cobranza@empresa.test")
        alternate_id = self._contact("info@empresa.test", score=90)
        ingest_delivery_failure({
            "outreach_id": sent["id"],
            "case_id": self.case["id"],
            "recipient_email": "cobranza@empresa.test",
            "provider_message_id": "<dsn-switch@example.test>",
            "failure_kind": "INVALID",
            "reason": "No such user",
        }, db_path=self.db)

        dossier = build_prospect_dossier(self.case["id"], self.db)
        self.assertEqual(dossier["best_contact"]["id"], alternate_id)
        self.assertEqual(dossier["best_contact"]["email"], "info@empresa.test")


if __name__ == "__main__":
    unittest.main()
