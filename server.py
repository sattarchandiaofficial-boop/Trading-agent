"""
Server — the one HTTP endpoint the mobile tap-and-talk app calls.

Flow: audio in -> Groq Whisper (transcribe) -> Llama (figure out which
symbol was asked about) -> orchestrator.run_full_analysis -> gTTS (speak
the verdict) -> audio + text out.

Deploy this to any free-tier host that can run a Python web app (e.g. a
free Render/Fly.io/Railway tier) — it does not need to run on your own PC.
"""

import os
import io
import json
import tempfile

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from groq import Groq
from gtts import gTTS

from orchestrator import run_full_analysis, run_single_agent_analysis
from specialist_agents import AGENTS

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
client = Groq(api_key=GROQ_API_KEY)

AGENT_NAMES = [a.name for a in AGENTS]

# Device actions — executed locally by the Termux script on the phone, not
# here on the cloud backend (which has no access to the phone's hardware).
# This backend's only job for these is figuring out WHICH action was meant.
DEVICE_ACTIONS = {
    "open_whatsapp": "open WhatsApp",
    "open_youtube": "open YouTube",
    "open_chrome": "open Chrome browser",
    "torch_on": "turn on the flashlight",
    "torch_off": "turn off the flashlight",
    "volume_up": "increase volume",
    "volume_down": "decrease volume",
    "vibrate": "vibrate the phone",
    "read_battery": "check/read battery status",
    "read_time": "check/read current time",
}

app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

KNOWN_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]  # extend as you wire up more pairs


def transcribe(audio_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".webm") as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        with open(tmp.name, "rb") as f:
            result = client.audio.transcriptions.create(
                file=(tmp.name, f.read()), model="whisper-large-v3",
            )
    return result.text


def extract_symbol(transcribed_text: str) -> str:
    """Asks the model which known symbol the user meant — handles 'gold',
    'euro dollar', accents/misheard words, etc. instead of brittle keyword
    matching."""
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": (
                f"Identify which of these symbols the user is asking about: "
                f"{KNOWN_SYMBOLS}. Respond with ONLY the symbol string, nothing else. "
                f"If unclear, respond with the most likely one."
            )},
            {"role": "user", "content": transcribed_text},
        ],
        temperature=0,
    )
    guess = resp.choices[0].message.content.strip().upper()
    return guess if guess in KNOWN_SYMBOLS else "XAUUSD"


def extract_intent(transcribed_text: str) -> dict:
    """
    Figures out from the voice command whether the user wants:
    - one specific specialist agent's view,
    - a full 17-agent trading analysis,
    - a device action performed (open an app, flashlight, etc.), or
    - is just asking a general, non-trading question.
    """
    device_actions_desc = "; ".join(f"{k} = {v}" for k, v in DEVICE_ACTIONS.items())
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": (
                "Classify the user's voice command into exactly one of these categories:\n"
                f"1) one of these specialist agent names, if asking for that ONE agent's "
                f"trading view specifically: {AGENT_NAMES}\n"
                "2) 'full' if asking for a general/full trading analysis of a symbol\n"
                f"3) one of these device action keys, if asking the phone to do something: "
                f"{device_actions_desc}\n"
                "4) 'general' if none of the above — a general knowledge question, casual "
                "conversation, or anything unrelated to trading or device actions\n"
                "Respond with ONLY the exact matching key/name from above — nothing else."
            )},
            {"role": "user", "content": transcribed_text},
        ],
        temperature=0,
    )
    guess = resp.choices[0].message.content.strip()
    if guess in AGENT_NAMES:
        return {"mode": "single", "agent_name": guess}
    if guess in DEVICE_ACTIONS:
        return {"mode": "device_action", "action": guess}
    if guess == "general":
        return {"mode": "general"}
    return {"mode": "full"}


def answer_general_question(transcribed_text: str) -> str:
    """Plain Q&A — no trading pipeline, no data fetching, just the model."""
    resp = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a helpful voice assistant. Keep answers concise and conversational, suitable for being read aloud."},
            {"role": "user", "content": transcribed_text},
        ],
        temperature=0.5,
    )
    return resp.choices[0].message.content.strip()


def build_spoken_summary(result: dict) -> str:
    if result.get("mode") == "single_agent":
        out = result["specialist_outputs"][0]
        return (
            f"{result['symbol']} — {out['agent']} view: {out.get('bias')}, "
            f"{out.get('confidence')} percent confidence. {out.get('summary')}"
        )

    v = result["verdict"]
    return (
        f"{result['symbol']} is currently at {result['current_price']}. "
        f"My read is {v.get('verdict')}, with {v.get('confidence')} percent confidence. "
        f"{v.get('reasoning')} "
        f"Key risk to watch: {v.get('key_risk')}"
    )


def process_command(transcribed_text: str):
    """
    Shared pipeline for both /analyze (audio in, from the web app) and
    /analyze-text (text in, from Termux — which already has free on-device
    speech-to-text via termux-speech-to-text, so no need to re-transcribe
    or spend Groq Whisper quota on that path).
    """
    intent = extract_intent(transcribed_text)

    if intent["mode"] == "device_action":
        # No cloud TTS/audio here — the Termux script executes the action
        # locally and speaks its own confirmation via termux-tts-speak.
        return {
            "mode": "device_action",
            "action": intent["action"],
            "transcribed_text": transcribed_text,
        }

    if intent["mode"] == "general":
        answer = answer_general_question(transcribed_text)
        result = {"mode": "general", "answer": answer, "specialist_outputs": []}
        spoken_summary = answer
    else:
        symbol = extract_symbol(transcribed_text)
        if intent["mode"] == "single":
            result = run_single_agent_analysis(symbol, intent["agent_name"])
        else:
            result = run_full_analysis(symbol)
        spoken_summary = build_spoken_summary(result)

    tts = gTTS(spoken_summary)
    out_path = tempfile.mktemp(suffix=".mp3")
    tts.save(out_path)

    return FileResponse(
        out_path, media_type="audio/mpeg",
        headers={
            "X-Transcribed-Text": transcribed_text,
            "X-Analysis-JSON": json.dumps(result, default=str)[:8000],  # header size caution
        },
    )


@app.post("/analyze")
async def analyze(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()
    transcribed_text = transcribe(audio_bytes)
    return process_command(transcribed_text)


@app.post("/analyze-text")
async def analyze_text(payload: dict):
    """Used by the Termux hands-free loop — text already transcribed on-device."""
    transcribed_text = payload.get("text", "").strip()
    if not transcribed_text:
        return {"mode": "error", "message": "empty text"}
    return process_command(transcribed_text)


@app.get("/health")
async def health():
    return {"status": "ok"}
