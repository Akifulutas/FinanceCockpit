"""Tests for static HTML dashboard (masa pano) — İP-9."""

from decimal import Decimal
import html
from pathlib import Path
import re
import pytest

from masa.cli import main
from masa.config import load_config
from masa.pipeline import SealedRun, SealedPosition
from masa.pano import build_pano_html, generate_pano
from masa.storage.db import DatabaseManager


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_pano.db"
    db = DatabaseManager(db_file)
    db.initialize_schema()
    return db


@pytest.fixture
def sample_run():
    pos = SealedPosition(
        isin="IE00B4L5Y983",
        name="iShares Core MSCI World <script>alert('xss')</script>",
        quantity=Decimal("120.0000"),
        broker_value=Decimal("11000.00"),
        broker_mid=Decimal("91.6667"),
        fifo_price=Decimal("80.0000"),
        mid=Decimal("91.6667"),
    )
    return SealedRun(
        run_id="run-test-pano-001",
        completed_at="2026-10-31 09:30:00 UTC",
        hashes={},
        quality="SEALED",
        positions=[pos],
        cash=Decimal("1500.50"),
        buying_power=Decimal("1500.50"),
    )


@pytest.fixture
def sample_integ():
    return {
        "ok": True,
        "schema_version": 3,
        "trigger_count": 78,
        "audit_events": 42,
    }


def test_pano_xss_protection(sample_run, sample_integ):
    """Ensure dynamic text fields are rigorously HTML-escaped against XSS."""
    cfg = load_config()
    html_out = build_pano_html(
        run=sample_run,
        cfg=cfg,
        integ=sample_integ,
        metrics={},
        port_metrics={},
        assessments=[],
        theses=[],
        forecast_scorecard={},
        champions=[],
        recent_jobs=[],
    )

    # Raw script tag must NOT exist
    assert "<script>alert('xss')</script>" not in html_out
    # Escaped script tag MUST exist
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html_out or "&lt;script&gt;alert('xss')&lt;/script&gt;" in html_out


def test_pano_zero_external_network_dependencies(sample_run, sample_integ):
    """Ensure dashboard is 100% self-contained with no external CSS, fonts, or scripts."""
    cfg = load_config()
    html_out = build_pano_html(
        run=sample_run,
        cfg=cfg,
        integ=sample_integ,
        metrics={},
        port_metrics={},
        assessments=[],
        theses=[],
        forecast_scorecard={},
        champions=[],
        recent_jobs=[],
    )

    # No external scripts
    assert not re.search(r'<script[^>]+src=["\']http', html_out, re.IGNORECASE)
    # No external stylesheets
    assert not re.search(r'<link[^>]+href=["\']http', html_out, re.IGNORECASE)
    # No remote url(...) in style
    assert not re.search(r'url\s*\(\s*["\']?http', html_out, re.IGNORECASE)


def test_pano_four_panels_presence(sample_run, sample_integ):
    """Ensure all four required panels from Design Doc §2.4 are present."""
    cfg = load_config()
    html_out = build_pano_html(
        run=sample_run,
        cfg=cfg,
        integ=sample_integ,
        metrics={},
        port_metrics={},
        assessments=[],
        theses=[],
        forecast_scorecard={},
        champions=[],
        recent_jobs=[],
    )

    # Panel 1: Bugün ve veri durumu
    assert "PANEL 1: BUGÜN VE VERİ DURUMU" in html_out
    assert "12,500.50 EUR" in html_out
    assert "Kriptografik Bütünlük GEÇERLİ" in html_out

    # Panel 2: Portföy ve sepet
    assert "Bölüm 2 · Portföy Varlıkları ve Ağırlıklar" in html_out
    assert "IE00B4L5Y983" in html_out

    # Panel 3: Model şampiyonları & İş kuyruğu
    assert "Bölüm 3 · Model Şampiyonları (İP-7)" in html_out

    # Panel 4: Tezler ve tahmin geçmişi
    assert "Bölüm 4 · Yatırım Tezleri Defteri (İP-5)" in html_out


def test_pano_atomic_publishing(tmp_path, test_db):
    """Ensure generate_pano writes to .tmp first and replaces atomically."""
    dest = tmp_path / "reports" / "pano.html"
    out = generate_pano(db=test_db, dest_path=dest)

    assert out.exists()
    assert out == dest
    # .tmp must be cleaned up / replaced
    assert not dest.with_suffix(".tmp").exists()
    content = out.read_text(encoding="utf-8")
    assert "<!doctype html>" in content
    assert "ETF YATIRIM MASASI" in content


def test_pano_cli_invocation(tmp_path, monkeypatch, capsys):
    """Ensure `masa pano --cikis <path>` CLI runs cleanly and produces output."""
    dest = tmp_path / "custom_pano.html"
    with pytest.raises(SystemExit) as exc:
        main(["pano", "--cikis", str(dest)])
    assert exc.value.code == 0
    assert dest.exists()
    captured = capsys.readouterr()
    assert "Statik pano başarıyla üretildi" in captured.out
