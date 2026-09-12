import unittest
from unittest.mock import patch

from casehunter.production_webapp import database_health


class _FakeCursor:
    def fetchone(self):
        return {"ok": 1}


class _FakeConnection:
    def __init__(self):
        self.closed = False

    def execute(self, sql):
        if sql != "SELECT 1 AS ok":
            raise AssertionError(sql)
        return _FakeCursor()

    def close(self):
        self.closed = True


class ProductionHealthTests(unittest.TestCase):
    @patch("casehunter.production_webapp.backend_name", return_value="postgresql")
    @patch("casehunter.production_webapp.connect")
    def test_database_health_reports_backend_and_closes_connection(self, mocked_connect, _mocked_backend):
        connection = _FakeConnection()
        mocked_connect.return_value = connection

        result = database_health()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["database_backend"], "postgresql")
        self.assertTrue(result["database_ok"])
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
