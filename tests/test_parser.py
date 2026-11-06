"""Tests of the pure parser, runnable with `python -m unittest` (no Home Assistant needed)."""

from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "cga_parser", ROOT / "custom_components" / "technicolor_cga" / "parser.py"
)
parser = importlib.util.module_from_spec(_spec)
sys.modules["cga_parser"] = parser
_spec.loader.exec_module(parser)

FIXTURE = json.loads((Path(__file__).parent / "fixture_cga437a_modem.json").read_text())
TZ = ZoneInfo("Europe/Brussels")


class NumberTest(unittest.TestCase):
    def test_units_and_missing(self):
        self.assertEqual(parser.number("5.6 dBmV"), 5.6)
        self.assertEqual(parser.number("-3 dBmV"), -3.0)
        self.assertEqual(parser.number("14009"), 14009.0)
        self.assertIsNone(parser.number("NA"))
        self.assertIsNone(parser.number(""))
        self.assertIsNone(parser.number(None))


class LogTest(unittest.TestCase):
    def setUp(self):
        self.log = parser.parse_log(FIXTURE["LogTbl"], TZ)

    def test_every_line_has_a_unique_signature(self):
        self.assertEqual(len(self.log), 31)
        self.assertEqual(len({e.signature for e in self.log}), 31)

    def test_categories_of_a_real_cga437a_log(self):
        counts = Counter(e.category for e in self.log)
        self.assertEqual(counts["disconnection"], 4)
        self.assertEqual(counts["reboot"], 2)
        self.assertEqual(counts["t3_timeout"], 4)
        self.assertEqual(counts["sync_loss"], 3)
        self.assertGreaterEqual(counts["dhcp_failure"], 1)

    def test_unset_clock_gives_no_time(self):
        first = self.log[0]
        self.assertIsNone(first.time)
        self.assertEqual(first.level_name, "critical")

    def test_time_is_local_and_mac_noise_is_dropped(self):
        last = self.log[-1]
        self.assertEqual(last.time.tzinfo, TZ)
        self.assertEqual(last.text, "CM State is operational")

    def test_garbage_rows_are_ignored(self):
        self.assertEqual(parser.parse_log([None, "x", {"level": "?"}], TZ)[0].level, None)
        self.assertEqual(parser.parse_log("NA", TZ), [])


class SummaryTest(unittest.TestCase):
    def test_summary_of_a_real_cga437a(self):
        summary = parser.summarize_channels(FIXTURE)
        self.assertEqual(summary["ds_locked"], 17)
        self.assertEqual(summary["us_locked"], 5)
        self.assertEqual(summary["ds_power"]["min"], 5.6)
        self.assertAlmostEqual(summary["ofdm_snr"]["avg"], 43.37)
        self.assertEqual(summary["uncorrectable"], 0)
        self.assertGreater(summary["corrected"], 0)

    def test_empty_modem(self):
        summary = parser.summarize_channels({})
        self.assertIsNone(summary["ds_power"]["avg"])
        self.assertEqual(summary["ds_locked"], 0)
        self.assertIsNone(summary["corrected"])


if __name__ == "__main__":
    unittest.main()


class TimeoutSpellingTest(unittest.TestCase):
    """The gateway writes "time-out", "timeout" and "time out"."""

    def test_spellings(self):
        categorize = parser.categorize
        CATEGORY_T3_TIMEOUT, CATEGORY_T4_TIMEOUT = parser.CATEGORY_T3_TIMEOUT, parser.CATEGORY_T4_TIMEOUT
        text = "Received Response to Broadcast Maintenance Request, But no Unicast Maintenance opportunities received - T4 time out"
        self.assertEqual(categorize(text), CATEGORY_T4_TIMEOUT)
        self.assertEqual(categorize("No Ranging Response received - T3 time-out"), CATEGORY_T3_TIMEOUT)
        self.assertEqual(categorize("No Ranging Response received - T3 timeout"), CATEGORY_T3_TIMEOUT)
