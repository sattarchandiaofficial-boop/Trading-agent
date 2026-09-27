"""
Orchestrator — the piece that ties everything together for one on-demand
analysis request. Fetches all raw data, computes all raw metrics, runs the
16 specialist agents in parallel, then the Head Agent, then journals the
result.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed

import data_layer as dl
import raw_detectors as rd
import memory_store as mem
from specialist_agents import AGENTS, run_agent
from head_agent import synthesize


def build_context(symbol: str) -> dict:
    """Fetches + computes every raw input every agent might need. This is
    the only place all the mechanical/mathematical work happens."""
    candles = dl.fetch_ohlc(symbol, interval="15m", outputsize=150)
    mtf_candles = dl.fetch_multi_timeframe(symbol, timeframes=("1h", "4h", "1d"))
    current_price = candles[-1]["close"]

    swings = rd.find_swing_points(candles)
    structure_breaks = rd.detect_structure_breaks(candles, swings)
    sr_levels = rd.detect_sr_levels(candles, swings)
    order_blocks = rd.detect_order_blocks(candles)
    fvgs = rd.detect_fair_value_gaps(candles)
    sweeps = rd.detect_liquidity_sweeps(candles)
    kill_zone = rd.current_kill_zone()
    ote = rd.detect_ote_zone(swings)
    volatility = rd.calc_volatility_state(candles)
    momentum = rd.calc_momentum(candles)
    rsi = rd.calc_rsi(candles)
    divergence = rd.detect_divergence_candidates(candles)
    regime = rd.calc_regime_hmm(candles)
    bocpd = rd.calc_bocpd_changepoint_probability(candles)
    anomaly = rd.detect_anomaly(candles)
    risk_reward = rd.calc_nearest_levels_rr(current_price, sr_levels)

    try:
        dxy_candles = dl.fetch_correlated_symbol("DXY", "15m", 150)
        correlation = rd.calc_correlation(candles, dxy_candles)
    except Exception as e:
        correlation = {"error": str(e)}

    try:
        news = dl.fetch_upcoming_news(currency="USD")
    except Exception as e:
        news = {"error": str(e)}

    try:
        cot = dl.fetch_cot_report(instrument=symbol)
    except Exception as e:
        cot = {"error": str(e)}

    try:
        seasonality = dl.fetch_seasonality(symbol)
    except Exception as e:
        seasonality = {"error": str(e)}

    journal_entries = mem.get_recent_entries(symbol, limit=5)

    return {
        "symbol": symbol, "current_price": current_price, "candles": candles,
        "mtf_candles": mtf_candles, "swings": swings, "structure_breaks": structure_breaks,
        "sr_levels": sr_levels, "order_blocks": order_blocks, "fvgs": fvgs, "sweeps": sweeps,
        "kill_zone": kill_zone, "ote": ote, "volatility": volatility, "momentum": momentum,
        "rsi_last": float(rsi[-1]), "divergence": divergence, "regime": regime, "bocpd": bocpd,
        "correlation": correlation, "news": news, "cot": cot, "seasonality": seasonality,
        "anomaly": anomaly, "risk_reward": risk_reward, "journal_entries": journal_entries,
    }


def run_single_agent_analysis(symbol: str, agent_name: str) -> dict:
    """
    Fast path — runs only one named specialist agent instead of all 17.
    Data is still fetched fresh (needed for an accurate read), but this
    skips the other 15 specialist LLM calls and the Head Agent call, so
    it's both quicker and cheaper on the Groq free-tier quota.
    """
    context = build_context(symbol)

    agent = next((a for a in AGENTS if a.name == agent_name), None)
    if agent is None:
        raise ValueError(f"Unknown agent: {agent_name}")

    output = run_agent(agent, context)
    return {
        "symbol": symbol,
        "current_price": context["current_price"],
        "mode": "single_agent",
        "specialist_outputs": [output],
        "verdict": None,  # no Head Agent synthesis in single-agent mode
    }


def run_full_analysis(symbol: str = "XAUUSD", max_workers: int = 16) -> dict:
    context = build_context(symbol)

    specialist_outputs = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run_agent, agent, context): agent.name for agent in AGENTS}
        for future in as_completed(futures):
            name = futures[future]
            try:
                specialist_outputs.append(future.result())
            except Exception as e:
                specialist_outputs.append({"agent": name, "error": str(e)})

    verdict = synthesize(context["symbol"], context["current_price"], specialist_outputs)

    mem.save_entry(symbol, {
        "verdict": verdict.get("verdict"),
        "confidence": verdict.get("confidence"),
        "price_at_analysis": context["current_price"],
    })

    return {
        "symbol": symbol,
        "current_price": context["current_price"],
        "specialist_outputs": specialist_outputs,
        "verdict": verdict,
    }
