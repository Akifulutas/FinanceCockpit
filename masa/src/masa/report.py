"""Markdown rapor: YALNIZ muhurlu veriden; butunluk satirlari gercek kontrol sonucudur."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from masa.advisor import Assessment
from masa.analytics import RealizedReturn, RiskMetrics
from masa.config import Config
from masa.pipeline import SealedRun
from masa.research import critic

PERF_LABELS = [("ONE_WEEK", "1H"), ("ONE_MONTH", "1A"), ("THREE_MONTHS", "3A"), ("SIX_MONTHS", "6A"),
               ("ONE_YEAR", "1Y"), ("SINCE_BUY", "Alıştan beri")]


def eur(v: Optional[Decimal | float]) -> str:
    if v is None:
        return "—"
    return f"{float(v):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v: Optional[float | Decimal], digits: int = 2, signed: bool = False) -> str:
    if v is None:
        return "—"
    return f"{float(v):{'+' if signed else ''}.{digits}f}%".replace(".", ",")


def critic_check(run: SealedRun, corr) -> critic.RedTeamCriticResultPayload:
    """Red-team: report's prices/weights/totals vs the price seal (and correlations vs data)."""
    total = float(run.total)
    vm: Dict[str, Any] = {
        "portfolio_currency": "EUR",
        "portfolio_positions": [{"symbol": p.isin, "quantity": float(p.quantity), "price": float(p.mid),
                                 "currency": "EUR"} for p in run.positions if p.mid is not None],
        "portfolio_total": float(run.positions_value),
        "prices": {p.isin: float(p.mid) for p in run.positions if p.mid is not None},
        "portfolio_weights": {p.isin: float(p.value) / float(run.positions_value) for p in run.positions}
        if run.positions_value else {},
    }
    seal = {"quotes": {p.isin: {"bid": float(p.bid), "ask": float(p.ask), "computed_mid": float(p.mid),
                                "currency": "EUR"} for p in run.positions if p.mid is not None}}
    evidence: Dict[str, Any] = {"price_seal": seal}
    claims = [{"claim_id": "C1", "text": f"Toplam yatırım değeri {total:.2f} EUR", "tag": "computation"}]
    if corr is not None:
        vm["claimed_correlations"] = []
        cols = list(corr.columns)
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                cid = f"R{len(claims)}"
                claims.append({"claim_id": cid, "text": f"rho({a},{b})={corr.loc[a, b]:.2f}", "tag": "computation"})
                vm["claimed_correlations"].append({"asset_a": a, "asset_b": b, "rho": round(float(corr.loc[a, b]), 4),
                                                   "claim_id": cid})
        evidence["empirical_covariance_matrix"] = {"correlations": {a: {b: float(corr.loc[a, b]) for b in cols}
                                                                    for a in cols}}
    payload = {"audit_context": {"audit_id": f"AU-{run.run_id}", "primary_agent_model": "masa-deterministic",
                                 "report_type": "portfolio", "audit_strictness": "PRODUCTION_GATE"},
               "candidate_report": {"report_id": run.run_id, "title": "Masa portföy raporu",
                                    "thesis_summary": "Mühürlü portföy görünümü", "claims": claims,
                                    "valuation_metrics": vm},
               "verified_evidence_bundle": evidence}
    return critic.audit_report(payload)


def build(run: SealedRun, cfg: Config, integrity: Dict[str, Any], market_open: bool,
          metrics: Dict[str, Optional[RiskMetrics]], portfolio_metrics: Optional[RiskMetrics], corr,
          assessments: List[Assessment], realized: Optional[RealizedReturn], plan: Optional[Any],
          scan: Optional[Dict[str, Any]], ta_results: Dict[str, Dict[str, Any]],
          critic_result: Optional[critic.RedTeamCriticResultPayload]) -> str:
    now = datetime.now(timezone.utc)
    L: List[str] = []
    a = L.append
    a("# ETF Yatırım Masası — Portföy Raporu")
    a("")
    a(f"**Rapor zamanı:** {now.strftime('%d.%m.%Y %H:%M UTC')}  ")
    a(f"**Veri mührü:** `{run.run_id}` (toplama bitişi {run.completed_at[:19].replace('T', ' ')} UTC, kalite **{run.quality}**)  ")
    if run.owner:
        a(f"**Hesap sahibi (Scalable oturumu):** {run.owner}  ")
    a(f"**Xetra (XETR) şu an:** {'AÇIK' if market_open else 'KAPALI'} · fiyat kaynağı: Scalable CLI (salt okuma)")
    a("")
    a("## 1. Özet")
    a("")
    a("| Kalem | Tutar | Pay |")
    a("|---|---|---|")
    tot = run.total
    a(f"| Yatırımlar (mid fiyat) | {eur(run.positions_value)} | {pct(run.positions_value / tot * 100 if tot else 0)} |")
    a(f"| Nakit | {eur(run.cash)} | {pct(run.cash / tot * 100 if tot else 0)} |")
    a(f"| **Toplam** | **{eur(tot)}** | 100% |")
    broker_total = sum((p.broker_value for p in run.positions), Decimal("0"))
    a("")
    a(f"Broker'ın kendi değerlemesi {eur(broker_total)}; mühürlü bid/ask ortalamasıyla fark {eur(run.positions_value - broker_total)}.")
    unreal = [p for p in run.positions if p.fifo_price and p.mid]
    if unreal:
        cost = sum((p.fifo_price * p.quantity for p in unreal), Decimal("0"))
        gain = sum(((p.mid - p.fifo_price) * p.quantity for p in unreal), Decimal("0"))
        a(f"Broker FIFO maliyetine göre gerçekleşmemiş kâr/zarar: **{eur(gain)}** ({pct(gain / cost * 100 if cost else 0, signed=True)}).")
    a("")
    a("## 2. Pozisyonlar (mühürlü fiyatlar)")
    a("")
    a("| ISIN | Rol | Fon | Adet | Bid | Ask | Mid | Değer | Ağırlık | Makas | FIFO maliyet | K/Z | Kalite |")
    a("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for p in run.positions:
        kz = (p.mid - p.fifo_price) * p.quantity if (p.fifo_price and p.mid) else None
        age = f" ({p.quote_age_seconds/3600:.1f} sa)" if p.quote_age_seconds and p.quote_age_seconds > 900 else ""
        a(f"| `{p.isin}` | {cfg.role(p.isin)} | {p.name} | {p.quantity} | {p.bid:.3f} | {p.ask:.3f} | {p.mid:.4f} | "
          f"{eur(p.value)} | {pct(p.value / tot * 100 if tot else 0)} | {pct(p.spread_pct)} | "
          f"{p.fifo_price if p.fifo_price else '—'} | {eur(kz)} | {p.quality}{age} |")
    a("")
    if run.performances:
        a("## 3. Fiyat performansı (Scalable)")
        a("")
        a("| ISIN | " + " | ".join(l for _, l in PERF_LABELS) + " |")
        a("|---|" + "---|" * len(PERF_LABELS))
        for p in run.positions:
            perf = run.performances.get(p.isin, {})
            a(f"| `{p.isin}` | " + " | ".join(pct(perf[k] * 100, 1, True) if k in perf else "—" for k, _ in PERF_LABELS) + " |")
        a("")
    a("## 4. Risk (1 yıllık `sc broker chart` serisi, quantstats)")
    a("")
    if any(metrics.values()):
        a("| ISIN | 1Y getiri | Yıllık oynaklık | Sharpe (rf=0) | Sortino | Maks. düşüş | Zirveden | ~200g ort. farkı |")
        a("|---|---|---|---|---|---|---|---|")
        rows = [(p.isin, metrics.get(p.isin)) for p in run.positions]
        if portfolio_metrics:
            rows.append(("**Bugünkü portföy (geriye dönük)**", portfolio_metrics))
        for name, m in rows:
            if m is None:
                a(f"| {name} | — | — | — | — | — | — | — |")
                continue
            a(f"| {name if name.startswith('**') else '`'+name+'`'} | {pct(m.total_return*100, 1, True)} | {pct(m.volatility*100, 1)} | "
              f"{m.sharpe:.2f} | {m.sortino:.2f} | {pct(m.max_drawdown*100, 1)} | {pct(m.from_high*100, 1)} | "
              f"{pct(m.trend_gap*100, 1, True) if m.trend_gap is not None else '—'} |")
        sample = next(m for m in metrics.values() if m)
        a("")
        a(f"Seri {sample.start} – {sample.end}, ~{sample.periods_per_year:.0f} gözlem/yıl (Scalable örneklemesi); "
          "yıllıklaştırma bu sıklıkla yapıldı. \"Bugünkü portföy\" satırı bugünkü adetlerin geçmişte tutulduğu varsayımıdır, gerçekleşmiş getiri değildir.")
        if corr is not None:
            a("")
            a("**Getiri korelasyonu**")
            a("")
            cols = list(corr.columns)
            a("| | " + " | ".join(f"`{c[-4:]}`" for c in cols) + " |")
            a("|---|" + "---|" * len(cols))
            for r in cols:
                a(f"| `{r[-4:]}` | " + " | ".join(f"{corr.loc[r, c]:.2f}" for c in cols) + " |")
    else:
        a("Fiyat geçmişi yok: `masa gecmis` çalıştırın.")
    a("")
    a("## 5. Gerçekleşmiş getiri (işlem geçmişinden)")
    a("")
    if realized is None or not realized.available:
        a(f"Hesaplanmadı. {realized.reason if realized else 'İşlem geçmişi mühürlenmemiş (`masa gecmis`).'}")
    else:
        a(f"Dönem {realized.start} – {realized.end}. Yatırılan {eur(realized.deposits)}, çekilen {eur(realized.withdrawals)}, "
          f"ücretler {eur(realized.fees)}; net kazanç **{eur(realized.gain)}**.")
        a("")
        a(f"- Zaman ağırlıklı getiri (TWR, kümülatif): **{pct(realized.twr_pct, 2, True)}**")
        a(f"- Modified Dietz: {pct(realized.mdietz_pct, 2, True)}")
        a(f"- XIRR / para ağırlıklı ({realized.xirr_status}): {pct(realized.xirr_pct, 2, True)}")
        a(f"- Nakit mutabakatı farkı: {eur(realized.cash_gap)}")
        for isin, (ours, broker) in realized.fifo_check.items():
            if ours is not None and broker is not None:
                a(f"- FIFO maliyet kontrolü `{isin}`: masa {float(ours):.4f} · broker {float(broker):.4f}")
        for w in realized.warnings:
            a(f"- ⚠️ {w}")
        if realized.ignored:
            a(f"- Kapsam dışı işlem türleri: {', '.join(realized.ignored[:8])}")
    a("")
    a("## 6. Tut / ekle / azalt değerlendirmesi (karar desteği)")
    a("")
    a(f"Eşikler `config/politika.json` · durum **{'ONAYLANDI' if cfg.policy.approved else 'TASLAK'}**. "
      "Bu bölüm emir değildir; sistem işlem yapmaz.")
    a("")
    for s in assessments:
        a(f"### `{s.isin}` — {s.label}")
        a(f"{s.name} · ağırlık {pct(s.weight*100, 1)}" + (f" · hedef {pct(s.target*100, 1)}" if s.target is not None else "")
          + (f" · K/Z {eur(s.unrealized_eur)} ({pct(s.unrealized_pct, 1, True)})" if s.unrealized_eur is not None else ""))
        a("")
        for r in s.reasons:
            a(f"- {r}")
        for n in s.notes:
            a(f"- _{n}_")
        ta = ta_results.get(s.isin)
        if ta:
            if ta.get("ok"):
                dec = (ta.get("reports", {}).get("final_trade_decision") or "")[:1200]
                a(f"- **TradingAgents görüşü ({ta.get('route') or ta.get('deep_think_llm')}):** {ta.get('rating')}")
                if dec:
                    a("")
                    a("  > " + dec.replace("\n", "\n  > "))
            else:
                a(f"- TradingAgents çalışmadı: {ta.get('error')}")
        a("")
    a("## 7. Yeniden dengeleme planı")
    a("")
    if plan is None:
        a("Hedef ağırlık tanımlı değil (`config/portfoy.json` → `hedef_agirliklar`); plan üretilmedi.")
    else:
        a(plan.trigger_rationale)
        a("")
        if plan.ordered_execution_plan:
            a("| Sıra | ISIN | İşlem | Adet | Fiyat | Tutar |")
            a("|---|---|---|---|---|---|")
            for o in plan.ordered_execution_plan:
                a(f"| {o.execution_sequence} | `{o.isin}` | {o.action.value} | {abs(o.shares_delta):g} | {o.target_price:.3f} | {eur(o.estimated_amount)} |")
    a("")
    if scan:
        a("## 8. Fırsat taraması")
        a("")
        a(f"Tarama `{scan['run_id']}`. Puan: 6A ve 1Y momentum, Sharpe, trend ve portföyle düşük korelasyonun z-skor bileşimi. "
          "\"ARAŞTIRMAYA DEĞER\" alım tavsiyesi değildir.")
        a("")
        a("| # | ISIN | Tür | Ad | Etiket | Puan | 6A | 1Y | Sharpe | Maks. düşüş | Makas | Portföy korel. |")
        a("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for i, c in enumerate(scan["candidates"], 1):
            m = c.metrics
            a(f"| {i} | `{c.isin}` | {c.group} | {c.name[:40]} | {c.label} | {c.score:.2f} | " if c.score is not None else
              f"| {i} | `{c.isin}` | {c.group} | {c.name[:40]} | {c.label} | — | ")
            L[-1] += (f"{pct(c.perf_6m*100, 1, True) if c.perf_6m is not None else '—'} | "
                      f"{pct(c.perf_1y*100, 1, True) if c.perf_1y is not None else '—'} | "
                      f"{f'{m.sharpe:.2f}' if m else '—'} | {pct(m.max_drawdown*100, 1) if m else '—'} | "
                      f"{pct(c.spread_pct) if c.spread_pct is not None else '—'} | "
                      f"{f'{c.corr_to_portfolio:.2f}' if c.corr_to_portfolio is not None else '—'} |")
        a("")
        for c in scan["candidates"]:
            if c.reasons:
                a(f"- `{c.isin}` {c.label}: " + " ".join(c.reasons))
            ta = ta_results.get(c.isin)
            if ta and ta.get("ok"):
                a(f"  - TradingAgents: **{ta.get('rating')}**")
        a("")
    a("## 9. Doğrulama ve denetim izi")
    a("")
    a(f"- Mühür zinciri (alan düzeyinde yeniden hesap): **{'GEÇERLİ' if integrity['snapshot_chain_ok'] else 'BOZUK — ' + str(integrity['snapshot_chain_error'])}**")
    a(f"- Denetim olayları zinciri: **{'GEÇERLİ' if integrity['audit_chain_ok'] else 'BOZUK — ' + str(integrity['audit_chain_error'])}** ({integrity['audit_events']} olay)")
    a(f"- SQLite {integrity['sqlite_version']} · journal `{integrity['journal_mode']}` · recursive_triggers {integrity['recursive_triggers']} · "
      f"{integrity['trigger_count']} değişmezlik tetikleyicisi · şema v{integrity['schema_version']}")
    a(f"- Zincir ucu: `{(integrity['chain_tip'] or '')[:16]}…` · mühürler: " +
      ", ".join(f"{k} `{v[:12]}…`" for k, v in run.hashes.items()))
    if critic_result is not None:
        critic_verdict_str = (
            "Kod kontrolünden geçti (APPROVE) — Bağımsız model denetimi: YOK"
            if critic_result.verdict.value == "APPROVE"
            else critic_result.verdict.value
        )
        a(f"- Red-team denetimi (fiyat mührü, toplamlar, korelasyon iddiaları): **{critic_verdict_str}** "
          f"({critic_result.defect_counts.fatal_defects} kritik, {critic_result.defect_counts.material_warnings} önemli)")
        for d in critic_result.identified_defects[:6]:
            a(f"  - {d.severity.value}: {d.target_claim_or_metric}")
    a("- Broker yazma yolu: kodda yok (yalnız whoami/context/holdings/cash/quote/transactions/chart okunur).")
    a("- Vergi: hesaplanmıyor (modül pasif). Bilgi: Sparer-Pauschbetrag 1.000 € (tek kişi) / 2.000 € (birlikte değerlendirme).")
    a("")
    a("---")
    a("*Karar desteği amaçlıdır; yatırım veya vergi danışmanlığı değildir. Tüm fiyatlar mühürlü Scalable verisidir; "
      "TradingAgents görüşleri harici model çıktısıdır ve kendi veri kaynağını (Yahoo) kullanır.*")
    return "\n".join(L) + "\n"
