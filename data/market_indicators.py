"""
Market Indicators — fetches macro data relevant to Singapore property.
All sources are free (Yahoo Finance public API, no key needed).
Cached 4 hours to avoid hammering Yahoo.
"""

import json
import time
import requests
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / "cache" / "macro"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL = 14400  # 4 hours

_SYMBOLS = {
    "VIX":       {"ticker": "^VIX",       "label": "CBOE VIX (Fear Index)",       "unit": "pts"},
    "US10Y":     {"ticker": "^TNX",        "label": "US 10Y Treasury Yield",        "unit": "%"},
    "SGD_USD":   {"ticker": "SGD=X",       "label": "USD/SGD Rate",                 "unit": "SGD per USD"},
    "STI":       {"ticker": "^STI",        "label": "Straits Times Index",          "unit": "pts"},
    "SP500":     {"ticker": "^GSPC",       "label": "S&P 500",                      "unit": "pts"},
}


def _fetch_yahoo(ticker: str) -> dict | None:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    try:
        resp = requests.get(
            url,
            params={"interval": "1d", "range": "3mo"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data["chart"]["result"][0]
        meta = result["meta"]
        closes = result["indicators"]["quote"][0].get("close", [])
        timestamps = result["timestamp"]

        closes_clean = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
        if not closes_clean:
            return None

        current = meta.get("regularMarketPrice") or closes_clean[-1][1]
        prev = closes_clean[-2][1] if len(closes_clean) >= 2 else current
        month_ago = closes_clean[-22][1] if len(closes_clean) >= 22 else closes_clean[0][1]
        three_month_ago = closes_clean[0][1]

        return {
            "current": round(current, 4),
            "change_1d": round(current - prev, 4),
            "change_1d_pct": round((current - prev) / prev * 100, 2) if prev else 0,
            "change_1mo_pct": round((current - month_ago) / month_ago * 100, 2) if month_ago else 0,
            "change_3mo_pct": round((current - three_month_ago) / three_month_ago * 100, 2) if three_month_ago else 0,
            "history_3mo": [round(c, 4) for _, c in closes_clean[-63:]],
            "fetched_at": time.time(),
        }
    except Exception as e:
        return {"error": str(e), "fetched_at": time.time()}


def get_indicator(key: str) -> dict:
    """Return cached or freshly fetched data for a single indicator."""
    cache_path = CACHE_DIR / f"{key}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if time.time() - cached.get("fetched_at", 0) < CACHE_TTL:
            return {**_SYMBOLS[key], **cached}

    ticker = _SYMBOLS[key]["ticker"]
    data = _fetch_yahoo(ticker) or {"error": "fetch failed", "fetched_at": time.time()}
    cache_path.write_text(json.dumps(data))
    return {**_SYMBOLS[key], **data}


def get_all_indicators() -> dict:
    """Return all macro indicators as a dict keyed by symbol."""
    return {k: get_indicator(k) for k in _SYMBOLS}


def sg_property_macro_summary(indicators: dict) -> dict:
    """
    Rule-based interpretation of macro indicators for Singapore property.
    Returns a sentiment dict: signal (bullish/bearish/neutral), reasons, risk_factors.
    """
    vix = indicators.get("VIX", {}).get("current", 20)
    us10y = indicators.get("US10Y", {}).get("current", 4.5)
    sgd_usd = indicators.get("SGD_USD", {}).get("current", 0.74)
    vix_1mo = indicators.get("VIX", {}).get("change_1mo_pct", 0)
    us10y_1mo = indicators.get("US10Y", {}).get("change_1mo_pct", 0)

    bullish = []
    bearish = []
    neutral = []

    # VIX interpretation
    if vix < 15:
        bullish.append(f"VIX at {vix:.1f} — low market fear, risk appetite supports property prices")
    elif vix < 20:
        neutral.append(f"VIX at {vix:.1f} — moderate volatility, market stable")
    elif vix < 30:
        bearish.append(f"VIX at {vix:.1f} — elevated fear, buyers may hesitate on big-ticket purchases")
    else:
        bearish.append(f"VIX at {vix:.1f} — high market stress, expect slower transaction volumes")

    # US 10Y (proxy for global mortgage rate pressure)
    if us10y < 3.5:
        bullish.append(f"US 10Y at {us10y:.2f}% — low global rates reduce mortgage cost pressure")
    elif us10y < 4.5:
        neutral.append(f"US 10Y at {us10y:.2f}% — moderate global rates, Singapore mortgages manageable")
    elif us10y < 5.5:
        bearish.append(f"US 10Y at {us10y:.2f}% — elevated global rates push up SORA/SOR, increasing mortgage burden")
    else:
        bearish.append(f"US 10Y at {us10y:.2f}% — high global rates significantly increase financing costs")

    # Trend signals
    if us10y_1mo > 10:
        bearish.append(f"US 10Y rose {us10y_1mo:+.1f}% last month — rate hike expectations rising")
    elif us10y_1mo < -10:
        bullish.append(f"US 10Y fell {us10y_1mo:+.1f}% last month — rate cut expectations improving affordability")

    if vix_1mo > 30:
        bearish.append(f"VIX surged {vix_1mo:+.1f}% last month — risk-off sentiment building")

    # SGD strength: SGD=X gives SGD per USD, so lower = stronger SGD
    if sgd_usd < 1.30:
        bullish.append(f"SGD strong at {sgd_usd:.4f}/USD — foreign capital sees less currency risk buying SG property")
    elif sgd_usd > 1.38:
        bearish.append(f"SGD weak at {sgd_usd:.4f}/USD — imported inflation may pressure MAS tightening")

    # Score
    score = len(bullish) - len(bearish)
    if score >= 2:
        signal = "Macro Bullish"
    elif score <= -2:
        signal = "Macro Bearish"
    else:
        signal = "Macro Neutral"

    return {
        "signal": signal,
        "bullish_factors": bullish,
        "bearish_factors": bearish,
        "neutral_factors": neutral,
        "sg_property_impact": _property_impact_text(vix, us10y, sgd_usd),
    }


def _property_impact_text(vix: float, us10y: float, sgd_usd: float) -> str:
    # Estimated Singapore HDB average mortgage rate based on US10Y as proxy
    # Singapore SORA roughly tracks US Fed Funds with ~6-month lag
    est_sora = max(0.5, us10y - 2.0)  # rough proxy
    est_mortgage = round(est_sora + 1.3, 2)  # typical bank spread
    monthly_per_500k = round(500000 * (est_mortgage / 100 / 12) / (1 - (1 + est_mortgage / 100 / 12) ** -300), 0)

    lines = [
        f"Estimated Singapore mortgage rate: ~{est_mortgage:.2f}% p.a. (SORA proxy {est_sora:.2f}% + spread 1.3%)",
        f"Monthly repayment on SGD 500K / 25yr loan: ~SGD {monthly_per_500k:,.0f}",
        f"VIX at {vix:.1f}: {'low risk appetite' if vix > 25 else 'normal market conditions'}",
    ]
    return " | ".join(lines)
