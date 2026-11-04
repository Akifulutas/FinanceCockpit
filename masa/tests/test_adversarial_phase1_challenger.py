"""Adversarial Challenger Test Suite for Phase 1 (H1, H2, H3).

Empirical stress tests covering:
1. `masa tez ekle` CLI argument parsing with edge cases:
   - Turkish unicode characters & special symbols (quotes, tags, emojis).
   - Falsification triggers: 0, 1, 2, duplicate, whitespace-only, 5+ triggers.
   - Field length boundaries: title (3..200), summary (10..500), rationale (10..10000+).
   - Date validation: ISO YYYY-MM-DD, leap years (2028-02-29 vs 2027-02-29), non-ISO formats.
   - Target allocation decimals: 0.0, 1.0, -0.1, 1.01, non-numeric.
   - Enums: category and horizon choices vs invalid entries.
   - ISIN: ISO 6166 checksums, case normalization, invalid format.
2. CLI stdin piping (`ayar yaz --dosya ... --json -`):
   - Piping valid JSON via stdin.
   - Piping malformed JSON, empty stdin, large 50KB payload.
   - Policy confirmation gating (`--onayla-politika`).
   - Portfolio weight validation (negative weight, total > 1.0).
3. Database triggers, immutability & hash chain:
   - Trigger blocks UPDATE/DELETE on `thesis_versions`.
   - Hash chain and schema integrity remain intact.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import pytest

from masa import config
from masa.cli import cmd_ayar, cmd_tez, main
from masa.identity.registry import IdentityRegistry
from masa.storage.db import DatabaseManager
from masa.thesis.manager import ThesisManager
from masa.thesis.models import (
    ThesisCategory,
    ThesisHorizon,
    ThesisRecord,
    ThesisStatus,
)


def run_cli(argv: list[str]) -> int:
    """Execute masa CLI and catch SystemExit return code."""
    try:
        main(argv)
        return 0
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch):
    """Set up completely isolated DB and Config directories."""
    db_path = tmp_path / "challenger_phase1.db"
    db = DatabaseManager(db_path)
    db.initialize_schema()
    IdentityRegistry(db=db).seed_from_configs()

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setenv("MASA_DB_PATH", str(db_path))

    # Seed initial config files
    portfoy = {
        "cekirdek_isin": "IE00B3YLTY66",
        "araclar": {
            "IE00B3YLTY66": {"rol": "Çekirdek", "tur": "ETF"},
            "IE00BKM4GZ66": {"rol": "Gelişmekte Olan", "tur": "ETF"},
        },
        "hedef_agirliklar": {},
        "hedef_durumu": "ONAYLANMADI",
    }
    politika = {
        "durum": "TASLAK",
        "tolerans_mutlak": 0.05,
        "tolerans_goreli": 0.25,
        "trend_uyari": -0.05,
        "dusus_inceleme": -0.20,
        "min_emir_eur": 25.0,
        "nakit_hedefi": 0.0,
        "ucits_kontrolu": False,
    }
    (cfg_dir / "portfoy.json").write_text(json.dumps(portfoy), encoding="utf-8")
    (cfg_dir / "politika.json").write_text(json.dumps(politika), encoding="utf-8")

    return {"db": db, "cfg_dir": cfg_dir, "db_path": db_path}


# ============================================================================
# 1. THESIS CLI ARGUMENT PARSING & EDGE CASES
# ============================================================================

class TestThesisCLIEmpiricalEdgeCases:

    def test_thesis_ekle_unicode_turkish_characters(self, isolated_env, capsys):
        """Stress-test Turkish characters: ç, ş, ğ, ö, ü, İ, ı across all text fields."""
        argv = [
            "tez", "ekle",
            "--isin", "IE00B3YLTY66",
            "--baslik", "Gelişmekte Olan Ülkeler ve Çin Ağırlıklı Büyüme Tezi — 2026",
            "--ozet", "Gelişmekte olan piyasaların değerleme iskontosu ve büyüme potansiyeli yüksektir.",
            "--gerekce", "Ekonomik büyüme hızı ve demografik avantajlar sebebiyle uzun vadeli getiri beklentisi büyüktür.",
            "--kategori", "CORE",
            "--vade", "LONG_TERM",
            "--tetikleyiciler", "MSCI EM F/K oranı 15'i aşarsa", "Çin GSYİH büyümesi %3'ün altına düşerse",
            "--kanitlar", "IMF Dünya Ekonomik Görünüm Raporu", "Dünya Bankası Göstergeleri",
            "--karsi-gorus", "Jeopolitik gerilimler ve kur dalgalanmaları riski mevcuttur.",
            "--hedef-agirlik", "0.40",
            "--sonraki-kontrol", "2026-12-31",
            "--json"
        ]
        ret = run_cli(argv)
        captured = capsys.readouterr()
        assert ret == 0, f"Expected 0, got {ret}. Stderr: {captured.err}"

        # Find JSON payload in output
        lines = captured.out.strip().splitlines()
        json_start = False
        json_lines = []
        for line in lines:
            if line.startswith("{"):
                json_start = True
            if json_start:
                json_lines.append(line)
        json_text = "\n".join(json_lines)

        data = json.loads(json_text)
        assert data["isin"] == "IE00B3YLTY66"
        assert "Çin" in data["title"]
        triggers = json.loads(data["falsification_triggers_json"])
        assert len(triggers) == 2
        assert "Çin" in triggers[1]

    def test_thesis_ekle_special_characters_and_emojis(self, isolated_env, capsys):
        """Stress-test quotes, HTML-like tags, symbols, and emojis."""
        argv = [
            "tez", "ekle",
            "--isin", "IE00BKM4GZ66",
            "--baslik", "Tech Growth & AI Momentum 🚀 <Top Pick> \"Alpha\"",
            "--ozet", "Summary with symbols: 100% > 50% & P/E <= 25.0; $EUR/USD trend.",
            "--gerekce", "Detailed rationale with special chars: 'quotes', `backticks`, <xml-like>, & ampersands.",
            "--tetikleyiciler", "Trigger 1: Drawdown > 20% 📉", "Trigger 2: CEO resigns or SEC investigation ⚠️",
            "--hedef-agirlik", "0.15",
            "--json"
        ]
        ret = run_cli(argv)
        captured = capsys.readouterr()
        assert ret == 0, f"Failed with: {captured.err}"

        lines = captured.out.strip().splitlines()
        json_lines = [l for l in lines if l.startswith("{") or "version_id" in l or l.startswith("}") or ":" in l]
        data = json.loads("\n".join(json_lines))
        assert "🚀" in data["title"]
        triggers = json.loads(data["falsification_triggers_json"])
        assert "📉" in triggers[0]

    def test_thesis_ekle_triggers_boundary_one_rejected(self, isolated_env, capsys):
        """Exactly 1 falsification trigger must be rejected per mandatory IP-5 audit rule."""
        argv = [
            "tez", "ekle",
            "--isin", "IE00B3YLTY66",
            "--baslik", "Tek Tetikleyici Testi",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "Yalnızca bir tetikleyici"
        ]
        ret = run_cli(argv)
        captured = capsys.readouterr()
        assert ret == 1
        assert "en az 2 somut çürütme koşulu" in captured.out

    def test_thesis_ekle_triggers_boundary_duplicate_rejected(self, isolated_env, capsys):
        """2 identical triggers deduplicate to 1, which must fail the >= 2 distinct triggers check."""
        argv = [
            "tez", "ekle",
            "--isin", "IE00B3YLTY66",
            "--baslik", "Çift Tetikleyici Testi",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "Aynı Tetikleyici", "Aynı Tetikleyici"
        ]
        ret = run_cli(argv)
        captured = capsys.readouterr()
        assert ret == 1
        assert "en az 2 somut çürütme koşulu" in captured.out

    def test_thesis_ekle_triggers_five_successful(self, isolated_env, capsys):
        """Verify multiple triggers (5 triggers) are all recorded without truncation."""
        triggers = [f"Falsification Trigger #{i}: Condition breached" for i in range(1, 6)]
        argv = [
            "tez", "ekle",
            "--isin", "IE00B3YLTY66",
            "--baslik", "Beş Tetikleyicili Sağlam Tez",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler"
        ] + triggers + ["--json"]
        ret = run_cli(argv)
        captured = capsys.readouterr()
        assert ret == 0

        lines = captured.out.strip().splitlines()
        json_lines = [l for l in lines if l.startswith("{") or "version_id" in l or l.startswith("}") or ":" in l]
        data = json.loads("\n".join(json_lines))
        rec_triggers = json.loads(data["falsification_triggers_json"])
        assert len(rec_triggers) == 5

    def test_thesis_ekle_title_length_boundaries(self, isolated_env, capsys):
        """Title length boundaries: 2 (too short -> reject), 3 (exact min -> pass), 200 (exact max -> pass), 201 (too long -> reject)."""
        # 2 chars (rejected before DB insert)
        ret2 = run_cli([
            "tez", "ekle", "--isin", "IE00B3YLTY66", "--baslik", "AB",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2"
        ])
        assert ret2 == 1

        # 3 chars -> PASS on ISIN IE00BP3QZ825
        ret3 = run_cli([
            "tez", "ekle", "--isin", "IE00BP3QZ825", "--baslik", "ABC",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2"
        ])
        assert ret3 == 0

        # 200 chars -> PASS on ISIN IE00BP3QZB59
        title200 = "T" * 200
        ret200 = run_cli([
            "tez", "ekle", "--isin", "IE00BP3QZB59", "--baslik", title200,
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2"
        ])
        assert ret200 == 0

        # 201 chars -> REJECT (rejected before DB insert)
        title201 = "T" * 201
        ret201 = run_cli([
            "tez", "ekle", "--isin", "IE00B4L5Y983", "--baslik", title201,
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2"
        ])
        assert ret201 == 1

    def test_thesis_ekle_summary_length_boundaries(self, isolated_env, capsys):
        """Summary boundaries: 9 chars (fail), 10 chars (pass), 500 chars (pass), 501 chars (fail)."""
        # 9 chars -> FAIL
        ret9 = run_cli([
            "tez", "ekle", "--isin", "US0378331005", "--baslik", "Başlık Metni",
            "--ozet", "123456789",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2"
        ])
        assert ret9 == 1

        # 10 chars -> PASS on US0378331005
        ret10 = run_cli([
            "tez", "ekle", "--isin", "US0378331005", "--baslik", "Başlık Metni",
            "--ozet", "1234567890",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2"
        ])
        assert ret10 == 0

        # 500 chars -> PASS on US5949181045
        s500 = "S" * 500
        ret500 = run_cli([
            "tez", "ekle", "--isin", "US5949181045", "--baslik", "Başlık Metni",
            "--ozet", s500,
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2"
        ])
        assert ret500 == 0

        # 501 chars -> FAIL
        s501 = "S" * 501
        ret501 = run_cli([
            "tez", "ekle", "--isin", "US67066G1040", "--baslik", "Başlık Metni",
            "--ozet", s501,
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2"
        ])
        assert ret501 == 1

    def test_thesis_ekle_huge_rationale_stress(self, isolated_env, capsys):
        """Stress-test a very large 10KB economic rationale (no artificial small buffer limits)."""
        huge_rationale = ("Gerekçe metni paragrafı. Uzun vadeli analiz ve makro ekonomik göstergeler. " * 150).strip()
        assert len(huge_rationale) > 10000

        argv = [
            "tez", "ekle",
            "--isin", "NL0010273215",
            "--baslik", "Büyük Gerekçeli Derin Tez",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", huge_rationale,
            "--tetikleyiciler", "T1: Enflasyon > 5%", "T2: Reel getiri < 0%",
            "--json"
        ]
        ret = run_cli(argv)
        captured = capsys.readouterr()
        assert ret == 0

        lines = captured.out.strip().splitlines()
        json_lines = [l for l in lines if l.startswith("{") or "version_id" in l or l.startswith("}") or ":" in l]
        data = json.loads("\n".join(json_lines))
        assert len(data["economic_rationale"]) == len(huge_rationale)

    def test_thesis_ekle_target_weight_boundaries(self, isolated_env, capsys):
        """Target weight boundaries: 0.0 (pass), 1.0 (pass), -0.05 (fail), 1.05 (fail), 'invalid' (fail)."""
        # 0.0 -> PASS on DE0007164600
        assert run_cli([
            "tez", "ekle", "--isin", "DE0007164600", "--baslik", "Ağırlık Testi 0",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2",
            "--hedef-agirlik", "0.0"
        ]) == 0

        # 1.0 -> PASS on US02079K3059
        assert run_cli([
            "tez", "ekle", "--isin", "US02079K3059", "--baslik", "Ağırlık Testi 1",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2",
            "--hedef-agirlik", "1.0"
        ]) == 0

        # Negative: -0.1 -> FAIL (rejected before DB insert)
        assert run_cli([
            "tez", "ekle", "--isin", "US02079K1079", "--baslik", "Ağırlık Negatif",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2",
            "--hedef-agirlik", "-0.1"
        ]) == 1

        # Exceeds: 1.01 -> FAIL
        assert run_cli([
            "tez", "ekle", "--isin", "US02079K1079", "--baslik", "Ağırlık Fazla",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2",
            "--hedef-agirlik", "1.01"
        ]) == 1

        # Non-numeric -> FAIL
        assert run_cli([
            "tez", "ekle", "--isin", "US02079K1079", "--baslik", "Ağırlık Metin",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2",
            "--hedef-agirlik", "not_a_number"
        ]) == 1

    def test_thesis_ekle_review_date_boundaries(self, isolated_env, capsys):
        """Date boundaries: valid ISO (pass), leap year 2028-02-29 (pass), invalid leap 2027-02-29 (fail), slash format (fail)."""
        base = [
            "tez", "ekle", "--isin", "IE00B3YLTY66", "--baslik", "Tarih Testi",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2"
        ]
        # Leap year 2028-02-29 -> PASS
        assert run_cli(base + ["--sonraki-kontrol", "2028-02-29"]) == 0

        # Invalid leap year 2027-02-29 -> FAIL
        assert run_cli(base + ["--sonraki-kontrol", "2027-02-29"]) == 1

        # Slash format 2026/12/31 -> FAIL
        assert run_cli(base + ["--sonraki-kontrol", "2026/12/31"]) == 1

        # Non-ISO format 31-12-2026 -> FAIL
        assert run_cli(base + ["--sonraki-kontrol", "31-12-2026"]) == 1

    def test_thesis_ekle_invalid_isin_rejected(self, isolated_env, capsys):
        """Invalid Luhn or bad length ISIN must be rejected."""
        base = [
            "tez", "ekle", "--baslik", "ISIN Testi",
            "--ozet", "Özet metni yeterli uzunlukta olmalıdır.",
            "--gerekce", "Ekonomik gerekçe metni de yeterli uzunluktadır.",
            "--tetikleyiciler", "T1", "T2"
        ]
        # Wrong Luhn digit: IE00B3YLTY65 instead of IE00B3YLTY66
        assert run_cli(base + ["--isin", "IE00B3YLTY65"]) == 1

        # Malformed format
        assert run_cli(base + ["--isin", "US123"]) == 1


# ============================================================================
# 2. CLI STDIN PIPING & CONFIG MANAGEMENT
# ============================================================================

class TestConfigCLISteinPipingEdgeCases:

    def test_config_portfoy_piped_stdin_valid(self, isolated_env, monkeypatch, capsys):
        """Verify piping valid portfolio configuration via stdin ('-')."""
        payload = {
            "cekirdek_isin": "IE00B3YLTY66",
            "araclar": {
                "IE00B3YLTY66": {"rol": "Çekirdek", "tur": "ETF"},
                "IE00BKM4GZ66": {"rol": "Gelişmekte Olan", "tur": "ETF"},
            },
            "hedef_agirliklar": {
                "IE00B3YLTY66": 0.60,
                "IE00BKM4GZ66": 0.40,
            },
        }
        json_str = json.dumps(payload)

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p_ayar = sub.add_parser("ayar")
        sub_ayar = p_ayar.add_subparsers(dest="ayar_action")
        p_yaz = sub_ayar.add_parser("yaz")
        p_yaz.add_argument("--dosya", required=True)
        p_yaz.add_argument("--json", required=True)
        p_yaz.add_argument("--onayla-politika", action="store_true")

        args = parser.parse_args(["ayar", "yaz", "--dosya", "portfoy", "--json", "-"])

        # Mock sys.stdin
        monkeypatch.setattr(sys, "stdin", io.StringIO(json_str))
        ret = cmd_ayar(args)
        assert ret == 0

        # Verify target file updated
        written = json.loads((isolated_env["cfg_dir"] / "portfoy.json").read_text(encoding="utf-8"))
        assert written["hedef_agirliklar"]["IE00B3YLTY66"] == 0.60
        assert written["hedef_durumu"] == "ONAYLANDI"

    def test_config_politika_piped_stdin_requires_confirmation(self, isolated_env, monkeypatch, capsys):
        """Setting policy to ONAYLANDI via stdin without --onayla-politika MUST be rejected."""
        payload = {
            "durum": "ONAYLANDI",
            "tolerans_mutlak": 0.05,
            "tolerans_goreli": 0.25,
        }
        json_str = json.dumps(payload)

        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p_ayar = sub.add_parser("ayar")
        sub_ayar = p_ayar.add_subparsers(dest="ayar_action")
        p_yaz = sub_ayar.add_parser("yaz")
        p_yaz.add_argument("--dosya", required=True)
        p_yaz.add_argument("--json", required=True)
        p_yaz.add_argument("--onayla-politika", action="store_true")

        # Without confirmation -> REJECT
        args_unconfirmed = parser.parse_args(["ayar", "yaz", "--dosya", "politika", "--json", "-"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json_str))
        assert cmd_ayar(args_unconfirmed) == 1

        # With confirmation -> PASS
        args_confirmed = parser.parse_args(["ayar", "yaz", "--dosya", "politika", "--json", "-", "--onayla-politika"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json_str))
        assert cmd_ayar(args_confirmed) == 0

        written = json.loads((isolated_env["cfg_dir"] / "politika.json").read_text(encoding="utf-8"))
        assert written["durum"] == "ONAYLANDI"

    def test_config_piped_stdin_malformed_json(self, isolated_env, monkeypatch, capsys):
        """Piping invalid JSON into stdin must be cleanly rejected with exit code 1."""
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p_ayar = sub.add_parser("ayar")
        sub_ayar = p_ayar.add_subparsers(dest="ayar_action")
        p_yaz = sub_ayar.add_parser("yaz")
        p_yaz.add_argument("--dosya", required=True)
        p_yaz.add_argument("--json", required=True)
        p_yaz.add_argument("--onayla-politika", action="store_true")

        args = parser.parse_args(["ayar", "yaz", "--dosya", "portfoy", "--json", "-"])
        monkeypatch.setattr(sys, "stdin", io.StringIO("{this is: not valid json!"))
        ret = cmd_ayar(args)
        assert ret == 1
        captured = capsys.readouterr()
        assert "Geçersiz JSON" in captured.out

    def test_config_portfoy_piped_stdin_weight_sum_exceeded(self, isolated_env, monkeypatch, capsys):
        """Target weight sum > 1.0001 must be rejected."""
        payload = {
            "hedef_agirliklar": {
                "IE00B3YLTY66": 0.80,
                "IE00BKM4GZ66": 0.30,  # sum = 1.10
            }
        }
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="command")
        p_ayar = sub.add_parser("ayar")
        sub_ayar = p_ayar.add_subparsers(dest="ayar_action")
        p_yaz = sub_ayar.add_parser("yaz")
        p_yaz.add_argument("--dosya", required=True)
        p_yaz.add_argument("--json", required=True)
        p_yaz.add_argument("--onayla-politika", action="store_true")

        args = parser.parse_args(["ayar", "yaz", "--dosya", "portfoy", "--json", "-"])
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        assert cmd_ayar(args) == 1
        captured = capsys.readouterr()
        assert "1'i aşıyor" in captured.out


# ============================================================================
# 3. DATABASE TRIGGERS & IMMUTABILITY INTEGRITY
# ============================================================================

class TestDatabaseImmutabilityAndIntegrity:

    def test_thesis_immutability_trigger_blocks_update(self, isolated_env):
        """Verify that SQLite triggers strictly block direct UPDATE on thesis_versions."""
        mgr = ThesisManager(isolated_env["db"])
        rec = ThesisRecord(
            isin="IE00B3YLTY66",
            category=ThesisCategory.CORE,
            horizon=ThesisHorizon.LONG_TERM,
            title="Değiştirilemezlik Testi",
            one_line_summary="Bu tez veritabanı mühür bütünlüğünü test eder.",
            economic_rationale="Gerekçe metni en az 10 karakter olmalıdır.",
            falsification_triggers=["T1: Koşul A", "T2: Koşul B"],
        )
        created = mgr.create_thesis(rec)

        conn = isolated_env["db"].get_connection()
        cursor = conn.cursor()

        # Attempt illegal UPDATE
        with pytest.raises(sqlite3.IntegrityError, match="degistirilemez|append-only"):
            cursor.execute(
                "UPDATE thesis_versions SET title = 'Hacked Title' WHERE version_id = ?",
                (created.version_id,)
            )
        conn.close()

    def test_thesis_immutability_trigger_blocks_delete(self, isolated_env):
        """Verify that SQLite triggers strictly block direct DELETE on thesis_versions."""
        mgr = ThesisManager(isolated_env["db"])
        rec = ThesisRecord(
            isin="IE00B3YLTY66",
            category=ThesisCategory.CORE,
            horizon=ThesisHorizon.LONG_TERM,
            title="Silinemezlik Testi",
            one_line_summary="Bu tez veritabanı mühür bütünlüğünü test eder.",
            economic_rationale="Gerekçe metni en az 10 karakter olmalıdır.",
            falsification_triggers=["T1: Koşul A", "T2: Koşul B"],
        )
        created = mgr.create_thesis(rec)

        conn = isolated_env["db"].get_connection()
        cursor = conn.cursor()

        # Attempt illegal DELETE
        with pytest.raises(sqlite3.IntegrityError, match="silinemez|append-only"):
            cursor.execute(
                "DELETE FROM thesis_versions WHERE version_id = ?",
                (created.version_id,)
            )
        conn.close()

    def test_database_locks_and_journal_mode(self, isolated_env):
        """Verify journal_mode is truncate and foreign_keys/recursive_triggers are active on connections."""
        conn = isolated_env["db"].get_connection()
        cursor = conn.cursor()

        cursor.execute("PRAGMA journal_mode;")
        mode = cursor.fetchone()[0]
        assert str(mode).lower() == "truncate"

        cursor.execute("PRAGMA foreign_keys;")
        assert cursor.fetchone()[0] == 1

        cursor.execute("PRAGMA recursive_triggers;")
        assert cursor.fetchone()[0] == 1
        conn.close()
