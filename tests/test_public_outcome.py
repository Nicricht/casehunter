import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db, transaction
from casehunter.discovery.case_builder import build_case
from casehunter.discovery.outcome import analyze_public_outcome
from casehunter.repository import import_candidate
from casehunter.scanner_service import _apply_public_outcomes


class PublicOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "outcome.db"
        init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fully_resolved_public_record(self):
        text = "La deuda fue pagada y el caso cerrado. No mantiene deuda con el proveedor."
        outcome = analyze_public_outcome(text)
        self.assertEqual(outcome["state"], "RESOLVED")
        case = build_case(text)
        self.assertEqual(case["outcome"]["state"], "RESOLVED")
        self.assertEqual(case["problems"], [])

    def test_alembic_style_record_is_partial_not_closed(self):
        text = (
            "Necesitamos iniciar conversaciones para abordar un plan de pago para nuestras facturas vencidas. "
            "ALEMBIC PHARMACEUTICALS. Las facturas vencidas que dieron origen a esta solicitud fueron pagadas "
            "y el estado de las facturas pendientes se informará vía correo electrónico por encargados."
        )
        case = build_case(text)
        self.assertEqual(case["outcome"]["state"], "PARTIAL")
        self.assertIn("PAYMENT_PENDING", {item["type"] for item in case["problems"]})

    def test_resolved_precedent_is_removed_from_active_queue(self):
        text = "La deuda fue pagada. Caso resuelto."
        built = build_case(text)
        candidate = {
            "audience_id": "RESOLVED-DEMO",
            "date": "2026-05-06",
            "detail_url": "https://example.test/resolved",
            "source_url": "https://example.test/list",
            "safis": [],
            "amounts_clp": [1000000],
            "problems": built["problems"],
            "historical_problems": built["historical_problems"],
            "outcome": built["outcome"],
            "confidence": built["confidence"],
            "represented_entities": ["ALEMBIC PHARMACEUTICALS SPA"],
            "works_for": [],
            "raw_text": text,
        }
        imported = import_candidate(candidate, db_path=self.db)["case"]
        result = _apply_public_outcomes([candidate], [imported["id"]], self.db)
        self.assertEqual(result["resolved"], 1)
        with transaction(self.db) as conn:
            case = conn.execute("SELECT status,financial_priority,current_blocker FROM cases WHERE id=?", (imported["id"],)).fetchone()
            open_actions = conn.execute("SELECT COUNT(*) n FROM actions WHERE case_id=? AND status='TODO'", (imported["id"],)).fetchone()["n"]
            precedent = conn.execute("SELECT COUNT(*) n FROM timeline_events WHERE case_id=? AND event_type='PUBLIC_RESOLUTION_SIGNAL'", (imported["id"],)).fetchone()["n"]
        self.assertEqual(case["status"], "RESOLVED")
        self.assertEqual(case["financial_priority"], 0)
        self.assertIsNone(case["current_blocker"])
        self.assertEqual(open_actions, 0)
        self.assertEqual(precedent, 1)


if __name__ == "__main__":
    unittest.main()
