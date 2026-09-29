"""
head_agent.py — the synthesizer.

Deliberately does NOT use a hardcoded voting rule ("if 10/16 bullish -> Buy").
It reads every specialist's reasoning and decides its own weighting — e.g.
news should dominate right before a high-impact release; seasonality should
carry very little weight alone. This mirrors a human head trader reading a
panel of desk analysts, not a scoring formula.
"""

from llm import chat_json, HEAD_MODEL

SYSTEM_PROMPT = """You are the Head Trading Analyst. You receive outputs from
16 specialist agents covering price structure, SMC/ICT, momentum, volatility,
divergence, regime state, multi-timeframe context, intermarket correlation,
seasonality, news, COT positioning, risk/reward, trade journal consistency,
and anomalies. Some specialists may report an error (e.g. a feed was
unavailable) — treat those as missing input, not as a signal either way.

Do not average or vote mechanically. Read their reasoning, note where they
agree and where they genuinely conflict, and decide which agents' input
should carry more weight given the current situation (e.g. news risk should
dominate right before a high-impact release; seasonality alone should carry
very little weight). Form your own independent judgment.

Write the values of agreement_summary, conflict_summary, reasoning and
key_risk in Roman Urdu (Urdu written in Latin/English letters, mixed with
English technical terms as a Pakistani trader would naturally speak) —
conversational, not formal textbook Urdu. Keep the verdict field itself in
English (buy/sell/sideways).

Respond ONLY in this JSON shape:
{
  "verdict": "buy|sell|sideways",
  "confidence": 0-100,
  "agreement_summary": "which agents agreed and on what",
  "conflict_summary": "which agents disagreed and why that matters",
  "reasoning": "3-5 sentence final reasoning",
  "key_risk": "the single biggest thing that could invalidate this read"
}"""


def synthesize(symbol: str, price: float, specialist_outputs: list) -> dict:
    payload = {"symbol": symbol, "price": price, "specialist_outputs": specialist_outputs}
    try:
        return chat_json(HEAD_MODEL, SYSTEM_PROMPT, str(payload)[:6000], max_tokens=500)
    except Exception as e:
        return {"verdict": "sideways", "confidence": 0, "error": str(e),
                "reasoning": "Head agent call failed; treat this as no signal.",
                "key_risk": "Synthesis unavailable — do not trade on this response."}
