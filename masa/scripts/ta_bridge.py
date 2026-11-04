"""TradingAgents koprusu — TradingAgents'in KENDI ortaminda calisir.

masa bu betigi ~/TradingAgents/.venv/bin/python ile, calisma
dizini TradingAgents olacak sekilde cagirir (o dizindeki .env model anahtarlarini
TradingAgents kendisi yukler; masa anahtarlari gormez). Girdi stdin JSON, cikti
stdout'ta tek satir JSON. Broker'a erisim yoktur; yalniz analiz uretir.
"""
import contextlib
import io
import json
import sys
import traceback


def main() -> int:
    req = json.loads(sys.stdin.read())
    out = {"ok": False, "ticker": req.get("ticker")}
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log):
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.graph.trading_graph import TradingAgentsGraph
            from tradingagents.portfolio import PortfolioContext
            import tradingagents

            config = DEFAULT_CONFIG.copy()
            if req.get("output_language"):
                config["output_language"] = req["output_language"]
            if req.get("max_debate_rounds"):
                config["max_debate_rounds"] = int(req["max_debate_rounds"])
            analysts = tuple(req.get("analysts") or ("market", "social", "news", "fundamentals"))
            book = PortfolioContext.model_validate(req["portfolio"]) if req.get("portfolio") else None
            graph = TradingAgentsGraph(selected_analysts=analysts, debug=False, config=config)
            state, rating = graph.propagate(req["ticker"], req["trade_date"],
                                            asset_type=req.get("asset_type", "stock"), portfolio=book)
        keys = ("market_report", "sentiment_report", "news_report", "fundamentals_report",
                "investment_plan", "trader_investment_plan", "final_trade_decision")
        out.update({"ok": True, "rating": rating, "version": getattr(tradingagents, "__version__", "?"),
                    "llm_provider": config.get("llm_provider"), "deep_think_llm": config.get("deep_think_llm"),
                    "quick_think_llm": config.get("quick_think_llm"),
                    "reports": {k: state.get(k) for k in keys if state.get(k)}})
    except Exception as exc:
        out.update({"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]})
    out["log_tail"] = log.getvalue()[-1500:]
    sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str) + "\n")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
