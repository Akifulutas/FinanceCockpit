"""Tests for macOS launchd scheduler and notification bridge (İP-12)."""

from decimal import Decimal
from pathlib import Path
import plistlib
import pytest

from masa.cli import main
from masa.notify import (
    notify_forecast_generated,
    notify_forecast_settled,
    notify_system_alert,
    send_notification,
)
from masa.scheduler import (
    JOB_SPECS,
    generate_plist_dict,
    get_schedule_status,
    install_jobs,
    render_plist_xml,
    uninstall_jobs,
)


def test_render_plist_xml_syntax(tmp_path):
    """Verify generated plist XML is 100% syntactically valid and loads via plistlib."""
    for spec in JOB_SPECS:
        xml_bytes = render_plist_xml(spec, log_dir=tmp_path)
        # Parse back with standard library
        parsed = plistlib.loads(xml_bytes)
        assert parsed["Label"] == spec["label"]
        assert "ProgramArguments" in parsed
        assert len(parsed["ProgramArguments"]) >= 2
        assert "StartCalendarInterval" in parsed
        assert len(parsed["StartCalendarInterval"]) > 0
        assert parsed["StandardOutPath"].endswith(".log")
        assert parsed["StandardErrorPath"].endswith(".log")


def test_install_and_uninstall_jobs_isolated(tmp_path):
    """Verify install_jobs writes valid plists and uninstall_jobs removes them."""
    installed = install_jobs(dest_dir=tmp_path, run_launchctl=False)
    assert len(installed) == 3
    for p in installed:
        assert p.exists()
        assert p.suffix == ".plist"

    # Status check
    statuses = get_schedule_status(dest_dir=tmp_path)
    assert len(statuses) == 3
    assert all(s["installed"] for s in statuses)

    # Uninstall
    removed = uninstall_jobs(dest_dir=tmp_path, run_launchctl=False)
    assert len(removed) == 3
    for p in installed:
        assert not p.exists()


def test_send_notification_dry_run():
    """Verify send_notification handles dry-run without errors."""
    res = send_notification(
        title="Test Title",
        subtitle="Test Subtitle",
        message='Test Message with "quotes" and \\backslashes\\',
        sound="default",
        dry_run=True,
    )
    assert res is True


def test_notify_triggers_dry_run():
    """Verify built-in notification helper functions in dry-run mode."""
    assert notify_forecast_generated(count=10, model_id="model_momentum_v1", dry_run=True) is True
    assert notify_forecast_settled(
        count=10,
        hit_rate_pct=Decimal("70.0"),
        mape_pct=Decimal("1.25"),
        dry_run=True,
    ) is True
    assert notify_system_alert(level="KRİTİK", message="Oturum süresi doldu", dry_run=True) is True


def test_cli_zamanla_lifecycle(tmp_path, capsys):
    """Verify `masa zamanla` subcommands execute cleanly through CLI."""
    # 1. kur (dry run)
    with pytest.raises(SystemExit) as exc:
        main(["zamanla", "kur", "--kuru", "--hedef", str(tmp_path)])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "LAUNCHD GÖREV ZAMANLAYICI KURULUMU" in captured.out
    assert "3 adet LaunchAgent plist dosyası kuruldu" in captured.out

    # 2. durum
    with pytest.raises(SystemExit) as exc:
        main(["zamanla", "durum", "--hedef", str(tmp_path)])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "GÖREV ZAMANLAYICI DURUMU" in captured.out
    assert "com.etf.masa.sabah" in captured.out

    # 3. kaldir
    with pytest.raises(SystemExit) as exc:
        main(["zamanla", "kaldir", "--hedef", str(tmp_path)])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "LAUNCHD GÖREV ZAMANLAYICI KALDIRMA" in captured.out
    assert "3 LaunchAgent görevi durduruldu ve silindi" in captured.out
