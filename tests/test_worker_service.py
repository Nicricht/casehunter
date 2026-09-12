import unittest
from unittest.mock import patch

from casehunter import worker_service


class WorkerServiceTests(unittest.TestCase):
    @patch("casehunter.worker_service.backend_name", return_value="postgresql")
    @patch("casehunter.worker_service._database_ok", return_value=True)
    def test_health_reports_database_and_schedule(self, _mocked_db, _mocked_backend):
        worker_service.app.state.last_run = {"ok": True, "run_id": 7}
        result = worker_service.healthz()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["database_backend"], "postgresql")
        self.assertTrue(result["database_ok"])
        self.assertGreaterEqual(result["interval_minutes"], 60)
        self.assertEqual(result["last_run"]["run_id"], 7)


if __name__ == "__main__":
    unittest.main()
