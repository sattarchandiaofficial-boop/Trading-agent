"""
raw_detectors.py — objective math only.

Everything here computes a FACT (a swing exists, RSI = 42.3, correlation =
0.71) or flags a CANDIDATE from a fixed definition (a 3-candle gap). Nothing
decides whether a fact MATTERS; that is the specialist agents' job.

Only numpy is required (no scipy / scikit-learn / hmmlearn), so it installs
on Termux with `pkg install python-numpy`.
"""

from datetime import datetime, timezone

import numpy as np


# ---------------------------------------------------------------------------
# Swings / structure
# ---------------------------------------------------------------------------
def find_swing_points(candles, lookback: int = 3):
    """Pivot high/low: extreme within `lookback` candles on each side."""
    swings = []
    for i in range(lookback, len(candles) - lookback):
        window = candles[i - lookback:i + lookback + 1]
        c = candles[i]
        if c["high"] == max(w["high"] for w in window):
            swings.append({"type": "swing_high", "time": c["time"], "price": c["high"], "index": i})
        if c["low"] == min(w["low"] for w in window):
            swings.append({"type": "swing_low", "time": c["time"], "price": c["low"], "index": i})
    swings.sort(key=lambda s: s["index"])
    return swings


def detect_structure_breaks(candles, swings, lookback: int = 3):
    """
    Walks forward in time. A swing only becomes 'known' `lookback` candles after
    it forms. A close beyond the latest known swing high/low is a break:
    BOS when it continues the current trend, CHOCH when it reverses it.
    Each level can only be broken once.
    """
    breaks = []
    trend = None
    last_high = last_low = None
    pending = list(swings)
    for i, c in enumerate(candles):
        while pending and pending[0]["index"] + lookback <= i:
            s = pending.pop(0)
            if s["type"] == "swing_high":
                last_high = s["price"]
            else:
                last_low = s["price"]
        if last_high is not None and c["close"] > last_high:
            kind = "BOS_bullish" if trend in (None, "up") else "CHOCH_bullish"
            breaks.append({"type": kind, "time": c["time"], "price": c["close"], "broken_level": last_high})
            trend, last_high = "up", None
        elif last_low is not None and c["close"] < last_low:
            kind = "BOS_bearish" if trend in (None, "down") else "CHOCH_bearish"
            breaks.append({"type": kind, "time": c["time"], "price": c["close"], "broken_level": last_low})
            trend, last_low = "down", None
    return {"breaks": breaks, "current_trend_by_breaks": trend}


# ---------------------------------------------------------------------------
# Support / resistance
# ---------------------------------------------------------------------------
def detect_sr_levels(candles, swings, cluster_tolerance_pct: float = 0.05):
    prices = sorted(s["price"] for s in swings)
    if not prices:
        return []
    clusters, current = [], [prices[0]]
    for p in prices[1:]:
        if abs(p - current[-1]) / current[-1] * 100 <= cluster_tolerance_pct:
            current.append(p)
        else:
            clusters.append(current)
            current = [p]
    clusters.append(current)

    price = candles[-1]["close"]
    levels = []
    for cl in clusters:
        level = sum(cl) / len(cl)
        levels.append({"level": level, "touches": len(cl), "distance": abs(price - level),
                       "distance_pct": abs(price - level) / price * 100,
                       "side": "above" if level > price else "below"})
    return sorted(levels, key=lambda l: l["distance"])


# ---------------------------------------------------------------------------
# SMC
# ---------------------------------------------------------------------------
def detect_order_blocks(candles):
    out = []
    for i in range(0, len(candles) - 1):
        prev, nxt = candles[i], candles[i + 1]
        move = nxt["close"] - nxt["open"]
        rng = prev["high"] - prev["low"]
        if rng == 0:
            continue
        if prev["close"] < prev["open"] and move > rng * 1.5:
            out.append({"type": "bullish_order_block", "time": prev["time"], "high": prev["high"], "low": prev["low"]})
        if prev["close"] > prev["open"] and -move > rng * 1.5:
            out.append({"type": "bearish_order_block", "time": prev["time"], "high": prev["high"], "low": prev["low"]})
    return out


def detect_fair_value_gaps(candles):
    gaps = []
    for i in range(1, len(candles) - 1):
        c1, c3 = candles[i - 1], candles[i + 1]
        if c1["high"] < c3["low"]:
            gaps.append({"type": "bullish_fvg", "top": c3["low"], "bottom": c1["high"], "time": candles[i]["time"]})
        if c1["low"] > c3["high"]:
            gaps.append({"type": "bearish_fvg", "top": c1["low"], "bottom": c3["high"], "time": candles[i]["time"]})
    # Mark whether later price has already traded back through the gap.
    for g in gaps:
        later = [c for c in candles if c["time"] > g["time"]]
        g["filled"] = any(c["low"] <= g["bottom"] if g["type"] == "bullish_fvg" else c["high"] >= g["top"] for c in later)
    return gaps


def detect_liquidity_sweeps(candles, lookback: int = 20):
    sweeps = []
    for i in range(lookback, len(candles)):
        window = candles[i - lookback:i]
        hi, lo = max(c["high"] for c in window), min(c["low"] for c in window)
        c = candles[i]
        if c["high"] > hi and c["close"] < hi:
            sweeps.append({"type": "liquidity_sweep_high", "time": c["time"], "wick_high": c["high"], "swept_level": hi})
        if c["low"] < lo and c["close"] > lo:
            sweeps.append({"type": "liquidity_sweep_low", "time": c["time"], "wick_low": c["low"], "swept_level": lo})
    return sweeps


# ---------------------------------------------------------------------------
# ICT
# ---------------------------------------------------------------------------
KILL_ZONES_UTC = {"asian": (0, 3), "london": (7, 10), "new_york": (12, 15)}


def current_kill_zone(now: datetime = None):
    now = now or datetime.now(timezone.utc)
    active = [n for n, (a, b) in KILL_ZONES_UTC.items() if a <= now.hour < b]
    return {"utc_time": now.strftime("%H:%M"), "active_kill_zones": active}


def detect_ote_zone(swings):
    """61.8%-79% retracement of the latest completed swing leg (a high and a low)."""
    if len(swings) < 2:
        return None
    last = swings[-1]
    other = next((s for s in reversed(swings[:-1]) if s["type"] != last["type"]), None)
    if other is None:
        return None
    leg = last["price"] - other["price"]  # >0 up-leg, <0 down-leg
    return {
        "direction": "up_leg" if leg > 0 else "down_leg",
        "leg_start": other["price"], "leg_end": last["price"],
        "ote_618": last["price"] - leg * 0.618, "ote_79": last["price"] - leg * 0.79,
    }


# ---------------------------------------------------------------------------
# Volatility / momentum
# ---------------------------------------------------------------------------
def calc_atr(candles, period: int = 14):
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    return float(np.mean(trs[-period:]))


def calc_volatility_state(candles, period: int = 14):
    now = calc_atr(candles, period)
    prior = calc_atr(candles[:-period], period)
    return {"atr_now": now, "atr_prior": prior, "ratio": (now / prior) if now and prior else None}


def calc_momentum(candles, lookback: int = 10):
    closes = [c["close"] for c in candles[-lookback:]]
    roc = (closes[-1] - closes[0]) / closes[0] * 100
    streak, direction = 0, None
    for c in reversed(candles):
        d = "up" if c["close"] >= c["open"] else "down"
        direction = direction or d
        if d != direction:
            break
        streak += 1
    return {"rate_of_change_pct": roc, "consecutive_candle_streak": streak, "streak_direction": direction}


# ---------------------------------------------------------------------------
# RSI / divergence
# ---------------------------------------------------------------------------
def calc_rsi(candles, period: int = 14):
    """Wilder RSI, aligned with `candles`; the first `period` entries are NaN."""
    closes = np.array([c["close"] for c in candles], dtype=float)
    n = len(closes)
    rsi = np.full(n, np.nan)
    if n <= period:
        return rsi
    deltas = np.diff(closes)
    gains, losses = np.where(deltas > 0, deltas, 0.0), np.where(deltas < 0, -deltas, 0.0)
    avg_gain, avg_loss = gains[:period].mean(), losses[:period].mean()
    for i in range(period, n):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        rsi[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi


def detect_divergence_candidates(candles, lookback: int = 40):
    rsi = calc_rsi(candles)
    offset = max(len(candles) - lookback, 0)
    swings = find_swing_points(candles[offset:], lookback=2)
    for s in swings:
        s["index"] += offset  # back to full-series indices so RSI lines up
    lows = [s for s in swings if s["type"] == "swing_low"]
    highs = [s for s in swings if s["type"] == "swing_high"]
    out = []
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if b["price"] < a["price"] and not np.isnan(rsi[a["index"]]) and rsi[b["index"]] > rsi[a["index"]]:
            out.append({"type": "bullish_divergence", "time": b["time"],
                        "price_lows": [a["price"], b["price"]], "rsi_at_lows": [float(rsi[a["index"]]), float(rsi[b["index"]])]})
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if b["price"] > a["price"] and not np.isnan(rsi[a["index"]]) and rsi[b["index"]] < rsi[a["index"]]:
            out.append({"type": "bearish_divergence", "time": b["time"],
                        "price_highs": [a["price"], b["price"]], "rsi_at_highs": [float(rsi[a["index"]]), float(rsi[b["index"]])]})
    return out


# ---------------------------------------------------------------------------
# Regime: 3-state Gaussian HMM (numpy Baum-Welch) + BOCPD
# ---------------------------------------------------------------------------
def _log_returns(candles):
    closes = np.array([c["close"] for c in candles], dtype=float)
    return np.diff(np.log(closes))


def _fit_gaussian_hmm(x, n_states=3, iters=40):
    """Scaled Baum-Welch for a 1-D Gaussian HMM. Returns (means, vars, A, filtered_last)."""
    T = len(x)
    qs = np.quantile(x, np.linspace(0.15, 0.85, n_states))
    mu = qs.copy()
    var = np.full(n_states, max(np.var(x), 1e-12))
    A = np.full((n_states, n_states), 0.1 / (n_states - 1))
    np.fill_diagonal(A, 0.9)
    pi = np.full(n_states, 1.0 / n_states)

    def emissions(mu, var):
        e = np.exp(-0.5 * (x[:, None] - mu[None, :]) ** 2 / var[None, :]) / np.sqrt(2 * np.pi * var[None, :])
        return np.maximum(e, 1e-300)

    for _ in range(iters):
        B = emissions(mu, var)
        alpha, c = np.zeros((T, n_states)), np.zeros(T)
        alpha[0] = pi * B[0]
        c[0] = alpha[0].sum()
        alpha[0] /= c[0]
        for t in range(1, T):
            alpha[t] = (alpha[t - 1] @ A) * B[t]
            c[t] = alpha[t].sum()
            alpha[t] /= c[t]
        beta = np.ones((T, n_states))
        for t in range(T - 2, -1, -1):
            beta[t] = (A @ (B[t + 1] * beta[t + 1])) / c[t + 1]
        gamma = alpha * beta
        gamma /= gamma.sum(axis=1, keepdims=True)
        xi = np.zeros((n_states, n_states))
        for t in range(T - 1):
            m = alpha[t][:, None] * A * (B[t + 1] * beta[t + 1])[None, :]
            xi += m / m.sum()
        w = gamma.sum(axis=0) + 1e-12
        mu = (gamma * x[:, None]).sum(axis=0) / w
        var = np.maximum((gamma * (x[:, None] - mu[None, :]) ** 2).sum(axis=0) / w, np.var(x) * 1e-3 + 1e-14)
        A = xi + 1e-6
        A /= A.sum(axis=1, keepdims=True)
        pi = gamma[0]
    B = emissions(mu, var)
    alpha = pi * B[0]
    alpha /= alpha.sum()
    for t in range(1, T):
        alpha = (alpha @ A) * B[t]
        alpha /= alpha.sum()
    return mu, var, A, alpha


def calc_regime_hmm(candles, n_states: int = 3):
    x = _log_returns(candles)
    if len(x) < 40:
        return {"error": "not enough candles for a regime fit (need 40+)"}
    mu, var, A, last = _fit_gaussian_hmm(x, n_states)
    order = np.argsort(mu)  # lowest mean return -> bearish, highest -> bullish
    names = ["bearish", "sideways", "bullish"]
    label = {int(order[i]): names[i] for i in range(n_states)}
    return {
        "current_regime": label[int(np.argmax(last))],
        "state_probabilities": {label[i]: round(float(last[i]), 3) for i in range(n_states)},
        "mean_return_per_bar_pct": {label[i]: round(float(mu[i]) * 100, 4) for i in range(n_states)},
        "stay_probability": {label[i]: round(float(A[i, i]), 3) for i in range(n_states)},
    }


def calc_bocpd(candles, hazard: float = 1 / 100):
    """Bayesian online changepoint detection (Adams & MacKay) on log returns."""
    x = _log_returns(candles)
    if len(x) < 20:
        return {"error": "not enough candles for changepoint detection"}
    scale = np.std(x) or 1e-9
    data = x / scale
    mu0, k0, a0, b0 = 0.0, 1.0, 1.0, 1.0
    R = np.array([1.0])
    mus, ks, als, bes = (np.array([v]) for v in (mu0, k0, a0, b0))
    recent_cp = []
    for obs in data:
        var = bes * (ks + 1) / (als * ks)
        pred = np.exp(-0.5 * (obs - mus) ** 2 / var) / np.sqrt(2 * np.pi * var)
        growth = R * pred * (1 - hazard)
        cp = float(np.sum(R * pred * hazard))
        R = np.append(cp, growth)
        R /= R.sum()
        recent_cp.append(float(R[0]))
        new_k = ks + 1
        new_mu = (ks * mus + obs) / new_k
        new_a = als + 0.5
        new_b = bes + ks * (obs - mus) ** 2 / (2 * new_k)
        mus, ks = np.append(mu0, new_mu), np.append(k0, new_k)
        als, bes = np.append(a0, new_a), np.append(b0, new_b)
    map_run = int(np.argmax(R))
    return {"changepoint_probability_now": round(float(R[0]), 4),
            "most_likely_run_length_bars": map_run,
            "max_changepoint_prob_last_10_bars": round(max(recent_cp[-10:]), 4)}


# ---------------------------------------------------------------------------
# Correlation / anomaly / risk-reward
# ---------------------------------------------------------------------------
def calc_correlation(candles_a, candles_b, period: int = 60):
    """Correlation of per-bar returns over the timestamps both series share."""
    a = {c["time"]: c["close"] for c in candles_a}
    b = {c["time"]: c["close"] for c in candles_b}
    times = sorted(set(a) & set(b))[-period:]
    if len(times) < 15:
        return {"error": f"only {len(times)} overlapping bars"}
    ra = np.diff(np.log([a[t] for t in times]))
    rb = np.diff(np.log([b[t] for t in times]))
    return {"return_correlation": round(float(np.corrcoef(ra, rb)[0, 1]), 3), "bars_used": len(times)}


def detect_anomaly(candles, lookback: int = 50):
    ranges = np.array([c["high"] - c["low"] for c in candles[-lookback - 1:-1]])
    last = candles[-1]["high"] - candles[-1]["low"]
    std = ranges.std()
    return {"last_candle_range": float(last), "mean_range": float(ranges.mean()),
            "z_score": float((last - ranges.mean()) / std) if std > 0 else 0.0}


def calc_risk_reward(price, sr_levels):
    above = [l for l in sr_levels if l["level"] > price]
    below = [l for l in sr_levels if l["level"] < price]
    res = min(above, key=lambda l: l["level"], default=None)
    sup = max(below, key=lambda l: l["level"], default=None)
    long_rr = short_rr = None
    if res and sup:
        up, down = res["level"] - price, price - sup["level"]
        long_rr = up / down if down > 0 else None
        short_rr = down / up if up > 0 else None
    return {"nearest_resistance": res["level"] if res else None,
            "nearest_support": sup["level"] if sup else None,
            "long_rr_to_nearest_levels": long_rr, "short_rr_to_nearest_levels": short_rr}
