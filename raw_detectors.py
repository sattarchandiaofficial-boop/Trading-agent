"""
Raw Detectors — objective math/geometry only.

Everything in this file computes a FACT (a swing point exists, RSI = 42.3,
these two series correlate at 0.71) or flags a CANDIDATE using a fixed
definition (a 3-candle gap, a wick beyond the 20-candle high). Nothing here
decides whether a fact MATTERS — that judgment always belongs to the
specialist AI agents in specialist_agents.py.
"""

import numpy as np
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Price Action / Structure
# ---------------------------------------------------------------------------

def find_swing_points(candles, lookback: int = 3):
    """Objective pivot high/low detection: a candle whose high/low is the
    extreme within `lookback` candles on each side."""
    swings = []
    for i in range(lookback, len(candles) - lookback):
        window = candles[i - lookback:i + lookback + 1]
        c = candles[i]
        if c["high"] == max(w["high"] for w in window):
            swings.append({"type": "swing_high", "time": c["time"], "price": c["high"], "index": i})
        if c["low"] == min(w["low"] for w in window):
            swings.append({"type": "swing_low", "time": c["time"], "price": c["low"], "index": i})
    return swings


def detect_structure_breaks(candles, swings):
    """
    Flags candidate Break of Structure (BOS) / Change of Character (CHOCH)
    points: price closing beyond the most recent opposite swing.
    Pure sequence logic — no judgment on significance.
    """
    breaks = []
    last_high = last_low = None
    trend = None  # "up" | "down" | None

    for s in swings:
        if s["type"] == "swing_high":
            last_high = s["price"]
        else:
            last_low = s["price"]

    for c in candles:
        if last_high and c["close"] > last_high:
            label = "BOS_bullish" if trend in (None, "up") else "CHOCH_bullish"
            breaks.append({"type": label, "time": c["time"], "price": c["close"]})
            trend = "up"
        if last_low and c["close"] < last_low:
            label = "BOS_bearish" if trend in (None, "down") else "CHOCH_bearish"
            breaks.append({"type": label, "time": c["time"], "price": c["close"]})
            trend = "down"
    return breaks


# ---------------------------------------------------------------------------
# Support / Resistance
# ---------------------------------------------------------------------------

def detect_sr_levels(candles, swings, cluster_tolerance_pct: float = 0.05):
    """Clusters swing points into candidate S/R levels by proximity."""
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

    current_price = candles[-1]["close"]
    levels = []
    for cl in clusters:
        level = sum(cl) / len(cl)
        levels.append({
            "level": level,
            "touches": len(cl),
            "distance_from_current": abs(current_price - level),
            "distance_pct": abs(current_price - level) / current_price * 100,
        })
    return sorted(levels, key=lambda l: l["distance_from_current"])


# ---------------------------------------------------------------------------
# SMC (Order Blocks / FVG / Liquidity Sweeps)
# ---------------------------------------------------------------------------

def detect_order_blocks(candles):
    candidates = []
    for i in range(1, len(candles) - 1):
        prev, nxt = candles[i], candles[i + 1]
        move = nxt["close"] - nxt["open"]
        rng = prev["high"] - prev["low"]
        if rng == 0:
            continue
        if prev["close"] < prev["open"] and move > rng * 1.5:
            candidates.append({"type": "bullish_order_block", "time": prev["time"], "high": prev["high"], "low": prev["low"]})
        if prev["close"] > prev["open"] and -move > rng * 1.5:
            candidates.append({"type": "bearish_order_block", "time": prev["time"], "high": prev["high"], "low": prev["low"]})
    return candidates


def detect_fair_value_gaps(candles):
    gaps = []
    for i in range(1, len(candles) - 1):
        c1, c3 = candles[i - 1], candles[i + 1]
        if c1["high"] < c3["low"]:
            gaps.append({"type": "bullish_fvg", "top": c3["low"], "bottom": c1["high"], "time": candles[i]["time"]})
        if c1["low"] > c3["high"]:
            gaps.append({"type": "bearish_fvg", "top": c1["low"], "bottom": c3["high"], "time": candles[i]["time"]})
    return gaps


def detect_liquidity_sweeps(candles, lookback: int = 20):
    sweeps = []
    for i in range(lookback, len(candles)):
        window = candles[i - lookback:i]
        recent_high = max(c["high"] for c in window)
        recent_low = min(c["low"] for c in window)
        c = candles[i]
        if c["high"] > recent_high and c["close"] < recent_high:
            sweeps.append({"type": "liquidity_sweep_high", "time": c["time"], "wick_high": c["high"]})
        if c["low"] < recent_low and c["close"] > recent_low:
            sweeps.append({"type": "liquidity_sweep_low", "time": c["time"], "wick_low": c["low"]})
    return sweeps


# ---------------------------------------------------------------------------
# ICT (Kill zones / OTE)
# ---------------------------------------------------------------------------

KILL_ZONES_UTC = {
    "london": (7, 10),
    "new_york": (12, 15),
    "asian": (0, 3),
}


def current_kill_zone(now: datetime = None):
    now = now or datetime.now(timezone.utc)
    active = [name for name, (start, end) in KILL_ZONES_UTC.items() if start <= now.hour < end]
    return {"utc_hour": now.hour, "active_kill_zones": active}


def detect_ote_zone(swings):
    """Optimal Trade Entry = 61.8%-79% Fibonacci retracement of the most
    recent swing leg. Pure arithmetic, no judgment on whether it'll hold."""
    if len(swings) < 2:
        return None
    a, b = swings[-2], swings[-1]
    leg = b["price"] - a["price"]
    return {
        "leg_start": a["price"],
        "leg_end": b["price"],
        "ote_618": b["price"] - leg * 0.618,
        "ote_79": b["price"] - leg * 0.79,
    }


# ---------------------------------------------------------------------------
# Volatility / Momentum
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
    atr_now = calc_atr(candles, period)
    atr_prior = calc_atr(candles[:-period], period)
    return {"atr_now": atr_now, "atr_prior": atr_prior,
            "ratio": (atr_now / atr_prior) if atr_prior else None}


def calc_momentum(candles, lookback: int = 10):
    closes = [c["close"] for c in candles[-lookback:]]
    roc = (closes[-1] - closes[0]) / closes[0] * 100

    streak, direction = 0, None
    for c in reversed(candles):
        d = "up" if c["close"] >= c["open"] else "down"
        if direction is None:
            direction = d
        if d != direction:
            break
        streak += 1
    return {"rate_of_change_pct": roc, "consecutive_candle_streak": streak, "streak_direction": direction}


# ---------------------------------------------------------------------------
# Divergence
# ---------------------------------------------------------------------------

def calc_rsi(candles, period: int = 14):
    closes = np.array([c["close"] for c in candles])
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.zeros_like(closes)
    avg_loss = np.zeros_like(closes)
    avg_gain[period] = gains[:period].mean()
    avg_loss[period] = losses[:period].mean()
    for i in range(period + 1, len(closes)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period

    rs = np.divide(avg_gain, avg_loss, out=np.full_like(avg_gain, np.nan), where=avg_loss != 0)
    rsi = 100 - (100 / (1 + rs))
    return rsi  # array aligned with `candles`, first `period` entries are 0/NaN


def detect_divergence_candidates(candles, lookback: int = 30):
    """Flags candidate bullish/bearish divergence by comparing the two most
    recent price swing extremes against RSI at those same points."""
    rsi = calc_rsi(candles)
    swings = find_swing_points(candles[-lookback:], lookback=2)
    lows = [s for s in swings if s["type"] == "swing_low"]
    highs = [s for s in swings if s["type"] == "swing_high"]

    candidates = []
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if b["price"] < a["price"] and rsi[b["index"]] > rsi[a["index"]]:
            candidates.append({"type": "bullish_divergence", "at_time": b["time"]})
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if b["price"] > a["price"] and rsi[b["index"]] < rsi[a["index"]]:
            candidates.append({"type": "bearish_divergence", "at_time": b["time"]})
    return candidates


# ---------------------------------------------------------------------------
# Regime Detection — HMM + BOCPD (statistical, not AI, not hardcoded rules)
# ---------------------------------------------------------------------------

def calc_regime_hmm(candles, n_states: int = 3):
    """
    Fits a Gaussian HMM on log returns to classify the current regime.
    Requires: pip install hmmlearn
    States are labeled by their fitted mean return (not a hardcoded
    threshold on price — the label follows from the model's own fit).
    """
    from hmmlearn.hmm import GaussianHMM

    closes = np.array([c["close"] for c in candles])
    log_returns = np.diff(np.log(closes)).reshape(-1, 1)

    model = GaussianHMM(n_components=n_states, covariance_type="diag", n_iter=200, random_state=42)
    model.fit(log_returns)
    hidden_states = model.predict(log_returns)

    means = model.means_.flatten()
    order = np.argsort(means)  # bearish -> sideways -> bullish
    label_map = {order[0]: "bearish", order[1]: "sideways", order[2]: "bullish"}

    current_state = hidden_states[-1]
    state_probs = model.predict_proba(log_returns)[-1]

    return {
        "current_regime": label_map[current_state],
        "state_probabilities": {label_map[i]: float(state_probs[i]) for i in range(n_states)},
        "regime_means": {label_map[i]: float(means[i]) for i in range(n_states)},
    }


def calc_bocpd_changepoint_probability(candles, hazard: float = 1 / 100):
    """
    Simplified Bayesian Online Changepoint Detection (Adams & MacKay) on
    log returns. Returns the probability that a regime change occurred at
    the most recent observation — an early-warning signal, independent of
    the HMM's regime classification.
    """
    closes = np.array([c["close"] for c in candles])
    data = np.diff(np.log(closes))

    # Normal-inverse-gamma conjugate prior params (weak, generic prior)
    mu0, kappa0, alpha0, beta0 = 0.0, 1.0, 1.0, 1.0
    R = np.array([1.0])  # run-length distribution, starts certain at run=0
    mus, kappas, alphas, betas = [mu0], [kappa0], [alpha0], [beta0]

    for x in data:
        mus_a, kappas_a = np.array(mus), np.array(kappas)
        alphas_a, betas_a = np.array(alphas), np.array(betas)

        pred_var = betas_a * (kappas_a + 1) / (alphas_a * kappas_a)
        pred_var = np.maximum(pred_var, 1e-12)
        pred_prob = np.exp(-0.5 * (x - mus_a) ** 2 / pred_var) / np.sqrt(2 * np.pi * pred_var)

        growth = R * pred_prob * (1 - hazard)
        cp = np.sum(R * pred_prob * hazard)
        R_new = np.append(cp, growth)
        R_new /= R_new.sum()

        new_kappas = kappas_a + 1
        new_mus = (kappas_a * mus_a + x) / new_kappas
        new_alphas = alphas_a + 0.5
        new_betas = betas_a + kappas_a * (x - mus_a) ** 2 / (2 * new_kappas)

        mus = [mu0] + list(new_mus)
        kappas = [kappa0] + list(new_kappas)
        alphas = [alpha0] + list(new_alphas)
        betas = [beta0] + list(new_betas)
        R = R_new

    return {"changepoint_probability_now": float(R[0]), "run_length_distribution_tail": R[-5:].tolist()}


# ---------------------------------------------------------------------------
# Correlation / Intermarket
# ---------------------------------------------------------------------------

def calc_correlation(candles_a, candles_b, period: int = 30):
    n = min(len(candles_a), len(candles_b), period)
    a = np.array([c["close"] for c in candles_a[-n:]])
    b = np.array([c["close"] for c in candles_b[-n:]])
    corr = float(np.corrcoef(a, b)[0, 1])
    return {"correlation_coefficient": corr, "period": n}


# ---------------------------------------------------------------------------
# Anomaly Detection
# ---------------------------------------------------------------------------

def detect_anomaly(candles, lookback: int = 50):
    ranges = np.array([c["high"] - c["low"] for c in candles[-lookback:]])
    mean, std = ranges.mean(), ranges.std()
    last_range = candles[-1]["high"] - candles[-1]["low"]
    z = (last_range - mean) / std if std > 0 else 0.0
    return {"last_candle_range": float(last_range), "mean_range": float(mean), "z_score": float(z)}


# ---------------------------------------------------------------------------
# Risk / Reward
# ---------------------------------------------------------------------------

def calc_nearest_levels_rr(current_price, sr_levels, direction_hint: str = None):
    above = [l for l in sr_levels if l["level"] > current_price]
    below = [l for l in sr_levels if l["level"] < current_price]
    nearest_resistance = min(above, key=lambda l: l["level"], default=None)
    nearest_support = max(below, key=lambda l: l["level"], default=None)

    rr = None
    if nearest_resistance and nearest_support:
        risk = current_price - nearest_support["level"]
        reward = nearest_resistance["level"] - current_price
        rr = (reward / risk) if risk > 0 else None

    return {
        "nearest_resistance": nearest_resistance,
        "nearest_support": nearest_support,
        "risk_reward_ratio_long": rr,
    }
