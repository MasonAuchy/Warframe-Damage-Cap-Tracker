import json
import tempfile
import unittest
from pathlib import Path

from tracker_core import format_damage_value, load_saved_state, parse_damage_line, save_state


class DashboardHelperTests(unittest.TestCase):
    def test_format_damage_value_scales_large_numbers(self):
        self.assertEqual(format_damage_value(1_000), "1000")
        self.assertEqual(format_damage_value(1_000_000), "1.0 Million")
        self.assertEqual(format_damage_value(1_000_000_000), "1.0 Billion")

    def test_parse_damage_line_extracts_value(self):
        parsed = parse_damage_line("Damage too high: 10,389,241,856")
        self.assertEqual(parsed, (10_389_241_856, "10,389,241,856"))
        self.assertIsNone(parse_damage_line("something else"))

    def test_save_and_load_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "savelog.json"
            state = {
                "damage_history": [0, 42, 99],
                "max_hit": 99,
                "hit_count": 2,
                "all_hits": 141,
                "hit_events": [
                    {"timestamp": "12:34:56", "display_timestamp": "05/04 12:34", "value": 42, "raw_value": "42"},
                    {"timestamp": "12:35:01", "display_timestamp": "05/04 12:35", "value": 99, "raw_value": "99"},
                ],
                "session_started_at": "2026-05-04T10:05:00",
            }
            save_state(path, state)
            loaded = load_saved_state(path)
            self.assertEqual(loaded["damage_history"], [0, 42, 99])
            self.assertEqual(loaded["max_hit"], 99)
            self.assertEqual(loaded["hit_count"], 2)
            self.assertEqual(loaded["all_hits"], 141)
            self.assertEqual(loaded["hit_events"], state["hit_events"])
            self.assertEqual(loaded["session_started_at"], state["session_started_at"])

    def test_load_saved_state_supports_legacy_count_field(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "savelog.json"
            path.write_text(json.dumps({"total_hits_above_cap": 4, "all_hits": 100, "max_hit": 25, "damage_history": [0, 25]}))
            loaded = load_saved_state(path)
            self.assertEqual(loaded["hit_count"], 3)
            self.assertEqual(loaded["total_hits_above_cap"], 4)
            self.assertEqual([event["value"] for event in loaded["hit_events"]], [25])


if __name__ == "__main__":
    unittest.main()
