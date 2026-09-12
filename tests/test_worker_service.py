import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from casehunter import worker_service
from casehunter.database import init_db, transaction, utc_now


class WorkerServiceTests(unittest.TestCase):
    @patch("casehunter.worker_service.backend_name", return_value="postgresql")
    @patch("casehunter.worker_service._database_ok", return_value=True)
    def test_health_reports_database_and_schedule(self, _mocked_db, _mocked_backend):
        worker_service.app.state.last_run = {"ok": True, "run_id": 7}
        response = worker_service.healthz()
        result = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["database_backend"], "postgresql")
        self.assertTrue(result["database_ok"])
        self.assertGreaterEqual(result["interval_minutes"], 60)
        self.assertEqual(result["last_run"]["run_id"], 7)

    @patch("casehunter.worker_service.backend_name", return_value="postgresql")
    @patch("casehunter.worker_service._database_ok", return_value=False)
    def test_health_fails_when_database_is_unavailable(self, _mocked_db, _mocked_backend):
        worker_service.app.state.last_run = None
        response = worker_service.healthz()
        result = json.loads(response.body)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(result["status"], "degraded")
        self.assertFalse(result["database_ok"])

    def test_interrupted_runs_are_closed_before_new_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "worker.db"
            init_db(db)
            with transaction(db) as conn:
                conn.execute(
                    "INSERT INTO automation_runs(started_at,status,source_urls) VALUES(?,'RUNNING','[]')",
                    (utc_now(),),
                )

            closed = worker_service._close_interrupted_runs(db)
            self.assertEqual(closed, 1)

            with transaction(db) as conn:
                row = conn.execute(
                    "SELECT status,finished_at,error FROM automation_runs ORDER BY id DESC LIMIT 1"
                ).fetchone()
            self.assertEqual(row["status"], "INTERRUPTED")
            self.assertIsNotNone(row["finished_at"])
            self.assertIn("worker restarted", row["error"].lower())


if __name__ == "__main__":
    unittest.main()
