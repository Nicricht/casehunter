import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db, transaction
from casehunter.production_bootstrap import bootstrap_alembic_pilot
from casehunter.repository import get_case


DETAIL_URL = "https://www.leylobby.gob.cl/instituciones/MU271/audiencias/2026/800758/936913"


def fake_scanner(source_url, max_pages=5, enrich=True, enrich_limit=40):
    candidates = []
    if "/MU271/" in source_url:
        candidates.append({
            "audience_id": "MU271AW2265687",
            "date": "2026-07-28",
            "detail_url": DETAIL_URL,
            "source_url": source_url,
            "agency": "Municipalidad de Río Claro / Dirección Comunal de Salud",
            "represented_entities": ["ALEMBIC PHARMACEUTICALS SPA"],
            "works_for": [],
            "safis": [],
            "amounts_clp": [5178271],
            "problems": [{"type": "PAYMENT_PENDING", "matched_patterns": ["deuda vencida"]}],
            "confidence": {"score": 1.0, "label": "HIGH"},
            "raw_text": "Regularización de deuda vencida Alembic Pharmaceuticals. Se reconoce deuda por 5.178.271.",
            "detail_text": "El Director Comunal de Salud enviará detalle de deuda para solicitar recursos para pago.",
            "outcome": {"state": "OPEN_OR_UNKNOWN"},
        })
    return {
        "source": "LEY_DEL_LOBBY",
        "source_url": source_url,
        "pages_scanned": 1,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "enrichment_errors": [],
    }


class ProductionBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "bootstrap.db"
        init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bootstrap_marks_exact_rio_claro_case_as_active_pilot(self):
        result = bootstrap_alembic_pilot(self.db, scanner=fake_scanner)
        self.assertEqual(result["status"], "DONE")

        case = get_case(result["case_id"], self.db)
        self.assertEqual(case["external_id"], "MU271AW2265687")
        self.assertEqual(case["company_name"], "Alembic Pharmaceuticals SpA")
        self.assertEqual(case["status"], "FOLLOW_UP")
        self.assertEqual(case["amounts_clp"], [5178271])
        self.assertTrue(any(e["event_type"] == "PILOT_STARTED" for e in case["timeline"]))
        self.assertTrue(any(a["action_type"] == "WATCH_PUBLIC_CASE" and a["status"] == "TODO" for a in case["actions"]))

    def test_bootstrap_is_idempotent_after_success(self):
        first = bootstrap_alembic_pilot(self.db, scanner=fake_scanner)
        second = bootstrap_alembic_pilot(self.db, scanner=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scanner should not run")))
        self.assertEqual(first["status"], "DONE")
        self.assertEqual(second["status"], "SKIPPED")

        with transaction(self.db) as conn:
            pilot_events = conn.execute(
                "SELECT COUNT(*) n FROM timeline_events WHERE event_type='PILOT_STARTED'"
            ).fetchone()["n"]
            watch_actions = conn.execute(
                "SELECT COUNT(*) n FROM actions WHERE action_type='WATCH_PUBLIC_CASE' AND status='TODO'"
            ).fetchone()["n"]
        self.assertEqual(pilot_events, 1)
        self.assertEqual(watch_actions, 1)


if __name__ == "__main__":
    unittest.main()
