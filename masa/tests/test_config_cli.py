"""Unit tests for masa ayar goster and masa ayar yaz CLI and config module."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import pytest

from masa import config
from masa.cli import cmd_ayar


@pytest.fixture
def isolated_config_dir(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "CONFIG_DIR", cfg_dir)

    # Populate baseline files
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
    modeller = {
        "hizli_katman": [{"saglayici": "google", "model": "gemini-3.8-flash", "agirlik": 1}],
        "derin_katman": {"saglayici": "chatgpt", "model": "gpt-6.1-sol"},
    }

    (cfg_dir / "portfoy.json").write_text(json.dumps(portfoy), encoding="utf-8")
    (cfg_dir / "politika.json").write_text(json.dumps(politika), encoding="utf-8")
    (cfg_dir / "modeller.json").write_text(json.dumps(modeller), encoding="utf-8")

    return cfg_dir


def test_get_config_summary(isolated_config_dir):
    summary = config.get_config_summary()
    assert summary["schema_version"] == "1.0.0"
    assert "portfoy" in summary
    assert "politika" in summary
    assert "modeller" in summary
    assert "model_erisim" in summary
    assert "broker" in summary
    assert summary["portfoy"]["cekirdek_isin"] == "IE00B3YLTY66"
    assert summary["politika"]["durum"] == "TASLAK"
    assert isinstance(summary["model_erisim"]["providers"], list)


def test_write_config_portfoy_valid(isolated_config_dir):
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

    ok, msg, archive = config.write_config("portfoy", payload)
    assert ok is True
    assert archive is not None
    assert archive.exists()
    assert archive.parent.name == "arsiv"

    written = json.loads((isolated_config_dir / "portfoy.json").read_text(encoding="utf-8"))
    assert written["hedef_durumu"] == "ONAYLANDI"
    assert written["hedef_agirliklar"]["IE00B3YLTY66"] == 0.60
    assert written["hedef_agirliklar"]["IE00BKM4GZ66"] == 0.40


def test_write_config_portfoy_sum_exceeded(isolated_config_dir):
    payload = {
        "hedef_agirliklar": {
            "IE00B3YLTY66": 0.70,
            "IE00BKM4GZ66": 0.50,
        }
    }
    with pytest.raises(ValueError, match="toplamı 1'i aşıyor"):
        config.write_config("portfoy", payload)


def test_write_config_portfoy_invalid_isin(isolated_config_dir):
    payload = {
        "hedef_agirliklar": {
            "INVALID_ISIN_123": 0.50,
        }
    }
    with pytest.raises(ValueError):
        config.write_config("portfoy", payload)


def test_write_config_politika_onay_guard(isolated_config_dir):
    payload = {
        "durum": "ONAYLANDI",
        "tolerans_mutlak": 0.05,
    }
    with pytest.raises(ValueError, match="--onayla-politika parametresi gereklidir"):
        config.write_config("politika", payload, confirm_policy=False)


def test_write_config_politika_onay_confirmed(isolated_config_dir):
    payload = {
        "durum": "ONAYLANDI",
        "tolerans_mutlak": 0.05,
        "tolerans_goreli": 0.20,
    }
    ok, msg, archive = config.write_config("politika", payload, confirm_policy=True)
    assert ok is True
    written = json.loads((isolated_config_dir / "politika.json").read_text(encoding="utf-8"))
    assert written["durum"] == "ONAYLANDI"


def test_cli_ayar_goster_json(isolated_config_dir, capsys):
    args = argparse.Namespace(ayar_action="goster", json=True)
    exit_code = cmd_ayar(args)
    assert exit_code == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["schema_version"] == "1.0.0"
    assert parsed["portfoy"]["cekirdek_isin"] == "IE00B3YLTY66"


def test_cli_ayar_yaz_portfoy(isolated_config_dir, capsys):
    payload_str = json.dumps({
        "hedef_agirliklar": {
            "IE00B3YLTY66": 0.80,
            "IE00BKM4GZ66": 0.20,
        }
    })
    args = argparse.Namespace(
        ayar_action="yaz",
        dosya="portfoy",
        json=payload_str,
        onayla_politika=False,
    )
    exit_code = cmd_ayar(args)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "✓ portfoy.json başarıyla güncellendi." in captured.out


def test_cli_ayar_yaz_rejects_exceeded_sum(isolated_config_dir, capsys):
    payload_str = json.dumps({
        "hedef_agirliklar": {
            "IE00B3YLTY66": 0.80,
            "IE00BKM4GZ66": 0.40,
        }
    })
    args = argparse.Namespace(
        ayar_action="yaz",
        dosya="portfoy",
        json=payload_str,
        onayla_politika=False,
    )
    exit_code = cmd_ayar(args)
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "✗ Yapılandırma yazılamadı" in captured.out
