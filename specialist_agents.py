"""
Specialist Agents — ALL judgment happens here, via Llama 3.3 70B (Groq).

Every agent below follows the same shape: gather its slice of raw data
(already computed by raw_detectors.py / data_layer.py — nothing here
computes new raw facts), hand it to the model with an open-ended prompt,
and return the model's own reasoning. No agent contains an if/else that
decides "bullish" or "strong" — that word always comes from the model.
"""

import os
import json
from dataclasses import dataclass
from typing import Callable
from groq import Groq

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MODEL = "llama-3.3-70b-versatile"
client = Groq(api_key=GROQ_API_KEY)

RESPONSE_SHAPE = (
    '{"bias": "bullish|bearish|neutral", "confidence": 0-100, '
    '"key_points": ["..."], "summary": "2-3 sentence reasoning"}'
)


@dataclass
class SpecialistAgent:
    name: str
    system_prompt: str
    gather_data: Callable[[dict], dict]  # context -> raw data dict for this agent


def _call_llm(system_prompt: str, data: dict) -> dict:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt + f" Respond ONLY in this JSON shape: {RESPONSE_SHAPE}"},
            {"role": "user", "content": json.dumps(data, default=str)},
        ],
        temperature=0.3,
    )
    return json.loads(resp.choices[0].message.content)


def run_agent(agent: SpecialistAgent, context: dict) -> dict:
    data = agent.gather_data(context)
    result = _call_llm(agent.system_prompt, data)
    return {"agent": agent.name, **result}


# ---------------------------------------------------------------------------
# Agent definitions
# `context` (passed at run time) contains:
#   candles, swings, structure_breaks, sr_levels, order_blocks, fvgs, sweeps,
#   kill_zone, ote, volatility, momentum, rsi_last, divergence, regime,
#   bocpd, mtf_candles, correlation, news, cot, seasonality, anomaly,
#   risk_reward, journal_entries, symbol, current_price
# ---------------------------------------------------------------------------

AGENTS = [
    SpecialistAgent(
        name="price_action_structure",
        system_prompt=(
            "You are a price action / market structure analyst. You are given "
            "raw swing points and candidate structure breaks (BOS/CHOCH), "
            "mechanically flagged with no judgment on significance. Decide "
            "what the actual structure is telling us right now."
        ),
        gather_data=lambda ctx: {
            "symbol": ctx["symbol"], "current_price": ctx["current_price"],
            "recent_swings": ctx["swings"][-10:], "structure_breaks": ctx["structure_breaks"][-10:],
        },
    ),
    SpecialistAgent(
        name="support_resistance",
        system_prompt=(
            "You are a support/resistance analyst. You are given candidate S/R "
            "levels clustered from swing points, with touch counts and distance "
            "from current price. Decide which levels genuinely matter right now."
        ),
        gather_data=lambda ctx: {
            "symbol": ctx["symbol"], "current_price": ctx["current_price"],
            "candidate_levels": ctx["sr_levels"][:10],
        },
    ),
    SpecialistAgent(
        name="smc",
        system_prompt=(
            "You are a Smart Money Concepts analyst. You are given candidate "
            "order blocks, fair value gaps, and liquidity sweeps, mechanically "
            "flagged with no judgment. Decide which matter given confluence and "
            "recency, and what they suggest."
        ),
        gather_data=lambda ctx: {
            "symbol": ctx["symbol"], "current_price": ctx["current_price"],
            "order_blocks": ctx["order_blocks"][-10:], "fvgs": ctx["fvgs"][-10:], "sweeps": ctx["sweeps"][-10:],
        },
    ),
    SpecialistAgent(
        name="ict",
        system_prompt=(
            "You are an ICT (Inner Circle Trader) concepts analyst. You are "
            "given the current kill zone status and the Optimal Trade Entry "
            "(61.8%-79% fib) zone of the latest swing leg. Reason about session "
            "timing and OTE relevance right now."
        ),
        gather_data=lambda ctx: {
            "symbol": ctx["symbol"], "current_price": ctx["current_price"],
            "kill_zone": ctx["kill_zone"], "ote_zone": ctx["ote"],
        },
    ),
    SpecialistAgent(
        name="volatility",
        system_prompt=(
            "You are a volatility analyst. You are given current vs prior ATR. "
            "Decide whether the market is expanding, contracting, or coiling, "
            "and what that implies."
        ),
        gather_data=lambda ctx: {"symbol": ctx["symbol"], "volatility": ctx["volatility"]},
    ),
    SpecialistAgent(
        name="momentum",
        system_prompt=(
            "You are a momentum analyst. You are given rate of change and "
            "consecutive candle streak data. Reason about directional strength "
            "and exhaustion risk."
        ),
        gather_data=lambda ctx: {"symbol": ctx["symbol"], "momentum": ctx["momentum"]},
    ),
    SpecialistAgent(
        name="divergence",
        system_prompt=(
            "You are a divergence analyst. You are given candidate price/RSI "
            "divergence flags (mechanically detected, not judged). Decide "
            "whether they're meaningful given context."
        ),
        gather_data=lambda ctx: {
            "symbol": ctx["symbol"], "rsi_last": ctx["rsi_last"], "divergence_candidates": ctx["divergence"],
        },
    ),
    SpecialistAgent(
        name="regime_trend_state",
        system_prompt=(
            "You are a market regime analyst. You are given an HMM-fitted "
            "regime classification (bullish/bearish/sideways with "
            "probabilities) and a BOCPD changepoint probability (chance the "
            "regime just shifted). Reason about what state the market is "
            "actually in and how reliable that read is right now."
        ),
        gather_data=lambda ctx: {"symbol": ctx["symbol"], "hmm_regime": ctx["regime"], "bocpd": ctx["bocpd"]},
    ),
    SpecialistAgent(
        name="multi_timeframe",
        system_prompt=(
            "You are a multi-timeframe context analyst. You are given recent "
            "candles from H1, H4, and D1. Decide whether the current-timeframe "
            "picture aligns or conflicts with the higher-timeframe trend."
        ),
        gather_data=lambda ctx: {
            "symbol": ctx["symbol"],
            "h1_recent": ctx["mtf_candles"].get("1h", [])[-10:],
            "h4_recent": ctx["mtf_candles"].get("4h", [])[-10:],
            "d1_recent": ctx["mtf_candles"].get("1d", [])[-10:],
        },
    ),
    SpecialistAgent(
        name="correlation_intermarket",
        system_prompt=(
            "You are an intermarket correlation analyst. You are given the "
            "rolling correlation coefficient between this symbol and a related "
            "instrument (e.g. DXY). Reason about what that relationship implies "
            "right now, and flag if it's breaking down."
        ),
        gather_data=lambda ctx: {"symbol": ctx["symbol"], "correlation": ctx["correlation"]},
    ),
    SpecialistAgent(
        name="seasonality",
        system_prompt=(
            "You are a seasonality analyst. You are given raw scraped "
            "historical seasonal performance text for this symbol and the "
            "current month. Extract what tendency (if any) is credible, and "
            "how much weight it deserves — seasonality is a soft signal, say so "
            "if the data is weak or ambiguous."
        ),
        gather_data=lambda ctx: {"symbol": ctx["symbol"], "seasonality_data": ctx["seasonality"]},
    ),
    SpecialistAgent(
        name="fundamental_news",
        system_prompt=(
            "You are a fundamental/news analyst. You are given a raw list of "
            "upcoming scheduled economic events with impact ratings. Reason "
            "about which events could move this symbol soon and how a trader "
            "should account for that risk."
        ),
        gather_data=lambda ctx: {"symbol": ctx["symbol"], "upcoming_events": ctx["news"]},
    ),
    SpecialistAgent(
        name="market_sentiment_cot",
        system_prompt=(
            "You are a COT (Commitments of Traders) positioning analyst. You "
            "are given a raw CFTC report excerpt (weekly data, not real-time). "
            "Extract institutional positioning signal from it and reason about "
            "what it implies, noting it reflects last week's data."
        ),
        gather_data=lambda ctx: {"symbol": ctx["symbol"], "cot_report": ctx["cot"]},
    ),
    SpecialistAgent(
        name="risk_reward",
        system_prompt=(
            "You are a risk management analyst. You are given the nearest "
            "support/resistance levels and a computed risk-reward ratio. "
            "Reason about whether this is a favorable risk setup right now."
        ),
        gather_data=lambda ctx: {
            "symbol": ctx["symbol"], "current_price": ctx["current_price"], "risk_reward": ctx["risk_reward"],
        },
    ),
    SpecialistAgent(
        name="trade_journal_memory",
        system_prompt=(
            "You are a trading consistency analyst. You are given this user's "
            "recent past analysis entries for this symbol. Reason about "
            "whether the current read is consistent with recent context, or a "
            "notable change, and flag any pattern in how recent calls played out."
        ),
        gather_data=lambda ctx: {"symbol": ctx["symbol"], "recent_journal_entries": ctx["journal_entries"]},
    ),
    SpecialistAgent(
        name="anomaly_unusual_activity",
        system_prompt=(
            "You are an anomaly detection analyst. You are given the latest "
            "candle's range and its z-score versus the recent average range. "
            "Reason about whether this looks like unusual/abnormal activity "
            "worth flagging, and what could explain it."
        ),
        gather_data=lambda ctx: {"symbol": ctx["symbol"], "anomaly": ctx["anomaly"]},
    ),
]
