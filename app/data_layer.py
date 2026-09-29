"""
data_layer.py — mechanical fetching only, no judgment.

No browser is needed anywhere in this file. Every source is a plain HTTP
feed, so it runs fine on a phone in Termux:

  * Price candles ........ API Ninjas (gold, free key) / Twelve Data (forex, optional free key)
  * Economic calendar .... Forex Factory's public weekly JSON feed (no key)
  * COT positioning ...... CFTC's official public API (no key)
  * Seasonality .......... computed here from daily candles (objective arithmetic)
"""

import os
import time
import threading
from datetime import datetime, timezone, timedelta

import requests

API_NINJAS_KEY = lambda: os.environ.get("API_NINJAS_KEY")
TWELVE_DATA_KEY = lambda: os.environ.get("TWELVE_DATA_KEY")

INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
CACHE_SECONDS = {"1m": 30, "5m": 60, "15m": 60, "30m": 120, "1h": 300, "4h": 600, "1d": 1800}
TWELVE_INTERVALS = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1day"}

# Per-symbol static facts (which currencies move it, which CFTC contract tracks it).
SYMBOLS = {
    "XAUUSD": {"name": "Gold", "currencies": ["USD"], "cot_code": "088691", "kind": "gold"},
    "EURUSD": {"name": "EUR/USD", "currencies": ["EUR", "USD"], "cot_code": "099741", "kind": "forex", "td": "EUR/USD"},
    "GBPUSD": {"name": "GBP/USD", "currencies": ["GBP", "USD"], "cot_code": "096742", "kind": "forex", "td": "GBP/USD"},
    "USDJPY": {"name": "USD/JPY", "currencies": ["USD", "JPY"], "cot_code": "097741", "kind": "forex", "td": "USD/JPY"},
}

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Nexus assistant)"}


class DataError(Exception):
    pass


# --------------------------------------------------------------------------
# tiny TTL cache (protects the free API quotas, e.g. API Ninjas = 3,000/month)
# --------------------------------------------------------------------------
_cache = {}
_cache_lock = threading.Lock()


def _cached(key, ttl, producer, allow_stale_on_error=False):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[1] > now:
            return hit[0]
    try:
        value = producer()
    except Exception:
        if allow_stale_on_error and hit:
            return hit[0]
        raise
    with _cache_lock:
        _cache[key] = (value, now + ttl)
    return value


def _get_json(url, **kwargs):
    try:
        resp = requests.get(url, headers=kwargs.pop("headers", HTTP_HEADERS), timeout=20, **kwargs)
    except requests.RequestException as e:
        raise DataError(f"network error calling {url.split('?')[0]}: {e}")
    if resp.status_code != 200:
        raise DataError(f"{url.split('?')[0]} returned HTTP {resp.status_code}: {resp.text[:150]}")
    try:
        return resp.json()
    except ValueError:
        raise DataError(f"{url.split('?')[0]} did not return JSON (rate limited?)")


# --------------------------------------------------------------------------
# price candles
# --------------------------------------------------------------------------
def _normalize(rows):
    out = []
    for r in rows:
        out.append({
            "time": int(r["time"]),
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
            "volume": float(r.get("volume") or 0),
        })
    out.sort(key=lambda c: c["time"])
    return out


def _ninjas_candles(endpoint, params, interval, outputsize):
    key = API_NINJAS_KEY()
    if not key:
        raise DataError("API_NINJAS_KEY is not set")
    sec = INTERVAL_SECONDS[interval]
    # The API only returns the LAST 24 HOURS unless start/end are given, and
    # markets close on weekends, so ask for a generously wide window.
    span = int(outputsize * sec * 1.8) + 3 * 86400
    now = int(time.time())
    params = dict(params, period=interval, start=now - span, end=now)
    data = _get_json(f"https://api.api-ninjas.com/v1/{endpoint}", params=params,
                     headers={"X-Api-Key": key})
    if not isinstance(data, list):
        raise DataError(f"API Ninjas: {str(data)[:150]}")
    if not data:
        raise DataError("API Ninjas returned no candles (market closed or plan limit)")
    return _normalize(data)[-outputsize:]


def _twelve_candles(symbol_info, interval, outputsize):
    key = TWELVE_DATA_KEY()
    if not key:
        raise DataError("Forex pairs need a free TWELVE_DATA_KEY (twelvedata.com, no card). "
                        "API Ninjas' free plan only covers gold.")
    data = _get_json("https://api.twelvedata.com/time_series", params={
        "symbol": symbol_info["td"], "interval": TWELVE_INTERVALS[interval],
        "outputsize": min(outputsize, 5000), "apikey": key,
    })
    if data.get("status") == "error" or "values" not in data:
        raise DataError(f"Twelve Data: {data.get('message', str(data)[:150])}")
    rows = []
    for v in data["values"]:
        fmt = "%Y-%m-%d %H:%M:%S" if " " in v["datetime"] else "%Y-%m-%d"
        ts = datetime.strptime(v["datetime"], fmt).replace(tzinfo=timezone.utc)
        rows.append({"time": int(ts.timestamp()), "open": v["open"], "high": v["high"],
                     "low": v["low"], "close": v["close"], "volume": v.get("volume", 0)})
    return _normalize(rows)[-outputsize:]


def fetch_ohlc(symbol: str = "XAUUSD", interval: str = "15m", outputsize: int = 150):
    """Candles oldest -> newest: [{time, open, high, low, close, volume}, ...]"""
    symbol = symbol.upper()
    info = SYMBOLS.get(symbol)
    if not info:
        raise DataError(f"Unsupported symbol {symbol}. Supported: {', '.join(SYMBOLS)}")
    if interval not in INTERVAL_SECONDS:
        raise DataError(f"Unsupported interval {interval}")

    def produce():
        if info["kind"] == "gold":
            return _ninjas_candles("goldpricehistorical", {}, interval, outputsize)
        return _twelve_candles(info, interval, outputsize)

    return _cached(("ohlc", symbol, interval, outputsize), CACHE_SECONDS[interval], produce)


def fetch_multi_timeframe(symbol: str, timeframes=("1h", "4h", "1d")):
    """{tf: candles or {"error": ...}} — one bad timeframe must not sink the rest."""
    out = {}
    for tf in timeframes:
        try:
            out[tf] = fetch_ohlc(symbol, tf, 60)
        except DataError as e:
            out[tf] = {"error": str(e)}
    return out


def fetch_correlated(symbol: str, interval: str = "1h", outputsize: int = 120):
    """
    Best-effort related instrument for the Correlation agent.
    Gold -> silver via API Ninjas (may be a premium endpoint on some plans;
    if so this raises DataError and the agent reports 'no data').
    """
    symbol = symbol.upper()
    if SYMBOLS.get(symbol, {}).get("kind") == "gold":
        candles = _cached(
            ("corr", "silver", interval, outputsize), CACHE_SECONDS[interval],
            lambda: _ninjas_candles("commoditypricehistorical", {"name": "silver"}, interval, outputsize))
        return {"partner": "silver", "candles": candles}
    raise DataError("No free correlated-instrument feed configured for this symbol yet")


# --------------------------------------------------------------------------
# economic calendar — Forex Factory public weekly JSON (rate-limited: cache 1h)
# --------------------------------------------------------------------------
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


def fetch_upcoming_news(symbol: str):
    info = SYMBOLS.get(symbol.upper())
    if not info:
        raise DataError("Unsupported symbol")
    raw = _cached(("ff",), 3600, lambda: _get_json(FF_URL), allow_stale_on_error=True)
    if not isinstance(raw, list):
        raise DataError("Economic calendar feed returned an unexpected format")

    now = datetime.now(timezone.utc)
    events = []
    for e in raw:
        if e.get("country") not in info["currencies"]:
            continue
        if e.get("impact") not in ("High", "Medium"):
            continue
        try:
            when = datetime.fromisoformat(e["date"])
        except (KeyError, ValueError):
            continue
        minutes = int((when - now).total_seconds() // 60)
        if minutes < -180:
            continue
        events.append({
            "event": e.get("title"), "currency": e.get("country"), "impact": e.get("impact"),
            "minutes_from_now": minutes, "forecast": e.get("forecast") or None,
            "previous": e.get("previous") or None,
        })
    events.sort(key=lambda x: x["minutes_from_now"])
    return {"source": "Forex Factory weekly feed", "events": events[:10],
            "note": None if events else "No medium/high impact events left this week for these currencies"}


# --------------------------------------------------------------------------
# COT — CFTC official Socrata API (legacy, futures only), weekly data
# --------------------------------------------------------------------------
COT_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"


def _num(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def fetch_cot(symbol: str):
    info = SYMBOLS.get(symbol.upper())
    if not info:
        raise DataError("Unsupported symbol")

    def produce():
        return _get_json(COT_URL, params={
            "cftc_contract_market_code": info["cot_code"],
            "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 4,
        })

    rows = _cached(("cot", info["cot_code"]), 6 * 3600, produce, allow_stale_on_error=True)
    if not isinstance(rows, list) or not rows:
        raise DataError("CFTC returned no COT rows")

    weeks = []
    for r in rows:
        nl, ns = _num(r.get("noncomm_positions_long_all")), _num(r.get("noncomm_positions_short_all"))
        cl, cs = _num(r.get("comm_positions_long_all")), _num(r.get("comm_positions_short_all"))
        weeks.append({
            "report_date": (r.get("report_date_as_yyyy_mm_dd") or "")[:10],
            "speculators_long": nl, "speculators_short": ns,
            "speculators_net": None if nl is None or ns is None else nl - ns,
            "commercials_net": None if cl is None or cs is None else cl - cs,
            "open_interest": _num(r.get("open_interest_all")),
        })
    for i in range(len(weeks) - 1):
        a, b = weeks[i]["speculators_net"], weeks[i + 1]["speculators_net"]
        weeks[i]["speculators_net_change_vs_prior_week"] = None if a is None or b is None else a - b
    return {"source": "CFTC legacy futures-only (weekly, Tuesday snapshot)",
            "market": rows[0].get("market_and_exchange_names"), "weeks_newest_first": weeks}


# --------------------------------------------------------------------------
# seasonality — computed from daily candles
# --------------------------------------------------------------------------
def compute_seasonality(candles):
    """Average % change per calendar month from daily candles (pure arithmetic)."""
    month_close = {}
    for c in candles:  # oldest -> newest, so the last write per month is month-end
        d = datetime.fromtimestamp(c["time"], tz=timezone.utc)
        month_close[(d.year, d.month)] = c["close"]

    keys = sorted(month_close)
    by_month = {m: [] for m in range(1, 13)}
    for prev, cur in zip(keys, keys[1:]):
        expected = (prev[0] + (prev[1] // 12), prev[1] % 12 + 1)
        if cur != expected:  # gap in the data — skip rather than fake a return
            continue
        by_month[cur[1]].append((month_close[cur] / month_close[prev] - 1) * 100)

    def stats(m):
        vals = by_month[m]
        if not vals:
            return {"month": m, "samples": 0, "avg_return_pct": None, "positive_share": None}
        return {"month": m, "samples": len(vals), "avg_return_pct": round(sum(vals) / len(vals), 2),
                "positive_share": round(sum(v > 0 for v in vals) / len(vals), 2)}

    span_years = round((candles[-1]["time"] - candles[0]["time"]) / (365.25 * 86400), 1) if candles else 0
    now = datetime.now(timezone.utc)
    nxt = now.month % 12 + 1
    return {"data_span_years": span_years, "current_month": stats(now.month), "next_month": stats(nxt),
            "note": "Computed from the candles the free plan returned; few samples means weak evidence."}


def fetch_seasonality(symbol: str):
    candles = _cached(("season", symbol.upper()), 24 * 3600,
                      lambda: fetch_ohlc_long(symbol))
    return compute_seasonality(candles)


def fetch_ohlc_long(symbol: str, years: int = 6):
    """Long daily history for seasonality (bypasses the short-window cache key)."""
    info = SYMBOLS.get(symbol.upper())
    if not info:
        raise DataError("Unsupported symbol")
    n = int(years * 260)
    if info["kind"] == "gold":
        return _ninjas_candles("goldpricehistorical", {}, "1d", n)
    return _twelve_candles(info, "1d", n)
