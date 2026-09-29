"""
memory_store.py — trade journal, via Upstash Redis REST API (free tier).
Running inside Termux means the process persists on the phone, but Upstash
is still used so history survives Termux restarts/reinstalls.
"""

import os
import json
import time

import requests

URL = lambda: os.environ.get("UPSTASH_REDIS_REST_URL")
TOKEN = lambda: os.environ.get("UPSTASH_REDIS_REST_TOKEN")
LOCAL_FALLBACK = os.path.expanduser("~/nexus_journal_fallback.json")


def _configured():
    return bool(URL() and TOKEN())


def _cmd(command: list):
    resp = requests.post(URL(), headers={"Authorization": f"Bearer {TOKEN()}"}, json=command, timeout=10)
    resp.raise_for_status()
    return resp.json().get("result")


def save_entry(symbol: str, entry: dict, keep_last: int = 20):
    entry = {**entry, "saved_at": time.time()}
    key = f"journal:{symbol.upper()}"
    if _configured():
        try:
            _cmd(["LPUSH", key, json.dumps(entry)])
            _cmd(["LTRIM", key, 0, keep_last - 1])
            return
        except requests.RequestException:
            pass  # fall through to local file rather than losing the entry

    data = {}
    if os.path.exists(LOCAL_FALLBACK):
        with open(LOCAL_FALLBACK) as f:
            data = json.load(f)
    data.setdefault(symbol.upper(), []).insert(0, entry)
    data[symbol.upper()] = data[symbol.upper()][:keep_last]
    with open(LOCAL_FALLBACK, "w") as f:
        json.dump(data, f)


def get_recent_entries(symbol: str, limit: int = 5):
    key = f"journal:{symbol.upper()}"
    if _configured():
        try:
            raw = _cmd(["LRANGE", key, 0, limit - 1]) or []
            return [json.loads(r) for r in raw]
        except requests.RequestException:
            pass

    if not os.path.exists(LOCAL_FALLBACK):
        return []
    with open(LOCAL_FALLBACK) as f:
        data = json.load(f)
    return data.get(symbol.upper(), [])[:limit]
