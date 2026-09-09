import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db
from casehunter.repository import (
    add_timeline_event,
    create_action,
    create_company,
    dashboard,
    get_case,
    import_candidate,
    link_case_company,
    list_cases,
    update_action,
    update_case_status,
    update_document,
)


def candidate(aid="AM002AW2052621"):
    return {
        "audience_id": aid,
        "date": "2026-01-21",
        "detail_url": f"https://www.leylobby.gob.cl/detail/{aid}",
        "source_url": "https://www.leylobby.gob.cl/list",
        "safis": ["319892"],
        "amounts_clp": [100_000_000],
        "problems": [
            {"type": "LIQUIDATION_PENDING", "matched_patterns": ["liquidacion del contrato"]},
            {"type": "RETENTION_PENDING", "matched_patterns": ["devolucion de retenciones"]},
        ],
        "confidence": {"score": 1.0, "label": "HIGH"},
        "represented_entities": ["CONSTRUCTORA DEMO SPA"],
        "works_for": [],
        "raw_text": "SAFI 319.892 liquidación del contrato devolución de retenciones $100.000.000",
        "detail_text": "Detalle oficial",
    }


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "test.db"
        init_db(self.db)

    def tearDown(self): self.tmp.cleanup()

    def test_import_creates_resolution_plan(self):
        result = import_candidate(candidate(), db_path=self.db)
        case = result["case"]
        self.assertTrue(result["created"])
        self.assertEqual(case["current_blocker"], "LIQUIDATION_PENDING")
        self.assertGreater(len(case["documents"]), 0)
        self.assertGreater(len(case["actions"]), 0)

    def test_import_is_idempotent(self):
        first = import_candidate(candidate(), db_path=self.db)
        second = import_candidate(candidate(), db_path=self.db)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(len(list_cases(db_path=self.db)), 1)

    def test_company_can_be_linked(self):
        case = import_candidate(candidate(), db_path=self.db)["case"]
        company = create_company("Constructora Demo SpA", "76.111.222-3", self.db)
        linked = link_case_company(case["id"], company["id"], self.db)
        self.assertEqual(linked["company_rut"], "76.111.222-3")

    def test_status_change_creates_timeline(self):
        case = import_candidate(candidate(), db_path=self.db)["case"]
        updated = update_case_status(case["id"], "VALIDATING", self.db)
        self.assertEqual(updated["status"], "VALIDATING")
        self.assertTrue(any(e["event_type"] == "STATUS_CHANGED" for e in updated["timeline"]))

    def test_invalid_status_rejected(self):
        case = import_candidate(candidate(), db_path=self.db)["case"]
        with self.assertRaises(ValueError): update_case_status(case["id"], "MAGIC", self.db)

    def test_document_workflow(self):
        case = import_candidate(candidate(), db_path=self.db)["case"]
        doc = case["documents"][0]
        updated = update_document(doc["id"], "MISSING", "Proveedor debe conseguirlo", self.db)
        self.assertTrue(any(d["id"] == doc["id"] and d["status"] == "MISSING" for d in updated["documents"]))

    def test_action_workflow(self):
        case = import_candidate(candidate(), db_path=self.db)["case"]
        action = create_action(case["id"], "Llamar a la unidad responsable", db_path=self.db)
        done = update_action(action["id"], "DONE", db_path=self.db)
        self.assertEqual(done["status"], "DONE")

    def test_manual_timeline_note(self):
        case = import_candidate(candidate(), db_path=self.db)["case"]
        add_timeline_event(case["id"], "Empresa confirmó documento faltante", db_path=self.db)
        refreshed = get_case(case["id"], self.db)
        self.assertTrue(any(e["title"] == "Empresa confirmó documento faltante" for e in refreshed["timeline"]))

    def test_dashboard_counts(self):
        import_candidate(candidate("A1"), db_path=self.db)
        import_candidate(candidate("A2"), db_path=self.db)
        d = dashboard(self.db)
        self.assertEqual(d["total_cases"], 2)
        self.assertGreater(d["open_actions"], 0)

    def test_case_search(self):
        import_candidate(candidate(), db_path=self.db)
        rows = list_cases(search="319892", db_path=self.db)
        self.assertEqual(len(rows), 1)


if __name__ == "__main__": unittest.main()
