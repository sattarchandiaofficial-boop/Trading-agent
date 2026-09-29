"""
specialist_agents.py — ALL judgment happens here, via the LLM.

Every agent: gather its slice of raw data (already computed by data_layer /
raw_detectors — nothing here invents new numbers), hand it to the model
with an open-ended prompt, return the model's own reasoning. No agent
contains an if/else deciding "bullish" or "strong" — that word always
comes from the model.
"""

from dataclasses import dataclass
from typing import Callable

from llm import chat_json, SPECIALIST_MODEL

RESPONSE_SHAPE = (
    '{"bias": "bullish|bearish|neutral", "confidence": 0-100, '
    '"key_points": ["..."], "summary": "2-3 sentence reasoning"}'
)

LANGUAGE_INSTRUCTION = (
    " Write the values of key_points and summary in Roman Urdu (Urdu written "
    "in Latin/English letters, mixed with English technical terms as a "
    "Pakistani trader would naturally speak) — conversational, not formal "
    "textbook Urdu. Keep the bias field itself in English (bullish/bearish/neutral)."
)


@dataclass
class SpecialistAgent:
    name: str
    label: str
    system_prompt: str
    gather_data: Callable[[dict], dict]


def run_agent(agent: SpecialistAgent, context: dict) -> dict:
    data = agent.gather_data(context)
    try:
        result = chat_json(
            SPECIALIST_MODEL,
            agent.system_prompt + LANGUAGE_INSTRUCTION + f" Respond ONLY in this JSON shape: {RESPONSE_SHAPE}",
            str(data)[:4000],
        )
        return {"agent": agent.name, "label": agent.label, **result}
    except Exception as e:
        return {"agent": agent.name, "label": agent.label, "error": str(e)}


# context keys available to every gather_data function (built in orchestrator.py):
#   symbol, price, candles, swings, structure, sr_levels, order_blocks, fvgs,
#   sweeps, kill_zone, ote, volatility, momentum, rsi_last, divergence,
#   regime, bocpd, mtf, correlation, news, cot, seasonality, anomaly,
#   risk_reward, journal

AGENTS = [
    SpecialistAgent(
        "price_action_structure", "Price Action / Structure",
        "You are a price action analyst. You get mechanically-detected swing "
        "points and structure breaks (BOS/CHOCH), no significance judged yet. "
        "Decide what the structure actually says about trend and momentum right now.",
        lambda ctx: {"symbol": ctx["symbol"], "price": ctx["price"],
                     "recent_swings": ctx["swings"][-8:], "structure": ctx["structure"]},
    ),
    SpecialistAgent(
        "support_resistance", "Support / Resistance",
        "You are an S/R analyst. You get candidate levels clustered from swing "
        "points, with touch counts and distance from price. Decide which levels "
        "genuinely matter right now and why.",
        lambda ctx: {"symbol": ctx["symbol"], "price": ctx["price"], "levels": ctx["sr_levels"][:8]},
    ),
    SpecialistAgent(
        "smc", "SMC",
        "You are a Smart Money Concepts analyst. You get candidate order blocks, "
        "fair value gaps (with a 'filled' flag), and liquidity sweeps, mechanically "
        "flagged with no judgment. Decide which matter given confluence and recency.",
        lambda ctx: {"symbol": ctx["symbol"], "price": ctx["price"],
                     "order_blocks": ctx["order_blocks"][-8:], "fvgs": ctx["fvgs"][-8:],
                     "sweeps": ctx["sweeps"][-8:]},
    ),
    SpecialistAgent(
        "ict", "ICT",
        "You are an ICT concepts analyst. You get the current kill-zone status and "
        "the Optimal Trade Entry (61.8%-79% fib) zone of the latest swing leg. "
        "Reason about session timing and OTE relevance right now.",
        lambda ctx: {"symbol": ctx["symbol"], "price": ctx["price"],
                     "kill_zone": ctx["kill_zone"], "ote_zone": ctx["ote"]},
    ),
    SpecialistAgent(
        "volatility", "Volatility",
        "You are a volatility analyst. You get current vs prior ATR. Decide "
        "whether the market is expanding, contracting, or coiling, and what that implies.",
        lambda ctx: {"symbol": ctx["symbol"], "volatility": ctx["volatility"]},
    ),
    SpecialistAgent(
        "momentum", "Momentum",
        "You are a momentum analyst. You get rate of change and consecutive "
        "candle streak data. Reason about directional strength and exhaustion risk.",
        lambda ctx: {"symbol": ctx["symbol"], "momentum": ctx["momentum"]},
    ),
    SpecialistAgent(
        "divergence", "Divergence",
        "You are a divergence analyst. You get candidate price/RSI divergence "
        "flags (mechanically detected). Decide whether they're meaningful given context.",
        lambda ctx: {"symbol": ctx["symbol"], "rsi_last": ctx["rsi_last"], "divergences": ctx["divergence"]},
    ),
    SpecialistAgent(
        "regime_trend_state", "Regime / Trend-State",
        "You are a market regime analyst. You get an HMM-fitted regime "
        "classification (bullish/bearish/sideways with probabilities and stay-probabilities) "
        "and a BOCPD changepoint probability (chance the regime just shifted). "
        "Reason about what state the market is in and how reliable that read is.",
        lambda ctx: {"symbol": ctx["symbol"], "hmm_regime": ctx["regime"], "bocpd": ctx["bocpd"]},
    ),
    SpecialistAgent(
        "multi_timeframe", "Multi-Timeframe Context",
        "You are a multi-timeframe analyst. You get recent candles from H1, H4 "
        "and D1. Decide whether the current-timeframe picture aligns or "
        "conflicts with the higher-timeframe trend.",
        lambda ctx: {"symbol": ctx["symbol"],
                     "h1_recent": _tail(ctx["mtf"].get("1h")), "h4_recent": _tail(ctx["mtf"].get("4h")),
                     "d1_recent": _tail(ctx["mtf"].get("1d"))},
    ),
    SpecialistAgent(
        "correlation_intermarket", "Correlation / Intermarket",
        "You are an intermarket correlation analyst. You get the rolling return "
        "correlation between this symbol and a related instrument. Reason about "
        "what that implies right now, and flag if the relationship looks unreliable "
        "(e.g. too few overlapping bars, or an error).",
        lambda ctx: {"symbol": ctx["symbol"], "correlation": ctx["correlation"]},
    ),
    SpecialistAgent(
        "seasonality", "Seasonality",
        "You are a seasonality analyst. You get computed average returns for the "
        "current and next calendar month, with a sample count and data span. "
        "Extract what tendency (if any) is credible; explicitly say if the "
        "sample size is too small to trust, since this is always a soft signal.",
        lambda ctx: {"symbol": ctx["symbol"], "seasonality": ctx["seasonality"]},
    ),
    SpecialistAgent(
        "fundamental_news", "Fundamental / News",
        "You are a news/fundamental analyst. You get upcoming scheduled economic "
        "events (medium/high impact) with minutes until release. Reason about "
        "which events could move this symbol soon and how a trader should weigh that risk.",
        lambda ctx: {"symbol": ctx["symbol"], "upcoming_events": ctx["news"]},
    ),
    SpecialistAgent(
        "market_sentiment_cot", "Market Sentiment / COT",
        "You are a COT positioning analyst. You get the last few weeks of CFTC "
        "speculator/commercial net positioning (weekly, not real-time). Extract "
        "the institutional positioning signal and its recent trend; note this "
        "reflects last week's data, not today.",
        lambda ctx: {"symbol": ctx["symbol"], "cot": ctx["cot"]},
    ),
    SpecialistAgent(
        "risk_reward", "Risk / Reward",
        "You are a risk-management analyst. You get the nearest support/resistance "
        "and computed long/short risk-reward ratios to those levels. Reason about "
        "whether this is a favorable risk setup right now, for longs and for shorts separately.",
        lambda ctx: {"symbol": ctx["symbol"], "price": ctx["price"], "risk_reward": ctx["risk_reward"]},
    ),
    SpecialistAgent(
        "trade_journal_memory", "Trade Journal / Memory",
        "You are a consistency analyst. You get this user's recent past analysis "
        "entries for this symbol (verdict, confidence, price at the time). Reason "
        "about whether the current read is consistent with recent context or a "
        "notable change, and flag any pattern in how recent calls played out.",
        lambda ctx: {"symbol": ctx["symbol"], "recent_entries": ctx["journal"]},
    ),
    SpecialistAgent(
        "anomaly_unusual_activity", "Anomaly / Unusual Activity",
        "You are an anomaly detector. You get the latest candle's range and its "
        "z-score versus the recent average range. Reason about whether this looks "
        "like unusual activity worth flagging, and what could explain it.",
        lambda ctx: {"symbol": ctx["symbol"], "anomaly": ctx["anomaly"]},
    ),
]


def _tail(candles, n=8):
    if not candles or isinstance(candles, dict):
        return candles  # {"error": ...} or None passes through as-is
    return candles[-n:]
