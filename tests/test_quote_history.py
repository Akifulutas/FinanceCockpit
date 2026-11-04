import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "Yatirim-Masasi/scripts/import_quote_text.py"
spec = importlib.util.spec_from_file_location("quote_import", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class QuoteHistoryTests(unittest.TestCase):
    def text(self, flag="N/A", stamp="2026-10-09T08:51:06.276Z"):
        return f'''TICKER ISIN BID ASK MID SPREAD SPREAD% OUTDATED QUOTE UTC
GRID IE000J80JTL1 56.12 EUR 56.17 EUR 56.145 EUR 0.0500 0.089% {flag} {stamp}
Snapshot UTC: 2026-10-09 08:52:04 UTC'''

    def test_false_and_unknown_are_distinct(self):
        unknown = module.parse_quote_text(self.text())[0]
        confirmed_false = module.parse_quote_text(self.text("false"))[0]
        self.assertIsNone(unknown["quote_is_outdated"])
        self.assertIs(confirmed_false["quote_is_outdated"], False)

    def test_quote_age_uses_each_quote_not_snapshot_label(self):
        record = module.parse_quote_text(self.text())[0]
        self.assertAlmostEqual(record["quote_age_seconds"], 57.724)
        self.assertAlmostEqual(record["spread_pct_of_mid"], 0.05/56.145*100)
        self.assertIsNone(record["exchange"])
        self.assertFalse(record["ownership_confirmed"])

    def test_future_quote_cannot_be_freshened_by_snapshot(self):
        with self.assertRaises(ValueError):
            module.parse_quote_text(self.text(stamp="2026-10-09T09:00:00Z"))


if __name__ == "__main__":
    unittest.main()
