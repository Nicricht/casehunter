import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db
from casehunter.public_watch import configure_case_watch, list_watch_sources
from casehunter.repository import create_action, import_candidate
from casehunter.watch_batch import (
    _enforce_source_budget,
    _new_discovery_urls,
    _protected_urls,
    run_bounded_active_watches,
)


def candidate():
    primary = "https://www.leylobby.gob.cl/instituciones/MU271/audiencias/2026/800758"
    return {
        "audience_id": "WATCH-BATCH-1",
        "date": "2026-07-28",
        "detail_url": primary,
        "source_url": primary,
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


class WatchBatchTests(unittest.TestCase):
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
        configure_case_watch(
            self.case["id"],
            source_urls=[
                candidate()["detail_url"],
                "https://rioclaro.cl/decretos-pago/",
                "https://rioclaro.cl/tesoreria/",
                "https://rioclaro.cl/transparencia/",
            ],
            keywords=["alembic", "pago", "recursos"],
            db_path=self.db,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_batch_is_bounded_keeps_primary_and_rotates_secondary_sources(self):
        calls = []

        def fetcher(url):
            calls.append(url)
            return {
                "source_url": url,
                "content_type": "text/html",
                "text": "Alembic pago pendiente sin cambio material",
                "raw_html": None,
            }

        first = run_bounded_active_watches(
            db_path=self.db,
            fetcher=fetcher,
            source_limit_per_case=2,
        )
        primary = candidate()["detail_url"]
        first_calls = list(calls)
        self.assertEqual(first["active_cases"], 1)
        self.assertEqual(first["selected_sources"], 2)
        self.assertEqual(first["checked"], 2)
        self.assertIn(primary, first_calls)

        calls.clear()
        second = run_bounded_active_watches(
            db_path=self.db,
            fetcher=fetcher,
            source_limit_per_case=2,
        )
        second_calls = list(calls)
        self.assertEqual(second["selected_sources"], 2)
        self.assertEqual(second["checked"], 2)
        self.assertIn(primary, second_calls)

        first_secondary = [url for url in first_calls if url != primary]
        second_secondary = [url for url in second_calls if url != primary]
        self.assertEqual(len(first_secondary), 1)
        self.assertEqual(len(second_secondary), 1)
        self.assertNotEqual(first_secondary[0], second_secondary[0])

    def test_source_budget_archives_overflow_and_never_reactivates_archived_discovery(self):
        configure_case_watch(self.case["id"], db_path=self.db)
        configure_case_watch(
            self.case["id"],
            source_urls=[f"https://noise.example.com/page-{index}" for index in range(20)],
            keywords=["alembic"],
            db_path=self.db,
        )

        budget = 7
        result = _enforce_source_budget(self.case["id"], max_sources=budget, db_path=self.db)
        sources = list_watch_sources(self.case["id"], db_path=self.db)
        active = [item for item in sources if item["status"] == "ACTIVE"]
        archived = [item for item in sources if item["status"] == "ARCHIVED"]
        protected = _protected_urls(self.case)

        self.assertGreater(result["archived_sources"], 0)
        self.assertGreater(len(archived), 0)
        self.assertEqual(len(active), max(budget, len(protected)))
        for url in protected:
            matching = [item for item in sources if item["source_url"] == url]
            self.assertTrue(matching)
            self.assertEqual(matching[0]["status"], "ACTIVE")

        archived_url = archived[0]["source_url"]
        new_url = "https://noise.example.com/new-page"
        allowed = _new_discovery_urls(
            self.case["id"],
            [archived_url, new_url],
            remaining_capacity=2,
            db_path=self.db,
        )
        self.assertNotIn(archived_url, allowed)
        self.assertEqual(allowed, [new_url])


if __name__ == "__main__":
    unittest.main()
