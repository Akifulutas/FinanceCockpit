"""Tut / ekle / azalt / gozden gecir — kural tabanli KARAR DESTEGI.

Bu modul emir uretmez ve broker'a erismez. Esikler masa/config/politika.json'dan
gelir; politika ONAYLANMADI ise her degerlendirme "taslak esik" etiketi tasir.
Etiketler oncelik sirasiyla: VERI YETERSIZ > AZALT > GOZDEN GECIR > EKLE > TUT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from masa.analytics import RiskMetrics
from masa.calendar.adapter import CalendarAdapter
from masa.config import Config
from masa.pipeline import SealedPosition, SealedRun

TEILFREISTELLUNG_EQUITY_ETF = Decimal("0.30")


@dataclass
class Assessment:
    isin: str
    name: str
    label: str
    reasons: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    weight: Decimal = Decimal("0")
    target: Optional[Decimal] = None
    unrealized_eur: Optional[Decimal] = None
    unrealized_pct: Optional[Decimal] = None
    external_opinion: Optional[str] = None


_PRIORITY = ["VERİ YETERSİZ", "AZALT", "GÖZDEN GEÇİR", "EKLE", "TUT"]


def _pick(labels: List[str]) -> str:
    return min(labels, key=_PRIORITY.index) if labels else "TUT"


def assess(run: SealedRun, cfg: Config, metrics: Dict[str, Optional[RiskMetrics]]) -> List[Assessment]:
    total = run.total
    pol = cfg.policy
    core = metrics.get(cfg.core_isin) if cfg.core_isin else None
    out: List[Assessment] = []

    cal = CalendarAdapter("XETR")
    try:
        snap_dt = datetime.fromisoformat(run.completed_at)
        if snap_dt.tzinfo is None:
            snap_dt = snap_dt.replace(tzinfo=timezone.utc)
    except Exception:
        snap_dt = datetime.now(timezone.utc)

    is_open = False
    try:
        is_open = cal.is_market_open(snap_dt)
    except Exception:
        pass

    for p in run.positions:
        w = p.value / total if total else Decimal("0")
        a = Assessment(p.isin, p.name, "TUT", weight=w, target=cfg.targets.get(p.isin))
        labels: List[str] = []
        m = metrics.get(p.isin)

        # Check quote validity considering closed market session (weekend / after-hours)
        if p.quality == "MISSING" or p.mid is None:
            labels.append("VERİ YETERSİZ")
            a.reasons.append("Kotasyon eksik; fiyata dayalı karar verilmedi.")
        elif p.quality in ("OUTDATED", "UNKNOWN", "AGED"):
            quote_dt = None
            if p.quote_time:
                try:
                    quote_dt = datetime.fromisoformat(p.quote_time)
                    if quote_dt.tzinfo is None:
                        quote_dt = quote_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            if not is_open and quote_dt:
                try:
                    assessment = cal.assess_quote_freshness(quote_dt, max(snap_dt, quote_dt), venue_mic="XETR")
                    if not assessment.is_stale:
                        a.notes.append(f"Piyasa kapalı (XETR). Son seans kapanış kotasyonu ({p.quote_time[:16]}) geçerli kabul edildi.")
                    else:
                        labels.append("VERİ YETERSİZ")
                        a.reasons.append(f"Kotasyon son seans kapanışından eski ({p.quote_age_seconds or 0:.0f} sn); fiyata dayalı karar verilmedi.")
                except Exception:
                    labels.append("VERİ YETERSİZ")
                    a.reasons.append(f"Kotasyon kalitesi {p.quality}; fiyata dayalı karar verilmedi.")
            else:
                labels.append("VERİ YETERSİZ")
                a.reasons.append(f"Kotasyon kalitesi {p.quality}; fiyata dayalı karar verilmedi.")

        if m is None:
            labels.append("VERİ YETERSİZ")
            a.reasons.append("Fiyat geçmişi yok (önce `masa gecmis`); trend, düşüş ve tez göstergeleri değerlendirilemedi.")
        if p.fifo_price and p.mid:
            a.unrealized_eur = (p.mid - p.fifo_price) * p.quantity
            a.unrealized_pct = (p.mid / p.fifo_price - 1) * 100

        # 1) policy targets (only if the user wrote them)
        if a.target is not None and total:
            gap = w - a.target
            rel = abs(gap) / a.target if a.target > 0 else Decimal("Infinity")
            if abs(gap) > pol.band_abs and rel > pol.band_rel:
                labels.append("AZALT" if gap > 0 else "EKLE")
                a.reasons.append(f"Ağırlık %{w*100:.1f}, hedef %{a.target*100:.1f} (bant ±%{pol.band_abs*100:.0f} "
                                 f"mutlak ve ±%{pol.band_rel*100:.0f} göreli aşıldı).")
            elif gap < 0:
                labels.append("EKLE")
                a.reasons.append(f"Hedefin altında (%{w*100:.1f} < %{a.target*100:.1f}); yeni nakit önce buraya.")
        # 2) market condition (kept separate from thesis, per tez-ve-portfoy rules)
        if m is not None:
            if m.trend_gap is not None and m.trend_gap < pol.trend_warn:
                labels.append("GÖZDEN GEÇİR")
                a.reasons.append(f"Piyasa koşulu: fiyat ~200 günlük ortalamanın %{m.trend_gap*100:.1f} altında.")
            if m.from_high < pol.drawdown_review:
                labels.append("GÖZDEN GEÇİR")
                a.reasons.append(f"Piyasa koşulu: 1 yıllık zirveden %{m.from_high*100:.1f} aşağıda.")
            # 3) thesis check for factor tilts vs the core holding
            if cfg.is_factor(p.isin) and core is not None and p.isin != cfg.core_isin:
                lag = m.total_return - core.total_return
                if lag < -pol.factor_lag:
                    labels.append("GÖZDEN GEÇİR")
                    a.reasons.append(f"Tez incelemesi: faktör fonu 1 yılda çekirdekten {lag*100:.1f} puan geride.")
                else:
                    a.notes.append(f"Faktör fonu 1 yılda çekirdeğe göre {lag*100:+.1f} puan.")
        if p.spread_pct is not None and float(p.spread_pct) > pol.spread_warn_pct:
            a.notes.append(f"Makas %{float(p.spread_pct):.2f}: işlem yapılacaksa limit emir ve likit saat.")
        if a.unrealized_eur is not None:
            if a.unrealized_eur > 0:
                taxable = a.unrealized_eur * (1 - TEILFREISTELLUNG_EQUITY_ETF)
                a.notes.append(f"Satış {a.unrealized_eur:.2f} € kârı gerçekleştirir (hisse ETF'inde %30 Teilfreistellung "
                               f"sonrası ~{taxable:.2f} € matrah; Sparer-Pauschbetrag 1.000 €/2.000 €). Vergi tavsiyesi değildir.")
            elif a.unrealized_eur < 0:
                a.notes.append(f"{a.unrealized_eur:.2f} € gerçekleşmemiş zarar: satış zararı mahsup edilebilir hale getirir; "
                               "tek başına satış gerekçesi değildir.")
        a.label = _pick(labels)
        if a.label == "TUT":
            a.reasons.append("Politika sınırları içinde; piyasa koşulu ve tez göstergelerinde uyarı yok.")
        if not pol.approved:
            a.notes.append("Eşikler TASLAK (politika.json onaylanmadı).")
        out.append(a)

    # 4) UCITS 5/10/40 concentration check (İP-11) — Yalnızca politika.json'da ucits_kontrolu=True ise çalıştırılır
    if getattr(pol, "ucits_kontrolu", False):
        try:
            from masa.calc.exposure import check_ucits_5_10_40
            weights_map = {p.isin: (p.value / total if total else Decimal("0")) for p in run.positions}
            ucits_res = check_ucits_5_10_40(weights_map)
            if not ucits_res.is_compliant:
                for a in out:
                    for v_isin, v_w in ucits_res.single_limit_violations:
                        if a.isin == v_isin:
                            a.notes.append(f"⚠️ UCITS 5/10/40 Uyarısı: Tekil pozisyon limiti (%10.00) aşıldı (%{v_w * 100:.1f}).")
                    if ucits_res.group_limit_violations:
                        for g_isin, g_w in ucits_res.group_limit_violations:
                            if a.isin == g_isin:
                                a.notes.append(f"⚠️ UCITS 5/10/40 Uyarısı: %5'i aşan pozisyonlar toplamı %40.00 tavanını aştı (Toplam: %{ucits_res.sum_exceeding_5pct * 100:.1f}).")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).debug("UCITS kontrolü sırasında hata oluştu: %s", exc)

    return out
