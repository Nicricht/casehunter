import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db
from casehunter.pilot_metrics import start_pilot
from casehunter.repository import (
    create_company,
    get_case,
    import_candidate,
    link_case_company,
    update_case_status,
)
from casehunter.resolution_learning import (
    apply_resolution_recommendation,
    refresh_active_pilot_recommendations,
    resolution_recommendation,
)


def candidate(aid, name, agency, text, amount=5_178_271, problems=None):
    return {
        "audience_id": aid,
        "date": "2026-07-28",
        "detail_url": f"https://www.leylobby.gob.cl/example/{aid}",
        "source_url": "https://www.leylobby.gob.cl/example",
        "safis": [],
        "amounts_clp": [amount] if amount else [],
        "problems": problems or [{"type": "PAYMENT_PENDING", "matched_patterns": ["pago pendiente"]}],
        "confidence": {"score": 0.95, "label": "HIGH"},
        "represented_entities": [name],
        "works_for": [],
        "agency": agency,
        "contract_ref": "Proveedor salud",
        "raw_text": text,
        "detail_text": text,
    }


class ResolutionLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "learning.db"
        init_db(self.db)
        self.company = create_company("Alembic Pharmaceuticals SpA", db_path=self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def _open_pilot(self):
        case = import_candidate(candidate(
            "ALEMBIC-RIO-CLARO",
            "ALEMBIC PHARMACEUTICALS SPA",
            "Municipalidad de Río Claro / Salud",
            "Pago pendiente. Solicitud de recursos sin respuesta posterior del municipio.",
        ), db_path=self.db)["case"]
        case = link_case_company(case["id"], self.company["id"], self.db)
        start_pilot(case["id"], "Seguimiento activo del caso Río Claro", self.db)
        return get_case(case["id"], self.db)

    def _resolved_precedent(self):
        text = (
            "Alembic solicitó audiencia por facturas pendientes. La gestión fue derivada a Finanzas "
            "y se informó un plan de pago con fecha concreta. Posteriormente las facturas fueron pagadas."
        )
        case = import_candidate(candidate(
            "ALEMBIC-RESOLVED-1",
            "Alembic Pharmaceuticals SpA",
            "Hospital público / Finanzas",
            text,
            amount=6_000_000,
        ), db_path=self.db)["case"]
        link_case_company(case["id"], self.company["id"], self.db)
        update_case_status(case["id"], "RESOLVED", self.db)
        return get_case(case["id"], self.db)

    def test_same_company_resolved_precedent_generates_recommendation(self):
        target = self._open_pilot()
        precedent = self._resolved_precedent()
        result = resolution_recommendation(target["id"], self.db)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["recommendation"]["action_type"], "VERIFY_PAYMENT_COMMITMENT")
        self.assertGreaterEqual(result["recommendation"]["confidence"], 55)
        self.assertEqual(result["recommendation"]["precedent_count"], 1)
        self.assertEqual(result["recommendation"]["evidence"][0]["case_id"], precedent["id"])
        self.assertIn("No demuestra", result["causality_notice"])

    def test_unrelated_resolved_case_is_not_treated_as_precedent(self):
        target = self._open_pilot()
        other = import_candidate(candidate(
            "OTHER-RESOLVED",
            "Constructora Distinta SpA",
            "MOP Carreteras",
            "Liquidación de contrato terminada y garantía devuelta.",
            amount=900_000_000,
            problems=[{"type": "LIQUIDATION_PENDING", "matched_patterns": ["liquidación pendiente"]}],
        ), db_path=self.db)["case"]
        update_case_status(other["id"], "RESOLVED", self.db)
        result = resolution_recommendation(target["id"], self.db)
        self.assertEqual(result["status"], "INSUFFICIENT_PRECEDENTS")
        self.assertIsNone(result["recommendation"])

    def test_apply_materializes_action_once(self):
        target = self._open_pilot()
        self._resolved_precedent()
        first = apply_resolution_recommendation(target["id"], self.db)
        self.assertTrue(first["materialized"])
        refreshed = get_case(target["id"], self.db)
        matching = [a for a in refreshed["actions"] if a["action_type"] == "VERIFY_PAYMENT_COMMITMENT" and a["status"] == "TODO"]
        self.assertEqual(len(matching), 1)
        self.assertTrue(any(e["event_type"] == "RESOLUTION_RECOMMENDATION" for e in refreshed["timeline"]))

        second = apply_resolution_recommendation(target["id"], self.db)
        self.assertFalse(second["materialized"])
        self.assertEqual(second["materialization_reason"], "equivalent_action_already_open")

    def test_active_pilot_refresh_applies_learning(self):
        target = self._open_pilot()
        self._resolved_precedent()
        result = refresh_active_pilot_recommendations(self.db)
        self.assertEqual(result["active_pilots"], 1)
        self.assertEqual(result["ready"], 1)
        self.assertEqual(result["materialized"], 1)
        refreshed = get_case(target["id"], self.db)
        self.assertTrue(any(a["action_type"] == "VERIFY_PAYMENT_COMMITMENT" for a in refreshed["actions"]))


if __name__ == "__main__":
    unittest.main()
