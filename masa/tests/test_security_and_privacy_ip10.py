"""Tests for Security Hardening, POSIX Permissions, and Privacy Sanitization (İP-10)."""

import os
from pathlib import Path
import stat
import pytest

from masa.cli import main
from masa.privacy import (
    FORBIDDEN_KEYS,
    PrivacyViolationError,
    is_isin,
    mask_report_for_sharing,
    sanitize_for_external,
    sanitize_text,
)
from masa.security import ensure_secure_permissions


def test_ensure_secure_permissions(tmp_path):
    """Verify directories become 0700 and sensitive files become 0600."""
    sub_dir = tmp_path / "private_sub"
    sub_dir.mkdir()
    os.chmod(sub_dir, 0o755)

    db_file = sub_dir / "masa.db"
    db_file.write_text("dummy db")
    os.chmod(db_file, 0o644)

    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=123")
    os.chmod(env_file, 0o666)

    lock_file = sub_dir / "sc.lock"
    lock_file.write_text("lock")
    os.chmod(lock_file, 0o644)

    changes = ensure_secure_permissions(tmp_path)
    assert len(changes) > 0

    # Verify directory permissions
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert stat.S_IMODE(sub_dir.stat().st_mode) == 0o700

    # Verify sensitive file permissions
    assert stat.S_IMODE(db_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(lock_file.stat().st_mode) == 0o600


def test_is_isin_discriminator():
    """Verify ISINs are kept and IBANs are rejected."""
    assert is_isin("IE00B4L5Y983") is True
    assert is_isin("US0378331005") is True
    assert is_isin("DE89370400440532013000") is False  # 22 chars
    assert is_isin("TR000000000000000000000000") is False  # 26 chars


def test_sanitize_text_redacts_ibans_and_secrets():
    """Verify secrets and IBANs are masked while ISINs are preserved."""
    raw = (
        "Fon ISIN: IE00B4L5Y983. "
        "Kullanıcı IBAN: DE89370400440532013000. "
        "Yetki: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token123."
    )
    scrubbed = sanitize_text(raw)
    assert "IE00B4L5Y983" in scrubbed
    assert "DE89370400440532013000" not in scrubbed
    assert "[MASKELENDİ_IBAN]" in scrubbed
    assert "[MASKELENDİ_GİZLİ_ANAHTAR]" in scrubbed


def test_sanitize_for_external_strict_raises_on_forbidden_keys():
    """Verify blacklisted keys trigger PrivacyViolationError in strict mode."""
    payload = {
        "symbol": "SPYI",
        "isin": "IE00B3YLTY66",
        "owner": "Akif Ulutas",
        "account_id": "ACC-998877",
    }
    with pytest.raises(PrivacyViolationError) as exc:
        sanitize_for_external(payload, strict=True)
    assert "owner" in str(exc.value) or "account_id" in str(exc.value)


def test_sanitize_for_external_non_strict_strips_forbidden_keys():
    """Verify non-strict mode cleanly drops forbidden keys."""
    payload = {
        "symbol": "SPYI",
        "isin": "IE00B3YLTY66",
        "owner": "Akif Ulutas",
        "account_id": "ACC-998877",
        "price": 105.50,
    }
    cleaned = sanitize_for_external(payload, strict=False)
    assert "symbol" in cleaned
    assert "isin" in cleaned
    assert "price" in cleaned
    assert "owner" not in cleaned
    assert "account_id" not in cleaned


def test_mask_report_for_sharing():
    """Verify --paylasim mode masks absolute EUR values, run_ids, and paths."""
    report = (
        "# ETF Yatırım Masası Raporu\n"
        "Mühür: run_20261031_093000\n"
        "Toplam Portföy: 25,450.75 EUR\n"
        "Nakit: 3,200.00 EUR\n"
        "Kaynak Dosya: /Users/testuser/Documents/ETF/masa/var/reports/test.md\n"
    )
    masked = mask_report_for_sharing(report)
    assert "PAYLAŞILABİLİR KİP (--paylasim)" in masked
    assert "25,450.75 EUR" not in masked
    assert "3,200.00 EUR" not in masked
    assert "[GİZLENDİ] EUR" in masked
    assert "run_20261031_093000" not in masked
    assert "run_YYYYMMDD_HHMMSS" in masked
    assert "/Users/testuser" not in masked
    assert "[YEREL_DOSYA_YOLU]" in masked


def test_cli_guvenlik_tara_command(capsys):
    """Verify `masa guvenlik-tara` CLI runs successfully."""
    with pytest.raises(SystemExit) as exc:
        main(["guvenlik-tara"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "GÜVENLİK VE GİZLİLİK DENETİMİ" in captured.out
    assert "GÜVENLİK VE GİZLİLİK SERTLEŞTİRMESİ TAMAMLANDI" in captured.out
