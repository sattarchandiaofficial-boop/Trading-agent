"""
server.py — Nexus's local backend, running inside Termux on the phone itself.

Because this process runs ON the device, device actions (open an app, torch,
volume) are executed directly here via `termux-api` subprocess calls — no
separate script needs to interpret an action name. Both the web app (tap and
talk, audio upload) and the hands-free Termux loop (already-transcribed
text) talk to this same server at http://127.0.0.1:8765.
"""

import os
import json
import shutil
import subprocess

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from llm import chat_text, chat_json, transcribe, GENERAL_MODEL, HEAD_MODEL, LLMError
from orchestrator import run_full_analysis, run_single_agent_analysis
from specialist_agents import AGENTS

app = FastAPI(title="Nexus")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/app", StaticFiles(directory=_STATIC_DIR, html=True), name="static")

AGENT_NAMES = [a.name for a in AGENTS]

DEVICE_ACTIONS = {
    "open_whatsapp": "open WhatsApp",
    "open_youtube": "open YouTube",
    "open_chrome": "open Chrome browser",
    "torch_on": "turn on the flashlight",
    "torch_off": "turn off the flashlight",
    "volume_up": "increase media volume",
    "volume_down": "decrease media volume",
    "vibrate": "vibrate the phone",
    "read_battery": "check/read battery status",
    "read_time": "check/read current time",
}


class TextIn(BaseModel):
    text: str


# ---------------------------------------------------------------------------
# intent classification
# ---------------------------------------------------------------------------
def extract_intent(text: str) -> dict:
    actions_desc = "; ".join(f"{k} = {v}" for k, v in DEVICE_ACTIONS.items())
    try:
        result = chat_json(HEAD_MODEL, (
            "You are the router for Nexus, a forex/gold TRADING assistant. The "
            "user is almost always asking about trading, not general topics — "
            "when a word is ambiguous, assume the trading meaning. For example "
            "'regime' means market regime (trending/ranging/reversing), NOT the "
            "gold standard or a political regime. 'Structure' means price "
            "structure, not building structure. Classify the user's command into "
            'exactly one category. Respond ONLY with {"category": "<value>"} '
            "where <value> is one of:\n"
            f"1) a specialist agent name if asking for that ONE agent's trading view: {AGENT_NAMES}\n"
            "   (regime/trend-state questions -> 'regime_trend_state'; structure/BOS/CHOCH -> "
            "'price_action_structure'; order blocks/FVG/liquidity -> 'smc'; support/resistance -> "
            "'support_resistance'; kill zones/OTE -> 'ict'; RSI/divergence -> 'divergence'; "
            "news/events -> 'fundamental_news'; COT/positioning -> 'market_sentiment_cot')\n"
            "2) 'full' for a general/full trading analysis or verdict on a symbol (buy/sell/sideways)\n"
            f"3) a device action key if asking the phone to do something: {list(DEVICE_ACTIONS)}\n"
            "4) 'general' ONLY if truly unrelated to trading or this phone (e.g. 'what's the "
            "capital of France', casual chat)"
        ), text, max_tokens=30, temperature=0)
        guess = result.get("category", "general")
    except LLMError:
        guess = "general"

    if guess in AGENT_NAMES:
        return {"mode": "single", "agent_name": guess}
    if guess in DEVICE_ACTIONS:
        return {"mode": "device_action", "action": guess}
    return {"mode": "general"} if guess == "general" else {"mode": "full"}


def extract_symbol(text: str) -> str:
    known = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]
    try:
        result = chat_json(HEAD_MODEL,
            f"Which of these symbols is the user asking about: {known}? "
            f'Respond ONLY with {{"symbol": "<one of these>"}}. "Gold" means XAUUSD. '
            "If unclear, pick the most likely one.",
            text, max_tokens=20, temperature=0)
        guess = result.get("symbol", "").upper()
        return guess if guess in known else "XAUUSD"
    except LLMError:
        return "XAUUSD"


# ---------------------------------------------------------------------------
# device actions — executed directly, since this process runs on the phone
# ---------------------------------------------------------------------------
def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(cmd: list, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def execute_device_action(action: str) -> str:
    """Runs the action, returns a short spoken confirmation. Never raises —
    a missing Termux:API package should report itself, not crash the request."""
    try:
        if action == "open_whatsapp":
            _run(["termux-open-url", "whatsapp://send"]); return "WhatsApp khol raha hun."
        if action == "open_youtube":
            _run(["termux-open-url", "https://youtube.com"]); return "YouTube khol raha hun."
        if action == "open_chrome":
            _run(["termux-open-url", "https://google.com"]); return "Chrome khol raha hun."
        if action == "torch_on":
            _run(["termux-torch", "on"]); return "Flashlight on kar diya."
        if action == "torch_off":
            _run(["termux-torch", "off"]); return "Flashlight off kar diya."
        if action == "volume_up":
            _run(["termux-volume", "music", "15"]); return "Volume barha diya."
        if action == "volume_down":
            _run(["termux-volume", "music", "3"]); return "Volume kam kar diya."
        if action == "vibrate":
            _run(["termux-vibrate", "-d", "500"]); return "Vibrate kar raha hun."
        if action == "read_battery":
            out = _run(["termux-battery-status"])
            pct = json.loads(out.stdout).get("percentage", "unknown")
            return f"Battery {pct} percent hai."
        if action == "read_time":
            out = _run(["date", "+%I:%M %p"])
            return f"Waqt {out.stdout.strip()} hai."
        return "Ye kaam abhi mujhe nahi aata."
    except FileNotFoundError:
        return "Termux:API installed nahi hai, isliye ye nahi ho sakta. Terminal me likhein: pkg install termux-api"
    except Exception as e:
        return f"Ye kaam fail ho gaya: {e}"


# ---------------------------------------------------------------------------
# shared pipeline
# ---------------------------------------------------------------------------
def build_spoken_summary(result: dict) -> str:
    if result.get("mode") == "device_action":
        return result["spoken"]
    if result.get("mode") == "general":
        return result["answer"]
    if result.get("mode") == "single_agent":
        out = result["specialist_outputs"][0]
        if "error" in out:
            return f"{out['label']} agent me error aayi: {out['error']}"
        return f"{result['symbol']} — {out['label']}: {out.get('bias')}, {out.get('confidence')}% confidence. {out.get('summary')}"
    v = result["verdict"] or {}
    if v.get("error"):
        return f"{result['symbol']} ka analysis synthesis step pe fail ho gaya: {v['error']}"
    return (f"{result['symbol']} abhi {result['price']} pe hai. Mera verdict {v.get('verdict')} hai, "
            f"{v.get('confidence')} percent confidence ke saath. {v.get('reasoning')} "
            f"Sabse bada risk: {v.get('key_risk')}")


def process_command(text: str) -> dict:
    intent = extract_intent(text)

    if intent["mode"] == "device_action":
        spoken = execute_device_action(intent["action"])
        result = {"mode": "device_action", "action": intent["action"], "spoken": spoken, "transcribed_text": text}
    elif intent["mode"] == "general":
        try:
            answer = chat_text(GENERAL_MODEL,
                "You are a helpful voice assistant named Nexus. Keep answers concise "
                "and conversational, suitable for being read aloud. Reply in Roman "
                "Urdu (Urdu written in Latin/English letters, mixed with English "
                "words naturally where a Pakistani speaker would) unless the user "
                "wrote in a different language.", text)
        except LLMError as e:
            answer = f"Model tak nahi pohanch saka: {e}"
        result = {"mode": "general", "answer": answer, "specialist_outputs": []}
    else:
        symbol = extract_symbol(text)
        try:
            if intent["mode"] == "single":
                result = run_single_agent_analysis(symbol, intent["agent_name"])
            else:
                result = run_full_analysis(symbol)
        except Exception as e:
            result = {"mode": intent["mode"], "symbol": symbol, "specialist_outputs": [],
                      "verdict": {"error": str(e)}}

    result["spoken_summary"] = build_spoken_summary(result)
    return result


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
@app.post("/analyze-text")
async def analyze_text(payload: TextIn):
    """Used by the Termux hands-free loop (text already transcribed on-device
    for free via termux-speech-to-text) and can also be called directly."""
    text = payload.text.strip()
    if not text:
        return {"mode": "error", "spoken_summary": "I didn't catch any text."}
    return process_command(text)


@app.post("/analyze")
async def analyze(payload: dict):
    """
    Used by the web app: {"audio_base64": "..."} — transcribes via Groq
    Whisper first, then runs the same pipeline as /analyze-text.
    """
    import base64
    audio_b64 = payload.get("audio_base64", "")
    try:
        audio_bytes = base64.b64decode(audio_b64)
        text = transcribe(audio_bytes)
    except (LLMError, Exception) as e:
        return {"mode": "error", "spoken_summary": f"Transcription failed: {e}"}
    if not text:
        return {"mode": "error", "spoken_summary": "I didn't catch that — try again."}
    result = process_command(text)
    result["transcribed_text"] = text
    return result


@app.get("/health")
async def health():
    return {"status": "ok", "termux_api_installed": _have("termux-battery-status")}
