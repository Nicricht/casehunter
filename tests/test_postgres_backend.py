import os
import unittest

from casehunter.contact_discovery import save_contacts
from casehunter.database import backend_name, init_db
from casehunter.operations import operations_snapshot
from casehunter.repository import create_company, get_company, import_candidate


POSTGRES_URL = os.getenv("CASE_HUNTER_TEST_POSTGRES_URL", "").strip()


@unittest.skipUnless(POSTGRES_URL, "PostgreSQL de integración no configurado")
class PostgresBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg

        with psycopg.connect(POSTGRES_URL, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
            conn.execute("CREATE SCHEMA public")
        init_db(POSTGRES_URL)

    def test_repository_and_operations_work_on_postgres(self):
        self.assertEqual(backend_name(POSTGRES_URL), "postgresql")

        company = create_company("PREVCONS SpA", "76.999.999-9", POSTGRES_URL)
        self.assertEqual(get_company(company["id"], POSTGRES_URL)["name"], "PREVCONS SpA")

        candidate = {
            "audience_id": "PG-INTEGRATION-1",
            "date": "2026-09-09",
            "detail_url": "https://www.leylobby.gob.cl/detail",
            "source_url": "https://www.leylobby.gob.cl/list",
            "safis": ["407848"],
            "amounts_clp": [120000000],
            "problems": [{"type": "LIQUIDATION_PENDING", "matched_patterns": ["cierre administrativo"]}],
            "confidence": {"score": 0.95, "label": "HIGH"},
            "represented_entities": ["PREVCONS SpA"],
            "works_for": [],
            "agency": "MOP",
            "contract_ref": "SAFI 407848",
            "raw_text": "cierre administrativo",
            "detail_text": "cierre administrativo",
        }
        imported = import_candidate(candidate, db_path=POSTGRES_URL)
        case_id = imported["case"]["id"]
        self.assertTrue(imported["created"])
        self.assertGreater(int(case_id), 0)

        contacts = save_contacts(
            case_id,
            [{"email": "prevcons@gmail.com", "source_url": "https://prevcons.cl/contacto", "confidence_label": "MEDIUM"}],
            POSTGRES_URL,
        )
        self.assertEqual(contacts["created"], 1)
        self.assertEqual(contacts["contacts"][0]["trust_decision"], "AUTO_SEND")

        snapshot = operations_snapshot(POSTGRES_URL)
        self.assertEqual(snapshot["kpis"]["cases_total"], 1)
        self.assertEqual(snapshot["kpis"]["contacts_auto_send_ready"], 1)


if __name__ == "__main__":
    unittest.main()
