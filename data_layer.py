"""
Data Layer — pure mechanical fetching, zero judgment.
Every function here returns raw facts. No function in this file decides
whether something is "significant" — that's always left to the AI agents.
"""

import os
import time
import requests

API_NINJAS_KEY = os.environ.get("API_NINJAS_KEY")  # free, no card: api-ninjas.com/register


def _api_ninjas_session():
    s = requests.Session()
    s.headers["X-Api-Key"] = API_NINJAS_KEY
    return s


def fetch_ohlc(symbol: str = "XAUUSD", interval: str = "15m", outputsize: int = 150):
    """
    Returns OHLC candles oldest->newest:
    [{"time": unix_ts, "open": .., "high": .., "low": .., "close": ..}, ...]

    interval must be one of: 1m, 5m, 15m, 30m, 1h, 4h, 1d
    """
    session = _api_ninjas_session()

    if symbol.upper() in ("XAUUSD", "GOLD", "XAU"):
        endpoint = "https://api.api-ninjas.com/v1/goldpricehistorical"
        params = {"period": interval}
    else:
        # Forex pair, e.g. EURUSD -> API Ninjas exchange rate historical endpoint.
        # Confirm the exact param names against your API Ninjas dashboard when
        # you wire up a specific pair; shape below follows their documented
        # historical-endpoint convention (same as goldpricehistorical).
        endpoint = "https://api.api-ninjas.com/v1/forexhistorical"
        params = {"pair": symbol.upper(), "period": interval}

    resp = session.get(endpoint, params=params, timeout=15)
    resp.raise_for_status()
    raw = resp.json()

    candles = []
    for c in sorted(raw, key=lambda c: c["time"]):
        candles.append({
            "time": c["time"],
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
        })
    return candles[-outputsize:]


def fetch_multi_timeframe(symbol: str, timeframes=("15m", "1h", "4h", "1d")):
    """Returns {"15m": [...], "1h": [...], ...} — for the Multi-Timeframe Agent."""
    return {tf: fetch_ohlc(symbol, tf, outputsize=100) for tf in timeframes}


def fetch_correlated_symbol(symbol: str = "DXY", interval: str = "1h", outputsize: int = 150):
    """
    Fetches a correlated instrument's candles (e.g. DXY for gold/forex).
    Swap endpoint for whichever free source covers DXY / index data on
    your chosen provider — placeholder mirrors fetch_ohlc's shape.
    """
    return fetch_ohlc(symbol, interval, outputsize)


# ---------------------------------------------------------------------------
# Chrome-research fetchers (News, COT, Seasonality)
# These use a headless browser because no reliable free structured API
# exists for them. Implemented with Playwright. Mechanical scraping only —
# no interpretation happens here, that's the News/COT/Seasonality agents' job.
# ---------------------------------------------------------------------------

def fetch_upcoming_news(currency: str = "USD"):
    """
    Scrapes upcoming high/medium-impact economic events from a free public
    economic calendar (e.g. Forex Factory) for the given currency.
    Returns a list of {"time": ..., "event": ..., "impact": ..., "currency": ...}
    """
    from playwright.sync_api import sync_playwright

    events = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.forexfactory.com/calendar", timeout=30000)
        page.wait_for_selector(".calendar__row", timeout=15000)

        rows = page.query_selector_all(".calendar__row")
        for row in rows:
            try:
                currency_el = row.query_selector(".calendar__currency")
                event_el = row.query_selector(".calendar__event")
                impact_el = row.query_selector(".calendar__impact span")
                time_el = row.query_selector(".calendar__time")
                if not (currency_el and event_el):
                    continue
                row_currency = currency_el.inner_text().strip()
                if currency and row_currency != currency:
                    continue
                events.append({
                    "currency": row_currency,
                    "event": event_el.inner_text().strip(),
                    "impact": impact_el.get_attribute("title") if impact_el else "unknown",
                    "time": time_el.inner_text().strip() if time_el else "unknown",
                })
            except Exception:
                continue  # skip malformed rows rather than fail the whole fetch

        browser.close()
    return events


def fetch_cot_report(instrument: str = "GOLD"):
    """
    Scrapes the latest public CFTC Commitment of Traders report for the
    given instrument. CFTC publishes this weekly (Fridays), not daily.
    Returns raw positioning numbers — interpretation is the COT Agent's job.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.cftc.gov/dea/futures/deacmesf.htm", timeout=30000)
        page.wait_for_load_state("networkidle")
        text = page.inner_text("body")
        browser.close()

    # NOTE: CFTC's report is a fixed-width text table. Proper parsing needs
    # a dedicated parser matched to the instrument's exact row — this
    # placeholder returns the raw block for the target instrument's section
    # so the COT Agent can be given real (if unparsed) context. Tighten this
    # with a regex/column-offset parser once you've picked your instrument.
    return {"instrument": instrument, "raw_report_text": text[:4000]}


def fetch_seasonality(symbol: str = "XAUUSD"):
    """
    Scrapes historical monthly performance tendency for a symbol from a
    free public seasonality source. Returns raw per-month stats;
    interpretation ("is this a reliable pattern") is the Seasonality Agent's job.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        # Placeholder target — swap for whichever free seasonality page you
        # settle on (e.g. a site that publishes monthly average returns per
        # symbol). Structure will need matching selectors like the two
        # functions above.
        page.goto(f"https://www.google.com/search?q={symbol}+seasonality+monthly+average+returns", timeout=30000)
        text = page.inner_text("body")
        browser.close()

    return {"symbol": symbol, "raw_search_snippet": text[:3000]}
