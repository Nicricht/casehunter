import tempfile
import unittest
from pathlib import Path

from casehunter.commercial_pipeline import commercial_stage, commercialize_case, opportunity_score
from casehunter.database import init_db
from casehunter.operations import operations_snapshot
from casehunter.repository import import_candidate


class CommercialPipelineTests(unittest.TestCase):
    def test_qualified_reply_outranks_unengaged_case(self):
        base = {
            "status": "VALIDATING",
            "financial_priority": 70,
            "confidence_score": 0.9,
            "contact_trust_score": 80,
            "has_auto_send_contact": 1,
            "has_contact": 1,
            "has_contacted": 1,
            "has_reply": 0,
            "latest_reply_classification": "",
            "has_watch_action": 0,
        }
        engaged = dict(base)
        engaged["has_reply"] = 1
        engaged["latest_reply_classification"] = "REQUESTS_INFO"

        self.assertEqual(commercial_stage(base), "CONTACTED")
        self.assertEqual(commercial_stage(engaged), "QUALIFIED")
        self.assertGreater(opportunity_score(engaged), opportunity_score(base))

    def test_follow_up_with_watch_action_is_watching(self):
        case = {
            "status": "FOLLOW_UP",
            "financial_priority": 60,
            "confidence_score": 0.95,
            "contact_trust_score": 75,
            "has_contact": 1,
            "has_auto_send_contact": 1,
            "has_contacted": 1,
            "has_reply": 1,
            "latest_reply_classification": "PILOT_REQUESTED",
            "has_watch_action": 1,
        }
        result = commercialize_case(case)
        self.assertEqual(result["commercial_stage"], "WATCHING")
        self.assertIn("Vigilar cambios públicos", result["next_commercial_move"])
        self.assertIn("seguimiento público activo", result["opportunity_reasons"])
        self.assertGreaterEqual(result["opportunity_score"], 70)

    def test_operations_exposes_ranked_commercial_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "commercial.db"
            init_db(db)
            imported = import_candidate({
                "audience_id": "COMMERCIAL-1",
                "date": "2026-09-12",
                "detail_url": "https://example.test/case",
                "source_url": "https://example.test/index",
                "safis": ["123"],
                "amounts_clp": [90000000],
                "problems": [{"type": "PAYMENT_PENDING", "matched_patterns": ["pago pendiente"]}],
                "confidence": {"score": 0.95, "label": "HIGH"},
                "represented_entities": ["Empresa Comercial SpA"],
                "works_for": [],
                "agency": "Organismo Público",
                "contract_ref": "SAFI 123",
                "raw_text": "pago pendiente",
                "detail_text": "pago pendiente",
            }, db_path=db)

            snapshot = operations_snapshot(db)
            opportunity = snapshot["top_opportunities"][0]
            self.assertEqual(opportunity["id"], imported["case"]["id"])
            self.assertEqual(opportunity["commercial_stage"], "RESEARCHED")
            self.assertGreater(opportunity["opportunity_score"], 0)
            self.assertTrue(opportunity["next_commercial_move"])
            self.assertTrue(opportunity["opportunity_reasons"])


if __name__ == "__main__":
    unittest.main()
