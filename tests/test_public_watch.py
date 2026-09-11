import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db, transaction
from casehunter.public_watch import configure_case_watch, list_watch_sources, run_case_watch
from casehunter.repository import create_action, import_candidate
from casehunter.watch_source_adapters import fetch_watch_source, source_kind


def candidate(aid="WATCH-1", contract_ref="Río Claro Salud"):
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
        "contract_ref": contract_ref,
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

    def test_configuration_adds_lobby_and_rio_claro_official_sources(self):
        result = configure_case_watch(self.case["id"], db_path=self.db)
        self.assertIn(
            "https://www.leylobby.gob.cl/instituciones/MU271/audiencias/2026/800758",
            result["source_urls"],
        )
        self.assertIn(
            "https://www.leylobby.gob.cl/instituciones/MU271/audiencias/2026",
            result["source_urls"],
        )
        self.assertIn("https://rioclaro.cl/", result["source_urls"])
        self.assertIn("https://rioclaro.cl/2026/", result["source_urls"])
        self.assertTrue(any("portaltransparencia.cl" in url for url in result["source_urls"]))
        sources = list_watch_sources(self.case["id"], self.db)
        self.assertGreaterEqual(len(sources), 5)
        self.assertTrue(any(item["source_kind"] == "TRANSPARENCIA" for item in sources))

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
            return {"source_url": _url, "content_type": "text/html", "text": text, "raw_html": None}

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
                "raw_html": None,
            }

        run_case_watch(self.case["id"], fetcher=fetcher, db_path=self.db)
        state["version"] = 2
        result = run_case_watch(self.case["id"], fetcher=fetcher, db_path=self.db)
        self.assertEqual(result["changes"], 0)

    def test_linked_official_sources_are_discovered_for_next_cycle(self):
        configure_case_watch(
            self.case["id"],
            source_urls=["https://rioclaro.cl/"],
            keywords=["pago", "alembic"],
            db_path=self.db,
        )

        def fetcher(_url):
            return {
                "source_url": _url,
                "content_type": "text/html",
                "text": "Alembic pago pendiente",
                "raw_html": """
                    <a href='/decretos-pago/'>Decretos de pago</a>
                    <a href='https://www.portaltransparencia.cl/PortalPdT/pdtta?codOrganismo=MU271'>Transparencia</a>
                    <a href='https://example.com/noticia'>No oficial</a>
                """,
            }

        result = run_case_watch(self.case["id"], fetcher=fetcher, db_path=self.db)
        self.assertEqual(result["discovered_sources"], 2)
        urls = {row["source_url"] for row in list_watch_sources(self.case["id"], self.db)}
        self.assertIn("https://rioclaro.cl/decretos-pago/", urls)
        self.assertTrue(any("portaltransparencia.cl" in url for url in urls))
        self.assertFalse(any("example.com" in url for url in urls))

    def test_mercado_publico_order_becomes_watch_source_and_detects_progress(self):
        other = import_candidate(candidate("WATCH-OC", "OC 2097-241-SE26"), db_path=self.db)["case"]
        configure_case_watch(other["id"], db_path=self.db)
        sources = list_watch_sources(other["id"], self.db)
        market = [row for row in sources if row["source_kind"] == "MERCADO_PUBLICO_OC"]
        self.assertEqual(len(market), 1)
        self.assertEqual(market[0]["source_url"], "mercadopublico:oc:2097-241-SE26")

        state = {"accepted": False}

        def market_fetcher(_code):
            return {
                "Codigo": "2097-241-SE26",
                "CodigoEstado": 13 if not state["accepted"] else 6,
                "Estado": "Pendiente de Recepcionar" if not state["accepted"] else "Aceptada",
                "Comprador": {"NombreOrganismo": "Municipalidad de Río Claro"},
                "Proveedor": {"Nombre": "Alembic Pharmaceuticals SpA"},
                "Fechas": {"FechaUltimaModificacion": "2026-09-11T10:00:00"},
            }

        def http_fetcher(_url):
            return {"source_url": _url, "content_type": "text/html", "text": "sin cambios relevantes", "raw_html": None}

        first = run_case_watch(other["id"], fetcher=http_fetcher, mercado_fetcher=market_fetcher, db_path=self.db)
        self.assertGreaterEqual(first["baselined"], 1)
        state["accepted"] = True
        second = run_case_watch(other["id"], fetcher=http_fetcher, mercado_fetcher=market_fetcher, db_path=self.db)
        market_events = [event for event in second["events"] if event["source_kind"] == "MERCADO_PUBLICO_OC"]
        self.assertEqual(len(market_events), 1)
        self.assertEqual(market_events[0]["signal"], "ORDER_PROGRESS")

    def test_source_adapter_classifies_official_sources(self):
        self.assertEqual(source_kind("https://www.leylobby.gob.cl/x"), "LEY_LOBBY")
        self.assertEqual(source_kind("https://www.portaltransparencia.cl/x"), "TRANSPARENCIA")
        self.assertEqual(source_kind("mercadopublico:oc:1234-1-SE26"), "MERCADO_PUBLICO_OC")
        result = fetch_watch_source(
            "mercadopublico:oc:1234-1-SE26",
            mercado_fetcher=lambda code: {"Codigo": code, "Estado": "Aceptada", "CodigoEstado": 6},
        )
        self.assertIn("estado: Aceptada", result["text"])


if __name__ == "__main__":
    unittest.main()
