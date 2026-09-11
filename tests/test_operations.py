import tempfile
import unittest
from pathlib import Path

from casehunter.contact_discovery import save_contacts
from casehunter.database import init_db
from casehunter.operations import operations_snapshot
from casehunter.pilot_metrics import start_pilot
from casehunter.repository import import_candidate


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "operations.db"
        init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_counts_trusted_external_contact(self):
        candidate = {
            "audience_id": "OPS-1",
            "date": "2026-09-09",
            "detail_url": "https://www.leylobby.gob.cl/detail",
            "source_url": "https://www.leylobby.gob.cl/list",
            "safis": ["407848"],
            "amounts_clp": [120000000],
            "problems": [{"type": "LIQUIDATION_PENDING", "matched_patterns": ["cierre administrativo"]}],
            "confidence": {"score": 0.95, "label": "HIGH"},
            "represented_entities": ["PREVCONS SpA"],
            "works_for": [],
            "agency": "MOP",
            "contract_ref": "SAFI 407848",
            "raw_text": "cierre administrativo",
            "detail_text": "cierre administrativo",
        }
        case_id = import_candidate(candidate, db_path=self.db)["case"]["id"]
        save_contacts(
            case_id,
            [{"email": "prevcons@gmail.com", "source_url": "https://prevcons.cl/contacto", "confidence_label": "MEDIUM"}],
            self.db,
        )
        snapshot = operations_snapshot(self.db)
        self.assertEqual(snapshot["kpis"]["cases_total"], 1)
        self.assertEqual(snapshot["kpis"]["contacts_found"], 1)
        self.assertEqual(snapshot["kpis"]["contacts_auto_send_ready"], 1)
        self.assertEqual(snapshot["pilot_funnel"]["counts"]["DETECTED"], 1)
        self.assertEqual(snapshot["top_opportunities"][0]["contact_trust_score"], 75)
        self.assertEqual(snapshot["top_opportunities"][0]["has_auto_send_contact"], 1)

    def test_snapshot_exposes_active_pilot(self):
        candidate = {
            "audience_id": "OPS-PILOT-1",
            "date": "2026-09-11",
            "detail_url": "https://www.leylobby.gob.cl/detail-pilot",
            "source_url": "https://www.leylobby.gob.cl/list",
            "safis": [],
            "amounts_clp": [5178271],
            "problems": [{"type": "PAYMENT_PENDING", "matched_patterns": ["deuda pendiente"]}],
            "confidence": {"score": 1.0, "label": "HIGH"},
            "represented_entities": ["ALEMBIC PHARMACEUTICALS SPA"],
            "works_for": [],
            "agency": "Municipalidad de Río Claro",
            "contract_ref": "Río Claro / CENABAST",
            "raw_text": "deuda pendiente y seguimiento activo",
            "detail_text": "deuda pendiente y seguimiento activo",
        }
        case_id = import_candidate(candidate, db_path=self.db)["case"]["id"]
        start_pilot(case_id, note="La empresa aceptó seguimiento activo", db_path=self.db)

        snapshot = operations_snapshot(self.db)
        self.assertEqual(snapshot["kpis"]["pilots_active"], 1)
        self.assertEqual(snapshot["pilot_funnel"]["counts"]["ACTIVE_PILOT"], 1)
        self.assertEqual(snapshot["pilot_funnel"]["rows"][0]["stage"], "ACTIVE_PILOT")


if __name__ == "__main__":
    unittest.main()
