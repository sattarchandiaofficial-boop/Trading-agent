"""
orchestrator.py — one on-demand analysis request, start to finish.

Fetches raw data, computes raw metrics, runs the 16 specialists (in a small
thread pool — phones have few cores and Groq's TPM budget serializes calls
anyway, see llm.py), then the Head Agent, then journals the result.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import data_layer as dl
import raw_detectors as rd
import memory_store as mem
from specialist_agents import AGENTS, run_agent
from head_agent import synthesize

MAX_WORKERS = 4  # keep this modest — phones have limited cores/RAM


def _safe(label, fn):
    try:
        return fn()
    except dl.DataError as e:
        return {"error": f"{label}: {e}"}
    except Exception as e:
        return {"error": f"{label}: unexpected error: {e}"}


def build_context(symbol: str) -> dict:
    candles = dl.fetch_ohlc(symbol, "15m", 150)
    price = candles[-1]["close"]

    swings = rd.find_swing_points(candles)
    structure = rd.detect_structure_breaks(candles, swings)
    sr_levels = rd.detect_sr_levels(candles, swings)
    rsi = rd.calc_rsi(candles)

    context = {
        "symbol": symbol, "price": price, "candles": candles,
        "swings": swings, "structure": structure, "sr_levels": sr_levels,
        "order_blocks": rd.detect_order_blocks(candles),
        "fvgs": rd.detect_fair_value_gaps(candles),
        "sweeps": rd.detect_liquidity_sweeps(candles),
        "kill_zone": rd.current_kill_zone(),
        "ote": rd.detect_ote_zone(swings),
        "volatility": rd.calc_volatility_state(candles),
        "momentum": rd.calc_momentum(candles),
        "rsi_last": None if len(rsi) == 0 or rsi[-1] != rsi[-1] else float(rsi[-1]),  # NaN-safe
        "divergence": rd.detect_divergence_candidates(candles),
        "anomaly": rd.detect_anomaly(candles),
        "risk_reward": rd.calc_risk_reward(price, sr_levels),
        "mtf": dl.fetch_multi_timeframe(symbol),
        "journal": _safe("journal", lambda: mem.get_recent_entries(symbol, 5)),
    }
    context["regime"] = _safe("regime", lambda: rd.calc_regime_hmm(candles))
    context["bocpd"] = _safe("bocpd", lambda: rd.calc_bocpd(candles))
    context["correlation"] = _safe("correlation", lambda: _correlate(symbol, candles))
    context["news"] = _safe("news", lambda: dl.fetch_upcoming_news(symbol))
    context["cot"] = _safe("cot", lambda: dl.fetch_cot(symbol))
    context["seasonality"] = _safe("seasonality", lambda: dl.fetch_seasonality(symbol))
    return context


def _correlate(symbol, candles):
    partner = dl.fetch_correlated(symbol)
    return rd.calc_correlation(candles, partner["candles"]) | {"partner": partner["partner"]}


def run_single_agent_analysis(symbol: str, agent_name: str) -> dict:
    """Fast path — one named specialist only, skips the other 15 + Head Agent."""
    context = build_context(symbol)
    agent = next((a for a in AGENTS if a.name == agent_name), None)
    if agent is None:
        raise ValueError(f"Unknown agent: {agent_name}")
    return {"symbol": symbol, "price": context["price"], "mode": "single_agent",
            "specialist_outputs": [run_agent(agent, context)], "verdict": None}


def run_full_analysis(symbol: str = "XAUUSD") -> dict:
    context = build_context(symbol)

    outputs = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(run_agent, a, context): a.name for a in AGENTS}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                outputs.append(fut.result())
            except Exception as e:
                outputs.append({"agent": name, "error": str(e)})

    verdict = synthesize(context["symbol"], context["price"], outputs)

    mem.save_entry(symbol, {"verdict": verdict.get("verdict"), "confidence": verdict.get("confidence"),
                            "price_at_analysis": context["price"]})

    return {"symbol": symbol, "price": context["price"], "mode": "full",
            "specialist_outputs": outputs, "verdict": verdict}
