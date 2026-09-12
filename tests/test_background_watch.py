import unittest
from unittest.mock import patch

from casehunter import reply_monitor


class BackgroundWatchTests(unittest.TestCase):
    def test_reply_background_intelligence_uses_bounded_watcher(self):
        with patch(
            "casehunter.reply_monitor.run_bounded_active_watches",
            return_value={"active_cases": 1, "checked": 1, "errors": 0},
        ) as watcher, patch(
            "casehunter.reply_monitor.refresh_due_pilot_portfolios",
            return_value={"refreshed": 0},
        ), patch(
            "casehunter.reply_monitor.refresh_active_pilot_recommendations",
            return_value={"refreshed": 0},
        ):
            result = reply_monitor._run_background_case_intelligence("db-path")

        watcher.assert_called_once_with(
            db_path="db-path",
            source_limit_per_case=reply_monitor.WATCH_SOURCES_PER_CASE,
            max_sources_per_case=reply_monitor.MAX_WATCH_SOURCES_PER_CASE,
        )
        self.assertEqual(result["public_watch"]["errors"], 0)


if __name__ == "__main__":
    unittest.main()
