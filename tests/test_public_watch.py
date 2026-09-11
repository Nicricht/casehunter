import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db, transaction
from casehunter.public_watch import configure_case_watch, list_watch_sources, run_case_watch
from casehunter.repository import create_action, import_candidate


def candidate(aid="WATCH-1"):
    return {
        "audience_id": aid,
        "date": "2026-07-28",
        "detail_url": "https://www.leylobby.gob.cl/instituciones/MU271/audiencias/2026/800758",
        "source_url": "https://www.leylobby.gob.cl/instituciones/MU271/audiencias/2026",
        "safis": [],
        "amounts_clp": [5178271],
        "problems": [{"type": "PAYMENT_PENDING", "matched_patterns": ["deuda"]}],
        "confidence": {"score": 0.95, "label": "HIGH"},
        "represented_entities": ["Alembic Pharmaceuticals SpA"],
        "works_for": [],
        "agency": "Municipalidad de Río Claro",
        "contract_ref": "Río Claro Salud",
        "raw_text": "deuda pendiente y solicitud de recursos",
        "detail_text": "deuda pendiente y solicitud de recursos",
    }


class PublicWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        init_db(self.db)
        self.case = import_candidate(candidate(), db_path=self.db)["case"]
        create_action(
            self.case["id"],
            "Mantener vigilancia pública del caso piloto",
            action_type="WATCH_PUBLIC_CASE",
            db_path=self.db,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_configuration_adds_detail_and_lobby_parent(self):
        result = configure_case_watch(self.case["id"], db_path=self.db)
        self.assertIn(
            "https://www.leylobby.gob.cl/instituciones/MU271/audiencias/2026/800758",
            result["source_urls"],
        )
        self.assertIn(
            "https://www.leylobby.gob.cl/instituciones/MU271/audiencias/2026",
            result["source_urls"],
        )
        self.assertEqual(len(list_watch_sources(self.case["id"], self.db)), 2)

    def test_first_run_is_baseline_second_actionable_change_creates_action(self):
        configure_case_watch(
            self.case["id"],
            source_urls=["https://public.example/rioclaro"],
            keywords=["alembic", "pago", "recursos", "remesa", "compromiso"],
            db_path=self.db,
        )
        state = {"version": 1}

        def fetcher(_url):
            if state["version"] == 1:
                text = "Alembic mantiene pago pendiente. Salud informó solicitud de recursos."
            else:
                text = "Alembic mantiene pago pendiente. Se informó compromiso de pago para el 20 de septiembre."
            return {"source_url": _url, "content_type": "text/html", "text": text}

        first = run_case_watch(self.case["id"], fetcher=fetcher, db_path=self.db)
        self.assertEqual(first["baselined"], 1)
        self.assertEqual(first["changes"], 0)

        state["version"] = 2
        second = run_case_watch(self.case["id"], fetcher=fetcher, db_path=self.db)
        self.assertEqual(second["changes"], 1)
        self.assertEqual(second["events"][0]["signal"], "PAYMENT_COMMITMENT")

        with transaction(self.db) as conn:
            action = conn.execute(
                "SELECT * FROM actions WHERE case_id=? AND action_type='VERIFY_PAYMENT_COMMITMENT'",
                (self.case["id"],),
            ).fetchone()
            event = conn.execute(
                "SELECT * FROM timeline_events WHERE case_id=? AND event_type='PUBLIC_WATCH_CHANGE'",
                (self.case["id"],),
            ).fetchone()
        self.assertIsNotNone(action)
        self.assertIsNotNone(event)

    def test_irrelevant_page_change_does_not_alert(self):
        configure_case_watch(
            self.case["id"],
            source_urls=["https://public.example/rioclaro"],
            keywords=["alembic", "pago"],
            db_path=self.db,
        )
        state = {"version": 1}

        def fetcher(_url):
            suffix = "Noticias generales uno" if state["version"] == 1 else "Noticias generales dos"
            return {
                "source_url": _url,
                "content_type": "text/html",
                "text": f"Alembic pago pendiente\n{suffix}",
            }

        run_case_watch(self.case["id"], fetcher=fetcher, db_path=self.db)
        state["version"] = 2
        result = run_case_watch(self.case["id"], fetcher=fetcher, db_path=self.db)
        self.assertEqual(result["changes"], 0)


if __name__ == "__main__":
    unittest.main()
