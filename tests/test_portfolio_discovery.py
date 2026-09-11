import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db, transaction
from casehunter.pilot_metrics import start_pilot
from casehunter.portfolio_discovery import refresh_due_pilot_portfolios
from casehunter.portfolio_watch import list_portfolios
from casehunter.repository import import_candidate


def candidate(audience_id, text, amount, outcome="OPEN_OR_UNKNOWN", company="ALEMBIC PHARMACEUTICALS SPA"):
    problems = [] if outcome == "RESOLVED" else [{"type": "PAYMENT_PENDING", "matched_patterns": ["facturas pendientes"]}]
    historical = [{"type": "PAYMENT_PENDING", "matched_patterns": ["facturas vencidas"]}] if outcome == "RESOLVED" else []
    return {
        "audience_id": audience_id,
        "date": "2026-07-28",
        "detail_url": f"https://www.leylobby.gob.cl/detail/{audience_id}",
        "source_url": "https://www.leylobby.gob.cl/list",
        "safis": [],
        "amounts_clp": [amount] if amount else [],
        "problems": problems,
        "historical_problems": historical,
        "outcome": {"state": outcome, "resolved_signals": ["fueron pagadas"] if outcome == "RESOLVED" else [], "pending_signals": []},
        "confidence": {"score": 0.9, "label": "HIGH"},
        "represented_entities": [company],
        "works_for": [],
        "agency": "Organismo público de prueba",
        "raw_text": text,
        "detail_text": text,
    }


class PortfolioDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "portfolio.db"
        init_db(self.db)
        seed = candidate("ALEMBIC-SEED", "Alembic Pharmaceuticals deuda pendiente", 5_178_271)
        self.seed_case = import_candidate(seed, db_path=self.db)["case"]
        start_pilot(self.seed_case["id"], "Alembic pidió seguimiento continuo", self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_active_pilot_refresh_builds_multi_case_portfolio(self):
        cases = [
            candidate("ALEMBIC-RIO-CLARO", "ALEMBIC PHARMACEUTICALS deuda pendiente solicitud de recursos", 5_178_271),
            candidate("ALEMBIC-COPIAPO", "Alembic Pharmaceuticals SpA facturas pendientes programa de pago", 47_000_000),
            candidate("ALEMBIC-RESOLVED", "ALEMBIC PHARMACEUTICALS facturas vencidas fueron pagadas", 9_000_000, outcome="RESOLVED"),
        ]

        def fake_scanner(_url, max_pages=5, enrich=True, enrich_limit=40):
            return {
                "source": "LEY_DEL_LOBBY",
                "source_url": _url,
                "pages_scanned": 1,
                "candidate_count": len(cases),
                "enrichment_errors": [],
                "candidates": cases,
            }

        result = refresh_due_pilot_portfolios(self.db, force=True, scanner=fake_scanner)
        self.assertEqual(result["refreshed"], 1)
        portfolio = result["results"][0]
        self.assertGreaterEqual(portfolio["case_count"], 4)
        self.assertGreaterEqual(portfolio["resolved_case_count"], 1)
        self.assertGreater(portfolio["public_amount_clp"], 50_000_000)

        with transaction(self.db) as conn:
            resolved = conn.execute(
                "SELECT status,financial_priority FROM cases WHERE external_id='ALEMBIC-RESOLVED'"
            ).fetchone()
            open_actions = conn.execute(
                """SELECT COUNT(*) n FROM actions a JOIN cases k ON k.id=a.case_id
                   WHERE k.external_id='ALEMBIC-RESOLVED' AND a.status='TODO'"""
            ).fetchone()["n"]
        self.assertEqual(resolved["status"], "RESOLVED")
        self.assertEqual(int(resolved["financial_priority"]), 0)
        self.assertEqual(open_actions, 0)

    def test_legal_name_variants_group_into_one_portfolio(self):
        import_candidate(candidate("ALEMBIC-VARIANT", "facturas pendientes", 1_000, company="Alembic Pharmaceuticals"), db_path=self.db)
        portfolios = list_portfolios(min_cases=2, active_only=False, db_path=self.db)
        alembic = next(item for item in portfolios if item["identity_key"] == "alembic pharmaceuticals")
        self.assertGreaterEqual(alembic["case_count"], 2)
        self.assertIn("ALEMBIC PHARMACEUTICALS SPA", alembic["name_variants"])


if __name__ == "__main__":
    unittest.main()
