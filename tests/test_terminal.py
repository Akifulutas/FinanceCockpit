"""Regressions for missing financial inputs, dated quotes and offline reporting."""
import copy
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(os.environ.get("ETF_TEST_SCRIPTS", ROOT / ".agents/skills/portfolio-intelligence/scripts"))
sys.path.insert(0, str(SCRIPTS))
from engine import run_all_engines
from fetcher import fetch_market_data, summarize_bars
from render_html import render_document, safe_url
from render_markdown import render_report

NOW = datetime(2026, 10, 23, 18, tzinfo=timezone.utc)


def quote(price=100):
    return {
        "price": price, "bar_date": "2026-10-22", "currency": "USD",
        "exchange_timezone": "America/New_York", "retrieved_at": "2026-10-23T17:00:00+00:00",
        "changes": {"1d": 1, "5d": 2, "mtd": None, "ytd": None},
        "change_unit": "%", "source": "fixture", "source_url": "https://example.org/price",
    }


class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        veri_dir = self.root / "Yatirim-Masasi/veri"
        veri_dir.mkdir(parents=True, exist_ok=True)
        (veri_dir / "ayarlar.json").write_text(json.dumps({
            "working_assumptions": {"timezone": "Europe/Berlin", "report_currency": "EUR"},
            "portfolio_context": {"displayed_total_eur": 10000.00, "registered_on": "2026-10-23", "observed_at": "2026-10-23"}
        }))
        (veri_dir / "izleme-listesi.csv").write_text(
            "isin,theme,source_url\n"
            "IE00BKM4GZ66,Emerging Markets,https://www.ishares.com/uk/individual/en/products/264659/ishares-msci-emerging-markets-imi-ucits-etf\n"
            "IE00BP3QZ825,World Momentum,https://www.ishares.com/uk/individual/en/products/270051/ishares-msci-world-momentum-factor-ucits-etf\n"
            "IE00BP3QZB59,World Value,https://www.ishares.com/uk/individual/en/products/270048/ishares-msci-world-value-factor-ucits-etf\n"
            "IE00B3YLTY66,All Country World IMI,https://www.ssga.com/library-content/products/factsheets/etfs/emea/factsheet-emea-en_gb-spyi-gy.pdf\n"
        )
        (veri_dir / "portfoy.csv").write_text(
            "isin,fund_name,base_currency,market_value_base,ticker,exchange,quantity,price\n"
            "IE00BKM4GZ66,iShares Core MSCI Emerging Markets IMI (Acc),EUR,2500,,,,\n"
            "IE00BP3QZ825,iShares Edge MSCI World Momentum Factor (Acc),EUR,2500,,,,\n"
            "IE00BP3QZB59,iShares Edge MSCI World Value Factor (Acc),EUR,1500,,,,\n"
            "IE00B3YLTY66,State Street SPDR MSCI All Country World Investable Market (Acc),EUR,3500,,,,\n"
        )
        (veri_dir / "dogrulanmis-fon-bilgileri.json").write_text(json.dumps({
            "schema_version": 1,
            "funds": [
                {"isin": "IE00B3YLTY66", "legal_name": "SPDR MSCI ACWI IMI UCITS ETF", "ter_percent": 0.17, "hedged": False, "base_currency": "USD", "distribution_policy": "Birikimli (Accumulating)", "source_url": "https://www.ssga.com/spyi"},
                {"isin": "IE00BKM4GZ66", "legal_name": "iShares Core MSCI EM IMI UCITS ETF", "ter_percent": 0.18, "hedged": False, "base_currency": "USD", "distribution_policy": "Birikimli (Accumulating)", "source_url": "https://www.ishares.com/emim"},
                {"isin": "IE00BP3QZ825", "legal_name": "iShares Edge MSCI World Momentum Factor UCITS ETF", "ter_percent": 0.25, "hedged": False, "base_currency": "USD", "distribution_policy": "Birikimli (Accumulating)", "source_url": "https://www.ishares.com/iwmo"},
                {"isin": "IE00BP3QZB59", "legal_name": "iShares Edge MSCI World Value Factor UCITS ETF", "ter_percent": 0.25, "hedged": False, "base_currency": "USD", "distribution_policy": "Birikimli (Accumulating)", "source_url": "https://www.ishares.com/iwvl"}
            ]
        }))
        (self.root / "data").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def cache(self, value):
        (self.root / "data/market_cache.json").write_text(json.dumps(value))

    def report(self):
        return run_all_engines(self.root, now=NOW)

    def test_unknown_inputs_never_make_performance(self):
        data = self.report()
        p = data["portfolio"]
        self.assertEqual(len(p["positions"]), 4)
        self.assertEqual(p["snapshot_total"], 10000.00)
        self.assertEqual(p["visible_sum"], 10000)
        self.assertEqual(p["rounding_difference"], 0.0)
        self.assertAlmostEqual(sum(x["snapshot_weight"] for x in p["positions"]), 100)
        for key in ("current_total", "daily_return", "monthly_return", "ytd_return", "cash", "cost_basis"):
            self.assertIsNone(p[key])
        self.assertIn("IE00BP3QZ825", [pos["isin"] for pos in p["positions"]])
        for pos in p["positions"]:
            for key in ("ticker", "exchange", "quantity", "price"):
                self.assertEqual(pos[key], "")

    def test_legacy_cache_cannot_be_rebranded_as_live(self):
        self.cache({"timestamp": "2026-10-23 18:58:16", "symbols": {"^GSPC": {"price": 999}}})
        data = self.report()
        self.assertTrue(data["warnings"])
        self.assertTrue(all(x["quote"] is None for x in data["market"]))

    def test_foreign_currency_snapshot_needs_conversion(self):
        path = self.root / "Yatirim-Masasi/veri/portfoy.csv"
        path.write_text(path.read_text().replace(",EUR,2500,", ",USD,2500,"))
        with self.assertRaises(ValueError):
            self.report()

    def test_missing_value_cannot_renormalize_remaining_holdings(self):
        path = self.root / "Yatirim-Masasi/veri/portfoy.csv"
        path.write_text(path.read_text().replace(",EUR,2500,", ",EUR,,"))
        p = self.report()["portfolio"]
        self.assertIsNone(p["visible_sum"])
        self.assertTrue(all(x["snapshot_weight"] is None for x in p["positions"]))

    def test_five_sessions_use_six_prices(self):
        bars = [{"date": f"2026-10-{12+i:02d}", "close": 100+i} for i in range(6)]
        result = summarize_bars(bars, "index")
        self.assertAlmostEqual(result["changes"]["5d"], 5)
        self.assertEqual(result["period_starts"]["5d"], "2026-10-12")
        self.assertIsNone(summarize_bars(bars[:-1], "index")["changes"]["5d"])

    def test_mtd_ytd_start_at_prior_close(self):
        result = summarize_bars([
            {"date": "2025-12-31", "close": 100},
            {"date": "2026-01-02", "close": 110},
            {"date": "2026-09-30", "close": 115},
            {"date": "2026-10-22", "close": 120},
        ], "index")
        self.assertAlmostEqual(result["changes"]["ytd"], 20)
        self.assertAlmostEqual(result["changes"]["mtd"], 100 * 5 / 115)
        self.assertEqual(result["period_starts"]["ytd"], "2025-12-31")

    def test_truncated_series_does_not_create_ytd(self):
        result = summarize_bars([{"date": "2026-01-02", "close": 100},
                                 {"date": "2026-01-05", "close": 110}], "index")
        self.assertIsNone(result["changes"]["ytd"])
        self.assertIsNone(result["changes"]["mtd"])

    def test_yields_use_basis_points_not_percent_return(self):
        result = summarize_bars([{"date": "2026-10-21", "close": 4},
                                 {"date": "2026-10-22", "close": 4.1}], "yield")
        self.assertAlmostEqual(result["changes"]["1d"], 10)
        self.assertEqual(result["change_unit"], "bp")

    def test_invalid_series_cannot_become_zero_or_healthy(self):
        with self.assertRaises(ValueError):
            summarize_bars([{"date": "2026-10-21", "close": 100},
                            {"date": "2026-10-22", "close": float("nan")}], "index")

    def test_failed_fetch_preserves_price_and_marks_failure(self):
        original = quote()
        self.cache({"schema_version": 2, "symbols": {"^GSPC": original}})
        def fail(*args):
            raise TimeoutError("offline")
        result = fetch_market_data(root=self.root, loader=fail, now=NOW)
        self.assertEqual(result["success"], 0)
        saved = json.loads((self.root / "data/market_cache.json").read_text())
        self.assertEqual(saved["symbols"]["^GSPC"], original)
        item = self.report()["market"][0]
        self.assertEqual(item["state"], "Eski kayıt")
        self.assertIn("offline", item["error"])

    def test_partial_fetch_does_not_claim_full_success(self):
        def load(symbol, spec, now):
            if symbol == "^GSPC":
                return quote()
            raise TimeoutError("unavailable")
        result = fetch_market_data(root=self.root, loader=load, now=NOW)
        self.assertEqual((result["success"], result["requested"]), (1, 6))
        self.assertEqual(sum(q["quote"] is not None for q in self.report()["market"]), 1)

    def test_bad_new_record_cannot_replace_good_price(self):
        self.cache({"schema_version": 2, "symbols": {"^GSPC": quote()}})
        bad = quote(999)
        bad["bar_date"] = "2026-10-23"
        fetch_market_data(root=self.root, loader=lambda *args: bad, now=NOW)
        self.assertEqual(self.report()["market"][0]["quote"]["price"], 100)

    def test_future_and_naive_quotes_are_unavailable(self):
        for field, value in (("bar_date", "2026-10-23"), ("retrieved_at", "2026-10-23T19:00:00+00:00"),
                             ("retrieved_at", "2026-10-23T17:00:00")):
            with self.subTest(field=field, value=value):
                bad = quote()
                bad[field] = value
                self.cache({"schema_version": 2, "symbols": {"^GSPC": bad}})
                self.assertIsNone(self.report()["market"][0]["quote"])

    def test_stale_download_cannot_look_current(self):
        old = quote()
        old["retrieved_at"] = "2026-10-20T17:00:00+00:00"
        self.cache({"schema_version": 2, "symbols": {"^GSPC": old}})
        self.assertEqual(self.report()["market"][0]["state"], "Eski kayıt")

    def test_corrupt_cache_not_overwritten(self):
        path = self.root / "data/market_cache.json"
        path.write_text("{broken")
        with self.assertRaises(ValueError):
            fetch_market_data(root=self.root, loader=lambda *args: quote(), now=NOW)
        self.assertEqual(path.read_text(), "{broken")

    def test_html_escapes_external_text_and_drops_active_urls(self):
        data = self.report()
        data["portfolio"]["positions"][0]["fund_name"] = '<script>alert("x")</script>'
        data["portfolio"]["positions"][0]["source_url"] = "javascript:alert(1)"
        document = render_document(data)
        self.assertNotIn('<script>alert("x")</script>', document)
        self.assertIn("&lt;script&gt;", document)
        self.assertNotIn('href="javascript:', document)
        self.assertEqual(safe_url("javascript:alert(1)"), "#")

    def test_offline_report_works_without_yfinance_import(self):
        original = sys.modules.get("yfinance", "absent")
        sys.modules["yfinance"] = None
        try:
            self.assertIn("10.000,00", render_report(data=self.report()))
        finally:
            if original == "absent":
                sys.modules.pop("yfinance", None)
            else:
                sys.modules["yfinance"] = original

    def test_cli_scope_and_invalid_commands_fail(self):
        for command in ("option", "setups", "unknown-command"):
            result = subprocess.run([sys.executable, str(SCRIPTS / "cli.py"), command,
                                     "--workspace", str(self.root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")

    def test_open_regenerates_old_report_without_browser(self):
        reports = self.root / "reports"
        reports.mkdir()
        (reports / "index.html").write_text("old")
        result = subprocess.run([sys.executable, str(SCRIPTS / "cli.py"), "open", "--no-open",
                                 "--workspace", str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual((reports / "index.html").read_text(), "old")

    def test_verified_fund_records_loaded_and_attributes_validated(self):
        data = self.report()
        verified = {f["isin"]: f for f in data["verified_funds"]}
        self.assertEqual(len(verified), 4)
        self.assertIn("IE00BP3QZ825", verified)
        self.assertIn("IE00BP3QZB59", verified)
        self.assertIn("IE00B3YLTY66", verified)
        self.assertIn("IE00BKM4GZ66", verified)
        self.assertEqual(verified["IE00B3YLTY66"]["ter_percent"], 0.17)
        self.assertEqual(verified["IE00BKM4GZ66"]["ter_percent"], 0.18)
        self.assertEqual(verified["IE00BP3QZ825"]["ter_percent"], 0.25)
        self.assertEqual(verified["IE00BP3QZB59"]["ter_percent"], 0.25)
        for f in verified.values():
            self.assertFalse(f["hedged"])
            self.assertEqual(f["base_currency"], "USD")
            self.assertIn("Birikimli", f["distribution_policy"])

    def test_research_record_state_and_warning_handling(self):
        rapor_dir = self.root / "Yatirim-Masasi/raporlar"
        rapor_dir.mkdir(parents=True)
        current_research = {
            "schema_version": 1, "date": "2026-10-23",
            "macro_summary": {"headline": "Büyüme Sürüyor", "facts": ["PMI 57.6"]},
            "funds": [{"isin": "IE00B3YLTY66", "fund_name": "SPDR", "what_changed": "PMI",
                       "economic_transmission": "Global", "counter_evidence": "Enflasyon",
                       "next_check": "Fed", "sources": [{"title": "Doc", "url": "https://example.com", "date": "2026-10-23"}]}]
        }
        (rapor_dir / "2026-10-23-etf-arastirmasi.json").write_text(json.dumps(current_research))
        data = self.report()
        self.assertEqual(data["research"]["state"], "Güncel araştırma kaydı")
        self.assertEqual(data["research"]["date"], "2026-10-23")
        self.assertIn("SPDR", render_document(data))
        self.assertIn("PMI 57.6", render_report(data=data))

        # Stale research triggers warning and state update
        stale_research = copy.deepcopy(current_research)
        stale_research["date"] = "2026-10-20"
        (rapor_dir / "2026-10-23-etf-arastirmasi.json").write_text(json.dumps(stale_research))
        data = self.report()
        self.assertIn("Önceki tarihli araştırma kaydı", data["research"]["state"])
        self.assertTrue(any("ETF araştırması bugüne ait değil" in w for w in data["warnings"]))

        # Future research is rejected
        future_research = copy.deepcopy(current_research)
        future_research["date"] = "2026-10-25"
        (rapor_dir / "2026-10-23-etf-arastirmasi.json").write_text(json.dumps(future_research))
        data = self.report()
        self.assertEqual(data["research"]["state"], "Geçersiz araştırma tarihi")
        self.assertIsNone(data["research"]["data"])

        # Corrupt research file is handled safely
        (rapor_dir / "2026-10-23-etf-arastirmasi.json").write_text("{broken")
        data = self.report()
        self.assertEqual(data["research"]["state"], "Araştırma kaydı okunamadı")

    def test_cli_research_command_succeeds(self):
        rapor_dir = self.root / "Yatirim-Masasi/raporlar"
        rapor_dir.mkdir(parents=True, exist_ok=True)
        sample = {
            "schema_version": 1, "date": "2026-10-23",
            "macro_summary": {"headline": "Faiz Beklentileri", "facts": ["Fed %4"]},
            "funds": []
        }
        (rapor_dir / "2026-10-23-etf-arastirmasi.json").write_text(json.dumps(sample))
        result = subprocess.run([sys.executable, str(SCRIPTS / "cli.py"), "research",
                                 "--workspace", str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Günlük ETF Araştırması", result.stdout)

    def test_missing_catalog_does_not_invent_fund_attributes(self):
        (self.root / "Yatirim-Masasi/veri/dogrulanmis-fon-bilgileri.json").unlink()
        data = self.report()
        for pos in data["portfolio"]["positions"]:
            self.assertIsNone(pos["base_currency_verified"])
            self.assertIsNone(pos["hedged_verified"])
            self.assertIsNone(pos["distribution_policy"])
        self.assertNotIn("Hedge yok", render_document(data))
        self.assertTrue(any("Fon bilgi" in w for w in data["warnings"]))

    def test_corrupt_catalog_is_explicitly_unavailable(self):
        path = self.root / "Yatirim-Masasi/veri/dogrulanmis-fon-bilgileri.json"
        for value in ("{broken", json.dumps({"schema_version": 1, "funds": [None]})):
            path.write_text(value)
            data = self.report()
            self.assertEqual(data["verified_funds"], [])
            self.assertTrue(any("Fon bilgi kaydı doğrulanamadı" in w for w in data["warnings"]))

    def test_invalid_fund_boolean_does_not_become_false(self):
        path = self.root / "Yatirim-Masasi/veri/dogrulanmis-fon-bilgileri.json"
        content = json.loads(path.read_text())
        content["funds"][0]["hedged"] = "false"
        path.write_text(json.dumps(content))
        self.assertEqual(self.report()["verified_funds"], [])

    def test_partial_catalog_keeps_missing_currency_unknown(self):
        path = self.root / "Yatirim-Masasi/veri/dogrulanmis-fon-bilgileri.json"
        content = json.loads(path.read_text())
        for fund in content["funds"]:
            fund.pop("base_currency", None)
        path.write_text(json.dumps(content))
        self.assertTrue(all(pos["base_currency_verified"] is None for pos in self.report()["portfolio"]["positions"]))

    def test_valid_json_wrong_research_shape_does_not_crash_rendering(self):
        directory = self.root / "Yatirim-Masasi/raporlar"
        directory.mkdir()
        path = directory / "2026-10-23-etf-arastirmasi.json"
        for funds in ([None], None, "bad"):
            path.write_text(json.dumps({"schema_version": 1, "date": "2026-10-23", "funds": funds}))
            data = self.report()
            self.assertIsNone(data["research"]["data"])
            self.assertIn("Günlük ETF Araştırması", render_report(data=data))
            self.assertIn("ETF Yatırım Masası", render_document(data))

    def test_research_future_generation_time_rejected_even_on_today(self):
        directory = self.root / "Yatirim-Masasi/raporlar"
        directory.mkdir()
        (directory / "2026-10-23-etf-arastirmasi.json").write_text(json.dumps({
            "schema_version": 1, "date": "2026-10-23", "generated_at": "2026-10-23T20:00:00+00:00", "funds": []}))
        self.assertIsNone(self.report()["research"]["data"])

    def test_research_invalid_source_url_is_rejected(self):
        directory = self.root / "Yatirim-Masasi/raporlar"
        directory.mkdir()
        (directory / "2026-10-23-etf-arastirmasi.json").write_text(json.dumps({
            "schema_version": 1, "date": "2026-10-23", "macro_summary": {"sources": [{"url": "javascript:alert(1)"}]}, "funds": []}))
        self.assertIsNone(self.report()["research"]["data"])

    def test_research_uses_content_date_and_preserves_valid_fallback(self):
        directory = self.root / "Yatirim-Masasi/raporlar"
        directory.mkdir()
        for name, day in (("a-etf-arastirmasi.json", "2026-10-23"), ("z-etf-arastirmasi.json", "2026-10-20")):
            (directory / name).write_text(json.dumps({"schema_version": 1, "date": day, "funds": []}))
        self.assertEqual(self.report()["research"]["date"], "2026-10-23")
        (directory / "zz-etf-arastirmasi.json").write_text("{broken")
        data = self.report()
        self.assertEqual(data["research"]["date"], "2026-10-23")
        self.assertTrue(any("zz-etf" in w for w in data["warnings"]))

    def test_today_does_not_imply_content_verification(self):
        directory = self.root / "Yatirim-Masasi/raporlar"
        directory.mkdir()
        path = directory / "2026-10-23-etf-arastirmasi.json"
        path.write_text(json.dumps({"schema_version": 1, "date": "2026-10-23", "funds": []}))
        data = self.report()
        self.assertEqual(data["research"]["verification_status"], "unreviewed")
        self.assertIn("İçerik doğrulaması kayıtlı değil", render_report(data=data))


if __name__ == "__main__":
    unittest.main()
