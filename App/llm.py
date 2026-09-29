"""
llm.py — minimal Groq client using plain `requests` (no SDK, so nothing
needs compiling on Termux).

Why the pacing code exists: Groq's free tier caps tokens per minute and per
day per model (roughly 6K TPM / 500K TPD on llama-3.1-8b-instant and
12K TPM / 100K TPD on llama-3.3-70b-versatile). Sixteen agents firing at once
would just get 429 errors, so calls wait for token budget and retry on 429.
"""

import os
import re
import json
import time
import threading
from collections import deque

import requests

GROQ_BASE = "https://api.groq.com/openai/v1"

SPECIALIST_MODEL = os.environ.get("SPECIALIST_MODEL", "llama-3.1-8b-instant")
HEAD_MODEL = os.environ.get("HEAD_MODEL", "llama-3.3-70b-versatile")
GENERAL_MODEL = os.environ.get("GENERAL_MODEL", "llama-3.1-8b-instant")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "whisper-large-v3")

# Conservative per-minute token budgets (a bit under Groq's published limits).
TPM_LIMITS = {
    "llama-3.1-8b-instant": int(os.environ.get("TPM_8B", "5000")),
    "llama-3.3-70b-versatile": int(os.environ.get("TPM_70B", "9000")),
}
DEFAULT_TPM = int(os.environ.get("TPM_DEFAULT", "5000"))


class LLMError(Exception):
    pass


class Budget:
    """Sliding-window token budget, one window per model."""

    def __init__(self, window_seconds: float = 60.0):
        self.window = window_seconds
        self.lock = threading.Lock()
        self.events = {}  # model -> deque[(timestamp, tokens)]

    def acquire(self, model: str, tokens: int, limit: int):
        while True:
            with self.lock:
                q = self.events.setdefault(model, deque())
                now = time.monotonic()
                while q and now - q[0][0] >= self.window:
                    q.popleft()
                used = sum(t for _, t in q)
                # A single call bigger than the whole budget must not deadlock.
                if used + tokens <= limit or not q:
                    q.append((now, tokens))
                    return
                wait = self.window - (now - q[0][0]) + 0.05
            time.sleep(max(wait, 0.05))


BUDGET = Budget()


def _api_key() -> str:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise LLMError("GROQ_API_KEY is not set")
    return key


def _retry_after_seconds(resp) -> float:
    header = resp.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    m = re.search(r"try again in (?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", resp.text or "")
    if m and (m.group(1) or m.group(2)):
        return float(m.group(1) or 0) * 60 + float(m.group(2) or 0)
    return 10.0


def _estimate_tokens(text: str) -> int:
    return int(len(text) / 3.5) + 1


def _post(path: str, **kwargs):
    """POST with retry on 429 / 5xx. Returns the parsed JSON body."""
    headers = {"Authorization": f"Bearer {_api_key()}"}
    last = None
    for attempt in range(6):
        try:
            resp = requests.post(f"{GROQ_BASE}{path}", headers=headers, timeout=90, **kwargs)
        except requests.RequestException as e:
            last = f"network error: {e}"
            time.sleep(2 + attempt * 2)
            continue

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            wait = min(_retry_after_seconds(resp) + 0.5, 65.0)
            last = f"rate limited (waited {wait:.0f}s)"
            # A per-DAY limit reports a long wait; don't sit on it forever.
            if wait > 65:
                raise LLMError("Groq daily token limit reached. Try again later.")
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            last = f"server error {resp.status_code}"
            time.sleep(2 + attempt * 2)
            continue
        raise LLMError(f"Groq error {resp.status_code}: {resp.text[:300]}")
    raise LLMError(f"Groq request failed after retries ({last})")


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise LLMError(f"Model did not return JSON: {text[:200]}")


def chat_json(model: str, system: str, user: str, max_tokens: int = 200,
              temperature: float = 0.3) -> dict:
    limit = TPM_LIMITS.get(model, DEFAULT_TPM)
    BUDGET.acquire(model, _estimate_tokens(system) + _estimate_tokens(user) + max_tokens, limit)
    body = _post("/chat/completions", json={
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    })
    return _extract_json(body["choices"][0]["message"]["content"])


def chat_text(model: str, system: str, user: str, max_tokens: int = 400,
              temperature: float = 0.5) -> str:
    limit = TPM_LIMITS.get(model, DEFAULT_TPM)
    BUDGET.acquire(model, _estimate_tokens(system) + _estimate_tokens(user) + max_tokens, limit)
    body = _post("/chat/completions", json={
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    })
    return body["choices"][0]["message"]["content"].strip()


def transcribe(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    body = _post("/audio/transcriptions",
                 files={"file": (filename, audio_bytes)},
                 data={"model": WHISPER_MODEL})
    return (body.get("text") or "").strip()
