"""
Memory Store — persists past analysis so the Trade Journal/Memory agent has
something to reason over. Serverless functions are stateless between calls,
so this needs an external store. Upstash Redis has a genuine free tier
(10,000 commands/day, REST-based — no VPS needed) and is used by default.
Falls back to a local JSON file if no Upstash credentials are set, which is
fine for local testing but won't persist across serverless invocations.
"""

import os
import json
import time
import requests

UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL")   # from upstash.com free tier
UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN")
LOCAL_FALLBACK_PATH = "journal_fallback.json"


def _upstash_configured():
    return bool(UPSTASH_URL and UPSTASH_TOKEN)


def _upstash_request(command: list):
    resp = requests.post(
        UPSTASH_URL, headers={"Authorization": f"Bearer {UPSTASH_TOKEN}"},
        json=command, timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("result")


def save_entry(symbol: str, entry: dict, keep_last: int = 20):
    entry = {**entry, "saved_at": time.time()}
    key = f"journal:{symbol.upper()}"

    if _upstash_configured():
        _upstash_request(["LPUSH", key, json.dumps(entry)])
        _upstash_request(["LTRIM", key, 0, keep_last - 1])
        return

    # local fallback
    data = {}
    if os.path.exists(LOCAL_FALLBACK_PATH):
        with open(LOCAL_FALLBACK_PATH) as f:
            data = json.load(f)
    data.setdefault(symbol.upper(), []).insert(0, entry)
    data[symbol.upper()] = data[symbol.upper()][:keep_last]
    with open(LOCAL_FALLBACK_PATH, "w") as f:
        json.dump(data, f)


def get_recent_entries(symbol: str, limit: int = 5):
    key = f"journal:{symbol.upper()}"

    if _upstash_configured():
        raw = _upstash_request(["LRANGE", key, 0, limit - 1]) or []
        return [json.loads(r) for r in raw]

    if not os.path.exists(LOCAL_FALLBACK_PATH):
        return []
    with open(LOCAL_FALLBACK_PATH) as f:
        data = json.load(f)
    return data.get(symbol.upper(), [])[:limit]
