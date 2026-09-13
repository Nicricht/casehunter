import tempfile
import unittest
from pathlib import Path

from casehunter.commercial_lifecycle import commercial_metrics, get_commercial_opportunity, set_commercial_status
from casehunter.database import init_db, transaction
from casehunter.pilot_proposal import generate_pilot_proposal
from casehunter.repository import get_case, import_candidate


def candidate(external_id="COMM-1", company="Comercial Piloto SpA"):
    return {
        "audience_id": external_id,
        "date": "2026-09-13",
        "detail_url": "https://www.leylobby.gob.cl/detail",
        "source_url": "https://www.leylobby.gob.cl/list",
        "safis": [],
        "amounts_clp": [80000000],
        "problems": [{"type": "PAYMENT_PENDING", "matched_patterns": ["pago pendiente"]}],
        "confidence": {"score": 0.95, "label": "HIGH"},
        "represented_entities": [company],
        "works_for": [],
        "agency": "Organismo Público",
        "contract_ref": "Contrato de prueba",
        "raw_text": "pago pendiente",
        "detail_text": "pago pendiente",
    }


class CommercialLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "commercial.db"
        init_db(self.db)
        self.case_id = import_candidate(candidate(), db_path=self.db)["case"]["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_lifecycle_tracks_pilot_and_won_value(self):
        proposed = set_commercial_status(
            self.case_id,
            "PILOT_PROPOSED",
            pilot_price_clp=0,
            monthly_price_clp=149000,
            expected_value_clp=600000,
            note="Propuesta enviada",
            db_path=self.db,
        )
        self.assertEqual(proposed["status"], "PILOT_PROPOSED")
        self.assertEqual(proposed["expected_value_clp"], 600000)

        active = set_commercial_status(self.case_id, "PILOT_ACTIVE", db_path=self.db)
        self.assertEqual(active["status"], "PILOT_ACTIVE")
        case = get_case(self.case_id, self.db)
        self.assertTrue(any(event["event_type"] == "PILOT_STARTED" for event in case["timeline"]))

        won = set_commercial_status(self.case_id, "WON", monthly_price_clp=149000, db_path=self.db)
        self.assertEqual(won["status"], "WON")
        metrics = commercial_metrics(self.db)
        self.assertEqual(metrics["won"], 1)
        self.assertEqual(metrics["won_monthly_revenue_clp"], 149000)

    def test_lost_requires_reason(self):
        with self.assertRaises(ValueError):
            set_commercial_status(self.case_id, "LOST", db_path=self.db)
        lost = set_commercial_status(self.case_id, "LOST", lost_reason="Sin presupuesto", db_path=self.db)
        self.assertEqual(lost["lost_reason"], "Sin presupuesto")
        self.assertEqual(commercial_metrics(self.db)["lost"], 1)

    def test_open_state_and_pilot_proposal_are_available_without_prior_row(self):
        commercial = get_commercial_opportunity(self.case_id, self.db)
        self.assertEqual(commercial["status"], "OPEN")
        proposal = generate_pilot_proposal(self.case_id, db_path=self.db)
        self.assertEqual(proposal["cases_limit"], 5)
        self.assertEqual(proposal["pilot_days"], 30)
        self.assertIn("Comercial Piloto SpA", proposal["title"])
        self.assertIn("Regla de evidencia", proposal["body"])

    def test_metrics_include_delivery_reply_and_qualified_conversion(self):
        with transaction(self.db) as conn:
            first = conn.execute(
                """INSERT INTO outreach_messages(
                       case_id,recipient_email,subject,body,status,dedupe_key,sent_at,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    self.case_id, "uno@example.com", "Caso", "Texto", "SENT", "dedupe-1",
                    "2026-09-13T10:00:00+00:00", "2026-09-13T10:00:00+00:00", "2026-09-13T10:00:00+00:00",
                ),
            ).lastrowid
            conn.execute(
                """INSERT INTO outreach_messages(
                       case_id,recipient_email,subject,body,status,dedupe_key,sent_at,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    self.case_id, "dos@example.com", "Caso", "Texto", "BOUNCED", "dedupe-2",
                    "2026-09-13T10:30:00+00:00", "2026-09-13T10:30:00+00:00", "2026-09-13T10:30:00+00:00",
                ),
            )
            conn.execute(
                """INSERT INTO outreach_replies(
                       outreach_id,case_id,provider_message_id,sender_email,classification,received_at,created_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    first, self.case_id, "reply-1", "uno@example.com", "REQUESTS_INFO",
                    "2026-09-13T12:00:00+00:00", "2026-09-13T12:00:00+00:00",
                ),
            )

        metrics = commercial_metrics(self.db)
        self.assertEqual(metrics["sent_attempts"], 2)
        self.assertEqual(metrics["delivery_failures"], 1)
        self.assertEqual(metrics["positive_replies"], 1)
        self.assertEqual(metrics["qualified_opportunities"], 1)
        self.assertEqual(metrics["avg_response_hours"], 2.0)


if __name__ == "__main__":
    unittest.main()
