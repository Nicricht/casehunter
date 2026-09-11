import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db
from casehunter.pilot_watch import build_watchlist
from casehunter.repository import import_candidate, update_case_status


def candidate(aid, company, amount=1000000):
    return {
        "audience_id": aid,
        "date": "2026-09-11",
        "detail_url": f"https://example.test/{aid}",
        "source_url": "https://example.test",
        "safis": [],
        "amounts_clp": [amount],
        "problems": [{"type": "PAYMENT_PENDING", "matched_patterns": ["pago pendiente"]}],
        "confidence": {"score": 0.95, "label": "HIGH"},
        "represented_entities": [company],
        "works_for": [],
        "agency": "Municipalidad",
        "contract_ref": aid,
        "raw_text": "pago pendiente",
        "detail_text": "pago pendiente",
    }


class PilotWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_watchlist_only_returns_active_cases(self):
        active = import_candidate(candidate("PILOT-1", "Empresa Activa"), db_path=self.db)["case"]
        resolved = import_candidate(candidate("PILOT-2", "Empresa Resuelta"), db_path=self.db)["case"]
        update_case_status(active["id"], "BLOCKER_IDENTIFIED", self.db)
        update_case_status(resolved["id"], "RESOLVED", self.db)

        result = build_watchlist(db_path=self.db)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["case_id"], active["id"])
        self.assertEqual(result[0]["status"], "BLOCKER_IDENTIFIED")
        self.assertIsNotNone(result[0]["next_action"])

    def test_watchlist_search_and_limit(self):
        first = import_candidate(candidate("PILOT-3", "Alembic Pharmaceuticals", 5000000), db_path=self.db)["case"]
        import_candidate(candidate("PILOT-4", "Otra Empresa", 1000), db_path=self.db)
        update_case_status(first["id"], "ACTION_REQUIRED", self.db)

        result = build_watchlist(search="Alembic", limit=1, db_path=self.db)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["company"], "Alembic Pharmaceuticals")
        self.assertGreaterEqual(result[0]["watch_score"], 100)


if __name__ == "__main__":
    unittest.main()
