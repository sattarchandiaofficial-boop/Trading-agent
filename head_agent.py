"""
Head Agent — the synthesizer.

Deliberately does NOT use a hardcoded voting rule ("if 10/16 bullish -> Buy").
It is given all 16 specialists' reasoning and asked to weigh them itself —
noting agreement, conflict, and which agents' input matters most given the
current context. This mirrors how a human head trader reads a panel of
desk analysts, not a scoring formula.
"""

import os
import json
from groq import Groq

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MODEL = "llama-3.3-70b-versatile"
client = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = """You are the Head Trading Analyst. You will receive the
outputs of 16 specialist agents, each with their own bias, confidence, and
reasoning, covering price structure, SMC/ICT, momentum, volatility,
divergence, regime state, multi-timeframe context, intermarket correlation,
seasonality, news, COT positioning, risk/reward, trade journal consistency,
and anomalies.

Do not average or vote mechanically. Read their reasoning, note where they
agree and where they genuinely conflict, and decide which agents' input
should carry more weight given the current situation (e.g. news risk should
dominate right before a high-impact release; seasonality should carry very
little weight on its own). Form your own independent judgment.

Respond ONLY in this JSON shape:
{
  "verdict": "buy|sell|sideways",
  "confidence": 0-100,
  "agreement_summary": "which agents agreed and on what",
  "conflict_summary": "which agents disagreed and why that matters",
  "reasoning": "3-5 sentence final reasoning",
  "key_risk": "the single biggest thing that could invalidate this read"
}"""


def synthesize(symbol: str, current_price: float, specialist_outputs: list[dict]) -> dict:
    payload = {
        "symbol": symbol,
        "current_price": current_price,
        "specialist_outputs": specialist_outputs,
    }
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ],
        temperature=0.3,
    )
    return json.loads(resp.choices[0].message.content)
