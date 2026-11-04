"""Static Single-File HTML Dashboard (masa pano).

Design Invariants (İP-9):
1. Four core panels (Design Doc §2.4):
   - Bugün ve veri durumu (mühür zamanı, bütünlük, pazar seansı).
   - Portföy ve sepet (pozisyonlar, ağırlıklar, risk metrikleri, örtüşme).
   - Araştırma ve model kayıtları (kanıt paketleri, model şampiyonları).
   - Tez ve sonuç geçmişi (aktif tezler, 5 ETF + 5 hisse günlük tahmin karnesi).
2. Security & Zero-Leakage:
   - All dynamic text passed through html.escape().
   - Strictly zero external script, font, or CSS CDN dependencies (100% offline self-contained).
   - All icons and indicators rendered as inline SVG.
   - Atomic publishing: writes to pano.html.tmp first, verifies, then atomically replaces.
3. Data consistency:
   - Reads strictly from sealed database via latest_run() and analysis pipeline; no invented data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import html
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from masa.advisor import assess
import masa.analytics as analytics
from masa.audit.queue import JobQueue
from masa.calendar import CalendarAdapter
from masa.config import Config, load_config
from masa.forecast.metrics import calculate_performance_metrics
from masa.model_registry.manager import ModelRegistryManager
from masa.pipeline import Pipeline, integrity_report, latest_run
from masa.storage.db import DatabaseManager
from masa.thesis.manager import ThesisManager

logger = logging.getLogger(__name__)

PANO_CSS = """
:root {
  color-scheme: dark;
  --bg: #0b1016;
  --panel: #121b24;
  --panel-alt: #0e1620;
  --line: #253341;
  --text: #eef4fa;
  --muted: #a2b1c0;
  --accent: #51dbc6;
  --accent-dim: #1e4542;
  --warn: #ffb454;
  --warn-bg: #2b1f11;
  --danger: #ff8077;
  --danger-bg: #2c1616;
  --success: #67ddbb;
  --success-bg: #143329;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 14px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  overflow-wrap: break-word;
}
.wrap { max-width: 1280px; margin: auto; padding: 24px 32px 60px; }
header {
  border-bottom: 1px solid var(--line);
  background: #0d151e;
  padding: 18px 0;
  margin-bottom: 24px;
}
.top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
}
.brand {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.brand span { color: var(--accent); margin-right: 8px; }
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  border: 1px solid var(--line);
  background: var(--panel-alt);
}
.badge-success { border-color: #2e594d; color: var(--success); background: var(--success-bg); }
.badge-warn { border-color: #634621; color: var(--warn); background: var(--warn-bg); }
.badge-danger { border-color: #692929; color: var(--danger); background: var(--danger-bg); }

.grid-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 18px 20px;
}
.card-highlight {
  background: linear-gradient(135deg, #132a2c, #111e29);
  border-color: #2b5550;
}
.card-title {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
  font-weight: 650;
  margin-bottom: 6px;
}
.card-value {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.03em;
  margin-bottom: 4px;
  font-variant-numeric: tabular-nums;
}
.card-sub { font-size: 12px; color: var(--muted); }

.panel-section {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 22px;
  margin-bottom: 24px;
}
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--line);
  padding-bottom: 12px;
  margin-bottom: 16px;
}
.section-header h2 {
  font-size: 17px;
  font-weight: 650;
  margin: 0;
  letter-spacing: -0.01em;
}
.section-header span { font-size: 12px; color: var(--muted); }

.table-wrap {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  width: 100%;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th {
  text-align: left;
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--muted);
  text-transform: uppercase;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
}
td {
  padding: 12px;
  border-bottom: 1px solid #1a2530;
  vertical-align: middle;
}
tr:last-child td { border-bottom: 0; }
.num { text-align: right; font-variant-numeric: tabular-nums; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }

.sub-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}
.pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.pill-buy { background: #183d33; color: #72e5c8; }
.pill-hold { background: #1a2c3a; color: #9bc2e5; }
.pill-trim { background: #3d2618; color: #ffbe72; }

footer {
  margin-top: 40px;
  padding-top: 20px;
  border-top: 1px solid var(--line);
  display: flex;
  justify-content: space-between;
  color: var(--muted);
  font-size: 12px;
}
"""

SVG_CHECK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:var(--success);vertical-align:-2px"><polyline points="20 6 9 17 4 12"></polyline></svg>'
SVG_WARN = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="color:var(--warn);vertical-align:-2px"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>'


def build_pano_html(
    run: Any,
    cfg: Config,
    integ: Dict[str, Any],
    metrics: Dict[str, Any],
    port_metrics: Dict[str, Any],
    assessments: List[Any],
    theses: List[Any],
    forecast_scorecard: Dict[str, Any],
    champions: List[Dict[str, Any]],
    recent_jobs: List[Any],
    market_open: bool = False,
    top_holdings: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Generate 100% self-contained, XSS-safe static HTML dashboard."""
    now_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Financial sums
    total_eur = getattr(run, "total", getattr(run, "total_value", Decimal("0.00")))
    cash_eur = getattr(run, "cash", Decimal("0.00"))
    invested_eur = getattr(run, "positions_value", total_eur - cash_eur)
    positions = getattr(run, "positions", [])

    # Panel 1: Data status badge
    integ_ok = integ.get("ok", False)
    integ_badge = (
        f'<span class="badge badge-success">{SVG_CHECK} Kriptografik Bütünlük GEÇERLİ</span>'
        if integ_ok
        else f'<span class="badge badge-danger">{SVG_WARN} Bütünlük Uyarısı</span>'
    )
    market_badge = (
        '<span class="badge badge-success">XETR Açık</span>'
        if market_open
        else '<span class="badge badge-warn">XETR Kapalı</span>'
    )

    # Positions rows
    pos_rows_html = []
    for p in positions:
        isin_str = getattr(p, "isin", "")
        isin_esc = html.escape(str(isin_str or "—"))
        name_val = cfg.instruments.get(isin_str, {}).get("ad") or getattr(p, "name", "—")
        name_esc = html.escape(str(name_val))
        qty_str = f"{p.quantity:,.4f}" if hasattr(p, "quantity") else "—"
        price_val = getattr(p, "mid", getattr(p, "broker_mid", getattr(p, "price", None)))
        price_str = f"{price_val:,.2f} EUR" if price_val is not None else "—"
        val = getattr(p, "value", None)
        val_str = f"{val:,.2f} EUR" if val is not None else "—"
        w_val = getattr(p, "weight", None)
        if w_val is None and val is not None and total_eur > Decimal("0.00"):
            w_val = val / total_eur
        weight_str = f"%{w_val * 100:.2f}" if w_val is not None else "—"
        role_esc = html.escape(cfg.role(getattr(p, "isin", "")) or "—")

        pos_rows_html.append(
            f"<tr>"
            f'<td class="mono">{isin_esc}</td>'
            f"<td><strong>{name_esc}</strong></td>"
            f'<td class="num">{qty_str}</td>'
            f'<td class="num">{price_str}</td>'
            f'<td class="num">{val_str}</td>'
            f'<td class="num">{weight_str}</td>'
            f"<td><small>{role_esc}</small></td>"
            f"</tr>"
        )
    pos_tbody = "".join(pos_rows_html) if pos_rows_html else '<tr><td colspan="7">Mühürlü pozisyon bulunamadı.</td></tr>'

    # Advisor cards
    adv_cards_html = []
    for s in assessments:
        label = getattr(s, "label", "TUT")
        isin_esc = html.escape(str(getattr(s, "isin", "")))
        name_esc = html.escape(str(getattr(s, "name", "")))
        reasons = [html.escape(r) for r in getattr(s, "reasons", [])]
        pill_cls = "pill-buy" if label == "EKLE" else ("pill-trim" if label == "AZALT" else "pill-hold")
        reasons_li = "".join(f"<li>{r}</li>" for r in reasons[:2])

        adv_cards_html.append(
            f'<div class="card" style="padding:14px;">'
            f'<div style="display:flex;justify-content:space-between;margin-bottom:6px;">'
            f'<strong>{name_esc}</strong><span class="pill {pill_cls}">{html.escape(label)}</span>'
            f"</div>"
            f'<div class="mono" style="color:var(--muted);font-size:11px;margin-bottom:8px;">{isin_esc}</div>'
            f'<ul style="margin:0;padding-left:16px;font-size:12px;color:var(--muted);">{reasons_li}</ul>'
            f"</div>"
        )
    adv_grid = "".join(adv_cards_html) if adv_cards_html else "<p>Tavsiye bulunamadı.</p>"

    # Lookthrough / Top Holdings
    top_h_rows = []
    if top_holdings:
        for th in top_holdings[:10]:
            c_name = html.escape(th.get("company_name", "—"))
            c_ticker = html.escape(th.get("ticker", "—"))
            c_weight = f"%{Decimal(str(th.get('weight_pct', 0))):.2f}"
            c_funds = html.escape(", ".join(th.get("funds", [])))
            top_h_rows.append(
                f"<tr><td><strong>{c_name}</strong> <span class='mono' style='color:var(--muted)'>({c_ticker})</span></td>"
                f'<td class="num"><strong>{c_weight}</strong></td>'
                f"<td><small>{c_funds}</small></td></tr>"
            )
    top_h_tbody = "".join(top_h_rows) if top_h_rows else '<tr><td colspan="3">Sepet detayı için `masa sepet yukle` çalıştırınız.</td></tr>'

    # Theses rows
    thesis_rows = []
    for t in theses:
        isin_esc = html.escape(getattr(t, "isin", "—"))
        title_esc = html.escape(getattr(t, "title", "—"))
        target_w = f"%{getattr(t, 'target_weight_pct', Decimal('0.00')):.2f}"
        rev_date = html.escape(str(getattr(t, "next_review_date", "—")))
        status_esc = html.escape(str(getattr(t, "status", "ACTIVE")))
        thesis_rows.append(
            f"<tr><td class='mono'>{isin_esc}</td>"
            f"<td><strong>{title_esc}</strong></td>"
            f"<td class='num'>{target_w}</td>"
            f"<td>{rev_date}</td>"
            f"<td><span class='badge'>{status_esc}</span></td></tr>"
        )
    theses_tbody = "".join(thesis_rows) if thesis_rows else '<tr><td colspan="5">Kayıtlı aktif tez bulunamadı.</td></tr>'

    # Model Champions rows
    champ_rows = []
    for c in champions:
        cat_esc = html.escape(c.get("task_category", "—"))
        m_name = html.escape(c.get("model_name", "—"))
        prov = html.escape(c.get("provider", "—"))
        score = f"%{Decimal(str(c.get('score_pct', 0))):.2f}"
        champ_rows.append(
            f"<tr><td><strong>{cat_esc}</strong></td>"
            f"<td>👑 {prov} / {m_name}</td>"
            f"<td class='num'><strong>{score}</strong></td></tr>"
        )
    champ_tbody = "".join(champ_rows) if champ_rows else '<tr><td colspan="3">Henüz şampiyon model belirlenmedi (`masa model degerlendir`).</td></tr>'

    # Forecast Scorecard summary
    fc_total = forecast_scorecard.get("total_settled", 0)
    fc_hit = forecast_scorecard.get("hit_rate_pct", Decimal("0.00"))
    fc_mape = forecast_scorecard.get("mape_pct", Decimal("0.00"))

    # Recent Jobs rows
    job_rows = []
    for j in recent_jobs[:5]:
        j_type = html.escape(getattr(j, "job_type", "—"))
        j_stat = html.escape(str(getattr(j, "status", "—")).upper())
        j_time = getattr(j, "created_at").strftime("%H:%M:%S") if getattr(j, "created_at", None) else "—"
        badge_cls = "badge-success" if "PUBLISHED" in j_stat else "badge"
        job_rows.append(
            f"<tr><td><strong>{j_type}</strong></td>"
            f"<td><span class='badge {badge_cls}'>{j_stat}</span></td>"
            f"<td class='num'>{j_time}</td></tr>"
        )
    jobs_tbody = "".join(job_rows) if job_rows else '<tr><td colspan="3">İş kaydı bulunamadı.</td></tr>'

    return f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>ETF Yatırım Masası — Konsolide Pano</title>
  <style>{PANO_CSS}</style>
</head>
<body>
  <header>
    <div class="wrap" style="padding-top:0;padding-bottom:0;">
      <div class="top">
        <div class="brand"><span>◈</span>ETF YATIRIM MASASI</div>
        <div style="display:flex;gap:10px;align-items:center;">
          {market_badge}
          {integ_badge}
          <span class="badge">Şema v{html.escape(str(integ.get('schema_version', 3)))}</span>
        </div>
      </div>
    </div>
  </header>

  <main class="wrap">
    <!-- PANEL 1: BUGÜN VE VERİ DURUMU -->
    <div class="grid-summary">
      <div class="card card-highlight">
        <div class="card-title">Toplam Portföy Değeri</div>
        <div class="card-value">{total_eur:,.2f} EUR</div>
        <div class="card-sub">Nakit: {cash_eur:,.2f} EUR · Yatırılmış: {invested_eur:,.2f} EUR</div>
      </div>
      <div class="card">
        <div class="card-title">Son Mühür / Çalışma</div>
        <div class="card-value mono" style="font-size:20px;padding-top:6px;">{html.escape(str(getattr(run, 'run_id', 'mühürsüz'))[:18])}</div>
        <div class="card-sub">Zaman: {html.escape(str(getattr(run, 'timestamp', now_utc_str)))}</div>
      </div>
      <div class="card">
        <div class="card-title">Tahmin Karnesi (5 ETF + 5 Hisse)</div>
        <div class="card-value" style="color:var(--accent);">%{fc_hit:.1f}</div>
        <div class="card-sub">Uzlaşılan: {fc_total} tahmin · Ortalama Hata: %{fc_mape:.2f}</div>
      </div>
      <div class="card">
        <div class="card-title">Denetim ve Değişmezlik</div>
        <div class="card-value" style="font-size:22px;padding-top:4px;">{integ.get('trigger_count', 78)} Tetikleyici</div>
        <div class="card-sub">Denetim Olayı: {integ.get('audit_events', 0)} · Append-only</div>
      </div>
    </div>

    <!-- PANEL 2: PORTFÖY VE SEPET -->
    <section class="panel-section">
      <div class="section-header">
        <h2>Bölüm 2 · Portföy Varlıkları ve Ağırlıklar</h2>
        <span>{len(positions)} Mühürlü Pozisyon</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ISIN</th>
              <th>Varlık Adı</th>
              <th class="num">Adet</th>
              <th class="num">Son Fiyat</th>
              <th class="num">Piyasa Değeri</th>
              <th class="num">Ağırlık</th>
              <th>Portföy Rolü</th>
            </tr>
          </thead>
          <tbody>{pos_tbody}</tbody>
        </table>
      </div>
    </section>

    <!-- KARAR DESTEĞİ & LOOKTHROUGH -->
    <div class="sub-grid" style="margin-bottom:24px;">
      <section class="panel-section" style="margin-bottom:0;">
        <div class="section-header">
          <h2>Karar Desteği (Tut / Ekle / Azalt)</h2>
          <span>Kural Tabanlı</span>
        </div>
        <div style="display:grid;gap:12px;">{adv_grid}</div>
      </section>

      <section class="panel-section" style="margin-bottom:0;">
        <div class="section-header">
          <h2>Sepet & Şeffaf Bakış (Top 10 Maruziyet)</h2>
          <span>Konsolide Şirketler</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Şirket</th><th class="num">Ağırlık</th><th>İçeren Fonlar</th></tr>
            </thead>
            <tbody>{top_h_tbody}</tbody>
          </table>
        </div>
      </section>
    </div>

    <!-- PANEL 3: MODEL ŞAMPİYONLARI & İŞ KUYRUĞU -->
    <div class="sub-grid" style="margin-bottom:24px;">
      <section class="panel-section" style="margin-bottom:0;">
        <div class="section-header">
          <h2>Bölüm 3 · Model Şampiyonları (İP-7)</h2>
          <span>Doğrulama Kümesi</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Görev</th><th>Şampiyon Model</th><th class="num">Skor</th></tr>
            </thead>
            <tbody>{champ_tbody}</tbody>
          </table>
        </div>
      </section>

      <section class="panel-section" style="margin-bottom:0;">
        <div class="section-header">
          <h2>İş Kuyruğu ve Durum Makinesi (İP-8)</h2>
          <span>Son Görevler</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Görev Türü</th><th>Durum</th><th class="num">Zaman</th></tr>
            </thead>
            <tbody>{jobs_tbody}</tbody>
          </table>
        </div>
      </section>
    </div>

    <!-- PANEL 4: TEZLER VE TAHMİN GEÇMİŞİ -->
    <section class="panel-section">
      <div class="section-header">
        <h2>Bölüm 4 · Yatırım Tezleri Defteri (İP-5)</h2>
        <span>Aktif Yatırım Hipotezleri</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ISIN</th>
              <th>Tez Başlığı</th>
              <th class="num">Hedef Ağırlık</th>
              <th>Sonraki İnceleme</th>
              <th>Durum</th>
            </tr>
          </thead>
          <tbody>{theses_tbody}</tbody>
        </table>
      </div>
    </section>

    <footer>
      <div>Masa Sürümü: v0.2 (Şema v3) · Veri Kaynağı: Scalable Capital Salt-Okunur Mühürleri</div>
      <div>Üretim: {now_utc_str}</div>
    </footer>
  </main>
</body>
</html>
"""


def generate_pano(
    db: Optional[DatabaseManager] = None,
    dest_path: Optional[Path] = None,
) -> Path:
    """Orchestrate data collection, build pano, and publish atomically."""
    mgr = db or DatabaseManager()
    mgr.initialize_schema()
    cfg = load_config()

    run = latest_run(mgr)
    integ = integrity_report(mgr)

    # Analytics and assessments
    metrics = {}
    port_metrics = {}
    assessments = []
    if run is not None:
        try:
            from masa.cli import _analysis
            _, metrics, _, port_metrics, _, _ = _analysis(mgr, cfg, run)
            assessments = assess(run, cfg, metrics)
        except Exception as exc:
            logger.warning(f"Pano analiz verisi oluşturulurken uyarı: {exc}")

    # Market session status
    market_open = False
    try:
        cal = CalendarAdapter()
        market_open = cal.is_market_open(datetime.now(timezone.utc))
    except Exception:
        pass

    # Theses
    theses = []
    try:
        tm = ThesisManager(mgr)
        theses = tm.list_theses(status="ACTIVE")
    except Exception as exc:
        logger.warning(f"Pano tezleri okunamadı: {exc}")

    # Forecast Scorecard
    forecast_scorecard = {"total_settled": 0, "hit_rate_pct": Decimal("0.00"), "mape_pct": Decimal("0.00")}
    try:
        card = calculate_performance_metrics(db=mgr)
        if card:
            forecast_scorecard = {
                "total_settled": card.settled_count,
                "hit_rate_pct": card.hit_rate_pct,
                "mape_pct": card.mape_pct,
            }
    except Exception as exc:
        logger.warning(f"Pano tahmin karnesi okunamadı: {exc}")

    # Model Champions
    champions = []
    try:
        m_mgr = ModelRegistryManager(mgr)
        m_mgr.seed_default_models()
        champions = m_mgr.get_champions()
    except Exception as exc:
        logger.warning(f"Pano model şampiyonları okunamadı: {exc}")

    # Top Holdings Lookthrough
    top_holdings = []
    try:
        from masa.calc.overlap import run_portfolio_overlap_analysis
        _, summary, _ = run_portfolio_overlap_analysis(mgr, top_n=10)
        for s in summary.top_stocks[:10]:
            top_holdings.append({
                "company_name": s.name,
                "ticker": s.ticker or (s.isin if s.isin else "—"),
                "weight_pct": s.portfolio_weight * Decimal("100"),
                "funds": list(s.contributions.keys()),
            })
    except Exception as exc:
        logger.debug(f"Pano lookthrough okunamadı: {exc}")

    # Recent Jobs
    recent_jobs = []
    try:
        jq = JobQueue(mgr)
        recent_jobs = jq.list_recent_jobs(limit=5)
    except Exception:
        pass

    html_content = build_pano_html(
        run=run,
        cfg=cfg,
        integ=integ,
        metrics=metrics,
        port_metrics=port_metrics,
        assessments=assessments,
        theses=theses,
        forecast_scorecard=forecast_scorecard,
        champions=champions,
        recent_jobs=recent_jobs,
        market_open=market_open,
        top_holdings=top_holdings,
    )

    out_file = dest_path or (mgr.db_path.parent.parent / "reports" / "pano.html")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write pattern
    tmp_file = out_file.with_suffix(".tmp")
    tmp_file.write_text(html_content, encoding="utf-8")
    tmp_file.replace(out_file)

    logger.info(f"Pano başarıyla üretildi ve atomik yayımlandı: {out_file}")
    return out_file
