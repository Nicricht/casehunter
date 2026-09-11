import tempfile
import unittest
from pathlib import Path

from casehunter.database import init_db, transaction, utc_now
from casehunter.pilot_metrics import list_pilot_metrics, pilot_funnel, start_pilot
from casehunter.repository import add_timeline_event, import_candidate, update_case_status


def candidate(name="ALEMBIC PHARMACEUTICALS SPA"):
    return {
        "audience_id": "PILOT-DEMO-1",
        "date": "2026-09-11",
        "detail_url": "https://example.test/pilot",
        "source_url": "https://example.test/list",
        "amounts_clp": [5178271],
        "problems": [],
        "confidence": {"score": 1.0, "label": "HIGH"},
        "represented_entities": [name],
        "works_for": [],
        "raw_text": "Caso público de prueba para piloto",
    }


class PilotMetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "pilot.db"
        init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def _case_with_reply(self):
        case = import_candidate(candidate(), db_path=self.db)["case"]
        now = utc_now()
        with transaction(self.db) as conn:
            cur = conn.execute(
                """INSERT INTO outreach_messages(case_id,recipient_email,subject,body,status,dedupe_key,sent_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (case["id"], "cobranzas@example.test", "Caso", "Hola", "REPLIED", "pilot-demo-outreach", now, now, now),
            )
            outreach_id = cur.lastrowid
            conn.execute(
                """INSERT INTO outreach_replies(outreach_id,case_id,provider_message_id,sender_email,classification,received_at,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (outreach_id, case["id"], "reply-pilot-demo", "cobranzas@example.test", "STILL_PENDING", now, now),
            )
        return case

    def test_start_pilot_moves_case_to_active_pilot(self):
        case = self._case_with_reply()
        before = list_pilot_metrics(db_path=self.db)[0]
        self.assertEqual(before["stage"], "PROBLEM_CONFIRMED")

        started = start_pilot(case["id"], "Empresa aceptó seguimiento del caso", self.db)
        self.assertEqual(started["stage"], "ACTIVE_PILOT")
        self.assertGreaterEqual(started["pilot_score"], 75)
        self.assertEqual(started["tracked_amount_clp"], 5178271)
        self.assertEqual(started["public_changes"], 0)
        self.assertFalse(started["has_measurable_result"])

        again = start_pilot(case["id"], db_path=self.db)
        self.assertEqual(again["stage"], "ACTIVE_PILOT")
        with transaction(self.db) as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM timeline_events WHERE case_id=? AND event_type='PILOT_STARTED'",
                (case["id"],),
            ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_public_change_becomes_measurable_pilot_result(self):
        case = self._case_with_reply()
        start_pilot(case["id"], db_path=self.db)
        add_timeline_event(
            case["id"],
            title="Cambio público detectado: PAYMENT_COMMITMENT",
            details="Compromiso de pago para el 20 de septiembre",
            event_type="PUBLIC_WATCH_CHANGE",
            event_date="2026-09-12",
            source_url="https://example.test/change",
            db_path=self.db,
        )
        row = list_pilot_metrics(db_path=self.db)[0]
        self.assertEqual(row["public_changes"], 1)
        self.assertTrue(row["has_measurable_result"])
        funnel = pilot_funnel(db_path=self.db)
        self.assertEqual(funnel["tracked_amount_clp_active_pilots"], 5178271)
        self.assertEqual(funnel["public_changes_active_pilots"], 1)

    def test_resolved_case_is_final_stage(self):
        case = self._case_with_reply()
        start_pilot(case["id"], db_path=self.db)
        update_case_status(case["id"], "RESOLVED", self.db)
        row = list_pilot_metrics(db_path=self.db)[0]
        self.assertEqual(row["stage"], "RESOLVED")
        self.assertTrue(row["has_measurable_result"])
        funnel = pilot_funnel(db_path=self.db)
        self.assertEqual(funnel["resolved"], 1)


if __name__ == "__main__":
    unittest.main()
