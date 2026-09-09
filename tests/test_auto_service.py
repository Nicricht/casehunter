import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from casehunter.auto_service import run_auto_cycle
from casehunter.database import init_db
from casehunter.outreach import list_outreach
from casehunter.repository import import_candidate


class AutoServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cycle_creates_approval_draft(self):
        candidate = {
            "audience_id": "AUTO-CYCLE-1", "date": "2026-09-09", "detail_url": "https://example.test/a",
            "source_url": "https://example.test", "safis": ["999"], "amounts_clp": [150000000],
            "problems": [{"type": "RETENTION_PENDING", "matched_patterns": ["retenciones"]}],
            "confidence": {"score": 0.95, "label": "HIGH"}, "represented_entities": ["Empresa Auto SpA"],
            "works_for": [], "agency": "MOP", "contract_ref": "SAFI 999", "raw_text": "retenciones", "detail_text": "retenciones",
        }
        imported = import_candidate(candidate, db_path=self.db)
        fake_scan = {"import": {"created": 0, "updated": 1, "case_ids": [imported["case"]["id"]]}}
        fake_contacts = {"created": 1, "contacts": [{"id": None, "email": "contacto@empresa.cl", "confidence_label": "HIGH"}]}
        with patch("casehunter.auto_service.run_ley_lobby_scan", return_value=fake_scan), patch("casehunter.auto_service.discover_contacts_for_case", return_value=fake_contacts):
            result = run_auto_cycle(source_urls=["https://example.test/list"], min_priority=0, db_path=self.db)
        self.assertEqual(result["drafts_created"], 1)
        queue = list_outreach(db_path=self.db)
        self.assertEqual(queue[0]["status"], "READY_FOR_APPROVAL")
        self.assertEqual(queue[0]["recipient_email"], "contacto@empresa.cl")


if __name__ == "__main__":
    unittest.main()
