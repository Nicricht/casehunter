import tempfile
import unittest
from pathlib import Path

from casehunter.contact_discovery import save_contacts
from casehunter.database import init_db
from casehunter.outreach import list_outreach
from casehunter.prospecting import build_prospect_dossier, prepare_prospect
from casehunter.repository import import_candidate


class ProspectingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "prospect.db"
        init_db(self.db)
        candidate = {
            "audience_id": "PROSPECT-1",
            "date": "2026-09-10",
            "detail_url": "https://public.example/case/1",
            "source_url": "https://public.example/list",
            "safis": ["410839"],
            "amounts_clp": [48000000],
            "problems": [{"type": "RETENTION_PENDING", "matched_patterns": ["retenciones"]}],
            "confidence": {"score": 0.92, "label": "HIGH"},
            "represented_entities": ["Constructora Prueba SpA"],
            "works_for": [],
            "agency": "MOP",
            "contract_ref": "SAFI 410839",
            "raw_text": "retenciones contractuales pendientes",
            "detail_text": "antecedentes sobre cierre y retenciones",
        }
        self.case_id = import_candidate(candidate, db_path=self.db)["case"]["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_dossier_separates_confirmed_facts_from_pending_validation(self):
        dossier = build_prospect_dossier(self.case_id, self.db)
        labels = {item["label"] for item in dossier["confirmed_facts"]}
        self.assertIn("Contrato / referencia", labels)
        self.assertTrue(dossier["evidence_sources"])
        self.assertTrue(dossier["pending_validation"])
        self.assertTrue(dossier["requires_human_approval"])
        self.assertFalse(dossier["automatic_send_allowed"])
        self.assertEqual(dossier["recommended_message"]["status"], "NOT_PREPARED")

    def test_prepare_uses_trusted_contact_but_never_approves_or_sends(self):
        save_contacts(
            self.case_id,
            [{
                "email": "contacto@constructoraprueba.cl",
                "source_url": "https://constructoraprueba.cl/contacto",
                "confidence_label": "HIGH",
            }],
            self.db,
        )
        result = prepare_prospect(self.case_id, self.db, discover_contacts=False)
        draft = result["preparation"]["draft"]
        self.assertEqual(draft["status"], "READY_FOR_APPROVAL")
        self.assertEqual(draft["recipient_email"], "contacto@constructoraprueba.cl")
        self.assertIsNone(draft.get("approved_at"))
        self.assertIsNone(draft.get("sent_at"))
        self.assertTrue(result["dossier"]["trusted_contact_found"])
        self.assertTrue(result["dossier"]["ready_for_review"])
        self.assertFalse(result["preparation"]["sent"])

    def test_prepare_without_trusted_contact_stays_needs_contact(self):
        result = prepare_prospect(self.case_id, self.db, discover_contacts=False)
        self.assertEqual(result["preparation"]["draft"]["status"], "NEEDS_CONTACT")
        self.assertFalse(result["dossier"]["trusted_contact_found"])
        messages = [m for m in list_outreach(db_path=self.db) if m["case_id"] == self.case_id]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["status"], "NEEDS_CONTACT")


if __name__ == "__main__":
    unittest.main()
