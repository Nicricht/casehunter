import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db
from casehunter.outreach import approve_outreach, build_outreach_email, ensure_outreach_draft, get_outreach, send_outreach
from casehunter.repository import import_candidate


class OutreachTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        init_db(self.db)
        candidate = {
            "audience_id": "AUTO-1", "date": "2026-09-09", "detail_url": "https://example.test/case",
            "source_url": "https://example.test", "safis": ["278592"], "amounts_clp": [12000000],
            "problems": [{"type": "RETENTION_PENDING", "matched_patterns": ["retenciones"]}],
            "confidence": {"score": 0.9, "label": "HIGH"}, "represented_entities": ["Constructora Prueba SpA"],
            "works_for": [], "agency": "MOP", "contract_ref": "SAFI 278592", "raw_text": "retenciones", "detail_text": "retenciones",
        }
        self.case_id = import_candidate(candidate, db_path=self.db)["case"]["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_email_does_not_claim_recovery(self):
        from casehunter.repository import get_case
        payload = build_outreach_email(get_case(self.case_id, self.db))
        self.assertIn("¿Se las envío?", payload["body"])
        self.assertIn("Case Hunter", payload["body"])
        self.assertIn("No represento al organismo ni a una empresa de cobranza", payload["body"])
        self.assertIn("La utilidad concreta", payload["body"])
        self.assertNotIn("recuperar su dinero", payload["body"].lower())

    def test_draft_deduplicates(self):
        first = ensure_outreach_draft(self.case_id, "contacto@empresa.cl", db_path=self.db)
        second = ensure_outreach_draft(self.case_id, "contacto@empresa.cl", db_path=self.db)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["message"]["id"], second["message"]["id"])

    def test_send_requires_approval(self):
        message = ensure_outreach_draft(self.case_id, "contacto@empresa.cl", db_path=self.db)["message"]
        with self.assertRaises(ValueError):
            send_outreach(message["id"], self.db, sender=lambda *args: "x")
        approve_outreach(message["id"], db_path=self.db)
        sent = send_outreach(message["id"], self.db, sender=lambda *args: "provider-123")
        self.assertEqual(sent["status"], "SENT")
        self.assertEqual(sent["provider_message_id"], "provider-123")


if __name__ == "__main__":
    unittest.main()
