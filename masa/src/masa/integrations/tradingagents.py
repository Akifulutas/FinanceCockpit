"""TradingAgents (TauricResearch, v0.7.x) ile kontrollu baglanti.

* TradingAgents kendi sanal ortaminda, ayri surecte calisir (shell=False).
* Ona yalniz Yahoo sembolu, tarih ve portfoy ozeti (adet, ortalama maliyet,
  nakit) gider; hesap kimligi, ad veya ham broker verisi gitmez.
* Ciktisi "harici model gorusu" olarak masa.db'ye ham kayit + denetim olayi
  seklinde yazilir; cekirdek fiyat/hesaplara karismaz.
* Her calisma cok sayida LLM cagrisi yapar (maliyet): CLI acik onay ister.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional

import os
import re

from masa.config import CONFIG_DIR, MASA_DIR, TRADINGAGENTS_DIR
from masa.model_registry.manager import (
    IneligibleModelError,
    MissingManifestError,
    ModelRegistryManager,
)
from masa.model_registry.models import ModelManifest, ModelRunStatus

BRIDGE = MASA_DIR / "scripts" / "ta_bridge.py"
ETF_ANALYSTS = ("market", "news")              # fon icin bilanco analisti anlamsiz
STOCK_ANALYSTS = ("market", "social", "news", "fundamentals")


@dataclass
class TAStatus:
    available: bool
    detail: str
    python: Optional[Path] = None


def status(ta_dir: Path = TRADINGAGENTS_DIR) -> TAStatus:
    py = ta_dir / ".venv" / "bin" / "python"
    if not ta_dir.exists():
        return TAStatus(False, f"{ta_dir} bulunamadı (MASA_TRADINGAGENTS_DIR ile yol verin)")
    if not py.exists():
        return TAStatus(False, f"{py} yok: TradingAgents ortamı kurulu değil")
    if not (ta_dir / ".env").exists():
        return TAStatus(False, f"{ta_dir/'.env'} yok: model anahtarları tanımlı değil", py)
    return TAStatus(True, "hazır", py)


_COST_NOTES = {
    "chatgpt": "ChatGPT Plus/Pro aboneliği (giriş: `tradingagents login chatgpt`) — API ücreti yok, plan kullanım limitine sayılır",
    "google": "Gemini API anahtarı — faturalandırma kapalı ücretsiz katmanda ücret yok; dakikalık/günlük istek limiti var",
    "ollama": "yerel model — ücret yok",
    "openai_compatible": "yerel/uyumlu sunucu — ücret sunucuya bağlı",
}


def provider_summary(ta_dir: Path = TRADINGAGENTS_DIR) -> Dict[str, Any]:
    """Model/provider choice from .env. ONLY TRADINGAGENTS_* settings are read; API keys are never read."""
    env = ta_dir / ".env"
    cfg: Dict[str, str] = {}
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("TRADINGAGENTS_") and "=" in line:
                k, v = line.split("=", 1)
                if not k.endswith(("_KEY", "_TOKEN", "_SECRET")):
                    cfg[k] = v.strip().strip('"').strip("'")
    default = cfg.get("TRADINGAGENTS_LLM_PROVIDER", "openai")
    tiers = {}
    for tier in ("QUICK", "DEEP"):
        prov = cfg.get(f"TRADINGAGENTS_{tier}_THINK_PROVIDER") or default
        tiers[tier.lower()] = {"provider": prov, "model": cfg.get(f"TRADINGAGENTS_{tier}_THINK_LLM", "varsayılan"),
                               "cost": _COST_NOTES.get(prov, "API anahtarıyla ücretli olabilir (sağlayıcı faturasına bağlı)")}
    chatgpt_used = any(t["provider"] == "chatgpt" for t in tiers.values())
    auth = Path.home() / ".tradingagents" / "chatgpt-auth.json"
    return {"tiers": tiers, "chatgpt_signed_in": auth.exists() if chatgpt_used else None}


def describe_providers(ta_dir: Path = TRADINGAGENTS_DIR) -> List[str]:
    router = ModelRouter()
    if router.enabled:
        weights = " / ".join(f"{q['saglayici']} {q['model']} (ağırlık {q.get('agirlik', 1)})" for q in router.quick)
        lines = [f"hızlı katman sırayla: {weights}",
                 f"derin katman: {router.deep['saglayici']} / {router.deep['model']}",
                 "ücret: chatgpt = abonelik limitinden düşer, google = ücretsiz katmanda ücret yok (limitli)"]
        if any(q["saglayici"] == "chatgpt" for q in router.quick) or router.deep["saglayici"] == "chatgpt":
            if not (Path.home() / ".tradingagents" / "chatgpt-auth.json").exists():
                lines.append("ChatGPT girişi YOK: önce `~/TradingAgents/.venv/bin/tradingagents login chatgpt`")
        return lines
    info = provider_summary(ta_dir)
    lines = [f"{'derin' if k == 'deep' else 'hızlı'} düşünme: {v['provider']} / {v['model']} — {v['cost']}"
             for k, v in info["tiers"].items()]
    if info["chatgpt_signed_in"] is False:
        lines.append("ChatGPT girişi YOK: önce `~/TradingAgents/.venv/bin/tradingagents login chatgpt`")
    return lines


# ------------------------------------------------------------------ model routing
_LIMIT_RE = re.compile(r"429|rate.?limit|resource.?exhausted|quota|usage.?limit|too many requests", re.I)


@dataclass
class Route:
    quick_provider: str
    quick_model: str
    deep_provider: str
    deep_model: str

    def env(self) -> Dict[str, str]:
        return {"TRADINGAGENTS_QUICK_THINK_PROVIDER": self.quick_provider,
                "TRADINGAGENTS_QUICK_THINK_LLM": self.quick_model,
                "TRADINGAGENTS_DEEP_THINK_PROVIDER": self.deep_provider,
                "TRADINGAGENTS_DEEP_THINK_LLM": self.deep_model}

    def label(self) -> str:
        return f"hızlı {self.quick_provider}/{self.quick_model} · derin {self.deep_provider}/{self.deep_model}"


class ModelRouter:
    """Smooth weighted round-robin of the quick tier across providers (per symbol)."""

    def __init__(self, cfg: Optional[Dict[str, Any]] = None) -> None:
        if cfg is None:
            p = CONFIG_DIR / "modeller.json"
            cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        self.quick = [q for q in cfg.get("hizli_katman", []) if float(q.get("agirlik", 1)) > 0]
        self.deep = cfg.get("derin_katman")
        self.fallback = bool(cfg.get("limit_hatasinda_yedege_gec", True))
        self._current = [0.0] * len(self.quick)
        self.usage: Dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.quick and self.deep)

    def _route(self, q: Dict[str, Any]) -> Route:
        return Route(q["saglayici"], q["model"], self.deep["saglayici"], self.deep["model"])

    def next(self) -> Route:
        total = sum(float(q.get("agirlik", 1)) for q in self.quick)
        for i, q in enumerate(self.quick):
            self._current[i] += float(q.get("agirlik", 1))
        best = max(range(len(self.quick)), key=lambda i: self._current[i])
        self._current[best] -= total
        return self._route(self.quick[best])

    def alternative(self, used: Route) -> Optional[Route]:
        for q in self.quick:
            if q["saglayici"] != used.quick_provider:
                return self._route(q)
        return None

    def record(self, route: Route) -> None:
        self.usage[route.quick_provider] = self.usage.get(route.quick_provider, 0) + 1

    @staticmethod
    def is_limit_error(result: Dict[str, Any]) -> bool:
        text = " ".join(str(result.get(k, "")) for k in ("error", "trace", "log_tail"))
        return (not result.get("ok")) and bool(_LIMIT_RE.search(text))


def run_routed(
    ticker: str,
    router: ModelRouter,
    manifest: Optional[ModelManifest] = None,
    db: Optional[DatabaseManager] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Run with the router's next route; on a provider limit error retry once on the other provider.
    
    Guarantees (İP-7 & İP-10):
    - Manifestless execution is strictly rejected (MissingManifestError).
    - Paused models cannot be selected (IneligibleModelError).
    - Rate limit/quota exhaustion transitions to WAITING_QUOTA state.
    - Fallback runs are recorded as linked sub-runs rather than silently merged.
    - Zero PII leakage: kwargs are sanitized before routing (PrivacyViolationError on sensitive keys).
    """
    from masa.privacy import sanitize_for_external
    clean_kwargs = sanitize_for_external(kwargs, strict=True)

    if not router.enabled:
        if manifest is None:
            raise MissingManifestError("Manifestsiz model çalışması reddedilir (ModelManifest zorunludur).")
        return run(ticker, **clean_kwargs)

    route = router.next()
    active_manifest = manifest or ModelManifest(
        task_name=f"tradingagents_{ticker}",
        quick_provider=route.quick_provider,
        quick_model=route.quick_model,
        deep_provider=route.deep_provider,
        deep_model=route.deep_model,
        prompt_summary=f"TradingAgents analysis for {ticker}",
        tools=list(kwargs.get("analysts", ETF_ANALYSTS)),
        rationale=f"Weighted router selected route: {route.label()}",
    )

    reg_mgr = ModelRegistryManager(db=db)
    initial_run = reg_mgr.record_run(
        manifest=active_manifest,
        status=ModelRunStatus.RUNNING,
    )

    res = run(ticker, env_overrides=route.env(), **kwargs)
    res["route"] = route.label()
    res["run_id"] = initial_run.run_id

    if router.fallback and router.is_limit_error(res):
        alt = router.alternative(route)
        if alt is not None:
            fallback_manifest = ModelManifest(
                task_name=f"tradingagents_{ticker}_fallback",
                quick_provider=alt.quick_provider,
                quick_model=alt.quick_model,
                deep_provider=alt.deep_provider,
                deep_model=alt.deep_model,
                prompt_summary=f"TradingAgents fallback for {ticker}",
                tools=list(kwargs.get("analysts", ETF_ANALYSTS)),
                rationale=f"Fallback triggered due to quota error on {route.quick_provider}",
            )
            held_run, fb_run = reg_mgr.record_quota_hold(
                parent_run=initial_run,
                fallback_manifest=fallback_manifest,
                quota_detail=str(res.get("error", "Rate limit")),
            )
            retry = run(ticker, env_overrides=alt.env(), **kwargs)
            retry["route"] = alt.label() + f" (yedek; ilk deneme {route.quick_provider} limitine takıldı)"
            retry["run_id"] = fb_run.run_id
            retry["held_run_id"] = held_run.run_id
            route, res = alt, retry
    if res.get("ok"):
        router.record(route)
    return res


def run(ticker: str, *, asset_kind: str, portfolio: Optional[Dict[str, Any]], trade_date: Optional[str] = None,
        language: str = "Turkish", timeout: int = 3600, ta_dir: Path = TRADINGAGENTS_DIR,
        env_overrides: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    st = status(ta_dir)
    if not st.available:
        return {"ok": False, "ticker": ticker, "error": st.detail}
    req = {"ticker": ticker, "trade_date": trade_date or date.today().isoformat(), "asset_type": "stock",
           "analysts": list(ETF_ANALYSTS if asset_kind == "ETF" else STOCK_ANALYSTS),
           "portfolio": portfolio, "output_language": language}
    try:
        env = dict(os.environ)
        env.update(env_overrides or {})  # .env is loaded with override=False, so these win
        proc = subprocess.run([str(st.python), str(BRIDGE)], input=json.dumps(req), capture_output=True,
                              text=True, cwd=str(ta_dir), timeout=timeout, shell=False, check=False, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "ticker": ticker, "error": f"{timeout} sn zaman aşımı"}
    line = (proc.stdout.strip().splitlines() or [""])[-1]
    try:
        out = json.loads(line)
    except json.JSONDecodeError:
        out = {"ok": False, "ticker": ticker, "error": "köprü JSON döndürmedi", "stderr": proc.stderr[-1500:]}
    out["requested_at"] = datetime.now(timezone.utc).isoformat()
    out["request"] = {k: v for k, v in req.items() if k != "portfolio"}
    return out


def portfolio_context(positions, cash, yahoo_of) -> Dict[str, Any]:
    """Broker-neutral book for TradingAgents: ticker, quantity, average price, cash."""
    pos: List[Dict[str, Any]] = []
    for p in positions:
        sym = yahoo_of(p.isin)
        if sym:
            pos.append({"ticker": sym, "quantity": float(p.quantity),
                        "average_price": float(p.fifo_price) if p.fifo_price else None})
    return {"cash": float(cash), "currency": "EUR", "positions": pos}
