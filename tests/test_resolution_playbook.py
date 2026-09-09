import unittest

from casehunter.resolution_playbook import build_playbook, get_playbook, list_playbooks


class ResolutionPlaybookTests(unittest.TestCase):
    def test_document_missing_has_operational_steps(self):
        playbook = get_playbook("DOCUMENT_MISSING")
        self.assertEqual(playbook.blocker, "DOCUMENT_MISSING")
        self.assertGreaterEqual(len(playbook.steps), 5)
        self.assertTrue(any(step.code == "SUBMIT_MISSING_DOCUMENT" for step in playbook.steps))
        self.assertTrue(any("expediente" in text.lower() for text in playbook.closure_criteria))

    def test_retention_does_not_claim_recoverable_money(self):
        playbook = get_playbook("RETENTION_RELEASE_PENDING")
        text = " ".join(playbook.escalation + (playbook.caution,)).lower()
        self.assertIn("no", text)
        self.assertIn("dinero recuperable", text)

    def test_unknown_uses_confirmation_route(self):
        playbook = get_playbook("NOT_A_REAL_BLOCKER")
        self.assertEqual(playbook.blocker, "UNKNOWN_BLOCKER")
        self.assertTrue(any(step.code == "IDENTIFY_REAL_BLOCKER" for step in playbook.steps))

    def test_runtime_recommends_action_required_for_missing_document(self):
        runtime = build_playbook(
            "DOCUMENT_MISSING",
            ["LIQUIDATION_PENDING"],
            [{"required": 1, "status": "MISSING"}],
            [{"status": "TODO", "action_type": "SUBMIT_MISSING_DOCUMENT", "title": "Enviar documento", "due_date": "2026-09-10", "responsible": "Proveedor"}],
        )
        self.assertEqual(runtime["recommended_status"], "ACTION_REQUIRED")
        self.assertEqual(runtime["next_step"]["action_type"], "SUBMIT_MISSING_DOCUMENT")
        self.assertFalse(runtime["ready_for_closure_review"])

    def test_catalog_contains_core_playbooks(self):
        keys = {row["blocker"] for row in list_playbooks()}
        self.assertTrue({"DOCUMENT_MISSING", "LIQUIDATION_PENDING", "PAYMENT_PENDING", "RETENTION_RELEASE_PENDING", "GUARANTEE_RELEASE_PENDING"}.issubset(keys))


if __name__ == "__main__":
    unittest.main()
