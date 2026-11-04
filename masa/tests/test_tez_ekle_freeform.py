"""test_tez_ekle_freeform.py — Tests for İP-3 [O1] Freeform JSON text arguments and edge cases."""

import json
from decimal import Decimal
import io
import sys
import pytest

from masa.cli import build_parser, cmd_tez
from masa.storage.db import DatabaseManager
from masa.thesis.manager import ThesisManager


def test_tez_ekle_via_stdin_json(tmp_path, monkeypatch):
    """Test adding thesis via --girdi-json - with emojis, quotes, and long rationale."""
    db_file = tmp_path / "test_masa.db"
    monkeypatch.setenv("MASA_DB_PATH", str(db_file))

    db = DatabaseManager(db_file)
    db.initialize_schema()
    conn = db.get_connection()
    try:
        conn.execute(
            """INSERT INTO instruments (instrument_id, isin, name, instrument_type, issuer_id, base_currency, created_at, record_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("inst_test01", "IE00B3YLTY66", "SPDR MSCI ACWI UCITS ETF", "ETF", "iss_01", "EUR", "2026-11-01T00:00:00Z", "hash_test01"),
        )
    finally:
        conn.close()

    payload = {
        "isin": "IE00B3YLTY66",
        "baslik": "Küresel 🚀 ETF Tezi: \"Tek Dünya, Tek Fon\" --json flag testi",
        "ozet": "Gelişmiş ve gelişmekte olan piyasaları kapsayan temel birikim tezi.",
        "gerekce": "Ekonomik büyüme ve verimlilik artışı " + ("uzun vadede değer üretir. " * 200),  # > 5000 chars
        "kategori": "CEKIRDEK",
        "vade": "STRATEJIK_UZUN",
        "tetikleyiciler": [
            "Küresel ticaret hacminde %40'ı aşan kalıcı daralma yaşanırsa 📉",
            "Fon yönetim ücreti %1.00 üzerine çıkarsa veya replikasyon aksarsa"
        ],
        "kanitlar": [
            "MSCI ACWI 20 yıllık net getiri serisi",
            "Düşük takip hatası (%0.03)"
        ],
        "karsi_gorus": "ABD teknoloji ağırlığının aşırı yükselmesi riski.",
        "hedef_agirlik": 0.45,
        "sonraki_kontrol": "2026-12-01",
        "yazar": "akif"
    }

    raw_json = json.dumps(payload, ensure_ascii=False)
    assert len(payload["gerekce"]) > 5000

    monkeypatch.setattr(sys, "stdin", io.StringIO(raw_json))

    parser = build_parser()
    args = parser.parse_args(["tez", "ekle", "--girdi-json", "-", "--json"])

    captured_out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured_out)

    exit_code = cmd_tez(args)
    output_str = captured_out.getvalue()
    assert exit_code == 0, f"Expected 0 exit code, got {exit_code}, out: {output_str}"
    json_start = output_str.find("{")
    assert json_start != -1, f"No JSON found in output: {output_str}"
    result = json.loads(output_str[json_start:])
    assert result["isin"] == "IE00B3YLTY66"
    assert result["category"] == "CORE"
    assert result["horizon"] == "LONG_TERM"
    assert "🚀" in result["title"]
    assert "--json" in result["title"]
    assert Decimal(result["target_allocation_pct"]) == Decimal("0.45")
    assert len(result["economic_rationale"]) > 5000


def test_tez_ekle_negative_weight_rejected(tmp_path, monkeypatch):
    """Negative target weight like -10% or -0.10 must be strictly rejected."""
    db_file = tmp_path / "test_masa.db"
    monkeypatch.setenv("MASA_DB_PATH", str(db_file))

    db = DatabaseManager(db_file)
    db.initialize_schema()
    conn = db.get_connection()
    try:
        conn.execute(
            """INSERT INTO instruments (instrument_id, isin, name, instrument_type, issuer_id, base_currency, created_at, record_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("inst_test01", "IE00B3YLTY66", "SPDR MSCI ACWI UCITS ETF", "ETF", "iss_01", "EUR", "2026-11-01T00:00:00Z", "hash_test01"),
        )
    finally:
        conn.close()

    payload = {
        "isin": "IE00B3YLTY66",
        "baslik": "Geçersiz Negatif Ağırlık Tezi",
        "ozet": "Kısa pozisyon veya negatif ağırlık denemesi.",
        "gerekce": "Negatif hedef ağırlık sistem kurallarına aykırıdır.",
        "kategori": "CORE",
        "vade": "LONG_TERM",
        "tetikleyiciler": ["Tetikleyici 1", "Tetikleyici 2"],
        "hedef_agirlik": -0.10,
    }

    raw_json = json.dumps(payload, ensure_ascii=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw_json))

    parser = build_parser()
    args = parser.parse_args(["tez", "ekle", "--girdi-json", "-", "--json"])

    captured_out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured_out)

    exit_code = cmd_tez(args)
    assert exit_code != 0
