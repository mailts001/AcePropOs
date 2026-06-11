"""
Singapore Stamp Duty Calculator — ABSD + BSD (as of 2023 cooling measures).
Pure rule-based, zero API cost. Updates as government announces changes.
"""

RATES_EFFECTIVE_DATE = "27 Apr 2023"   # Last updated: ABSD hike Budget 2023
# ⚠️ Check iras.gov.sg after every Singapore Budget for rate changes.

# ── Buyer's Stamp Duty (BSD) ─────────────────────────────────────────────────
# Same for all buyer profiles. Applied on purchase price or market value, whichever higher.
BSD_BANDS = [
    (180_000,   0.01),
    (180_000,   0.02),
    (640_000,   0.03),
    (500_000,   0.04),
    (1_500_000, 0.05),
    (float("inf"), 0.06),
]

# ── Additional Buyer's Stamp Duty (ABSD) — Feb 2023 rates ───────────────────
ABSD_RATES = {
    "SC": {       # Singapore Citizen
        1: 0.00,  # 1st property
        2: 0.20,  # 2nd property
        3: 0.30,  # 3rd+
    },
    "SPR": {      # Singapore Permanent Resident
        1: 0.05,
        2: 0.30,
        3: 0.35,
    },
    "Foreigner": {
        1: 0.60,  # All properties
        2: 0.60,
        3: 0.60,
    },
    "Entity": {
        1: 0.65,  # Companies / trusts
        2: 0.65,
        3: 0.65,
    },
}

# ── Seller's Stamp Duty (SSD) — only for residential sold within 3 years ────
SSD_RATES = [
    (12, 0.12),  # held ≤ 12 months
    (24, 0.08),  # held ≤ 24 months
    (36, 0.04),  # held ≤ 36 months
]


def calc_bsd(price: float) -> dict:
    """Buyer's Stamp Duty on residential property."""
    duty = 0.0
    remaining = price
    breakdown = []
    for band, rate in BSD_BANDS:
        taxable = min(remaining, band)
        amount = taxable * rate
        if amount > 0:
            breakdown.append({
                "band": f"First SGD {band:,.0f}" if band != float("inf") else "Above SGD 3,000,000",
                "rate_pct": rate * 100,
                "taxable_sgd": round(taxable, 0),
                "duty_sgd": round(amount, 0),
            })
        duty += amount
        remaining -= taxable
        if remaining <= 0:
            break
    return {
        "total_bsd_sgd": round(duty, 0),
        "effective_rate_pct": round(duty / price * 100, 2),
        "breakdown": breakdown,
    }


def calc_absd(price: float, profile: str, property_count: int) -> dict:
    """
    Additional Buyer's Stamp Duty.
    profile: "SC" | "SPR" | "Foreigner" | "Entity"
    property_count: number of residential properties AFTER this purchase
    """
    count = min(property_count, 3)  # 3+ all treated same
    rates = ABSD_RATES.get(profile, ABSD_RATES["Foreigner"])
    rate = rates.get(count, rates[3])
    duty = price * rate

    notes = []
    if profile == "SC" and property_count == 2:
        notes.append("Joint purchase: if co-buyer is SPR/Foreigner, higher profile's ABSD applies.")
    if profile == "SC" and property_count == 1:
        notes.append("First home — no ABSD. Remission available for married couples upgrading.")
    if profile == "Foreigner":
        notes.append("60% ABSD applies to all residential properties. No remission except Free Trade Agreement nationals.")
    if duty > 0:
        notes.append("ABSD must be paid within 14 days of signing the OTP (Option to Purchase).")

    return {
        "profile": profile,
        "property_count": property_count,
        "absd_rate_pct": rate * 100,
        "total_absd_sgd": round(duty, 0),
        "notes": notes,
    }


def calc_ssd(price: float, hold_months: int) -> dict:
    """Seller's Stamp Duty — only applies if sold within 36 months of purchase."""
    if hold_months > 36:
        return {"total_ssd_sgd": 0, "rate_pct": 0, "note": "No SSD — held more than 3 years."}
    for max_months, rate in SSD_RATES:
        if hold_months <= max_months:
            duty = price * rate
            return {
                "total_ssd_sgd": round(duty, 0),
                "rate_pct": rate * 100,
                "hold_months": hold_months,
                "note": f"Sold within {hold_months} months. SSD applies at {rate*100:.0f}%.",
            }
    return {"total_ssd_sgd": 0, "rate_pct": 0, "note": "No SSD."}


def full_stamp_duty(
    price: float,
    profile: str,
    property_count: int,
    is_hdb: bool = False,
) -> dict:
    """Combined BSD + ABSD with cash flow summary."""
    bsd = calc_bsd(price)
    absd = calc_absd(price, profile, property_count)

    total = bsd["total_bsd_sgd"] + absd["total_absd_sgd"]
    cash_needed = total  # stamp duties must be paid in cash (no CPF)

    # LTV implications
    if is_hdb:
        ltv_pct = 80 if profile in ("SC", "SPR") and property_count == 1 else 55
    else:
        ltv_pct = 75 if property_count == 1 else 45

    loan_max = price * ltv_pct / 100
    cash_down = price - loan_max
    total_cash_needed = cash_down + total  # downpayment + stamp duties

    return {
        "price": price,
        "bsd": bsd,
        "absd": absd,
        "total_stamp_duty_sgd": total,
        "effective_total_rate_pct": round(total / price * 100, 2),
        "ltv_pct": ltv_pct,
        "max_loan_sgd": round(loan_max, 0),
        "min_cash_downpayment_sgd": round(cash_down, 0),
        "total_upfront_cash_sgd": round(total_cash_needed, 0),
        "note": "Stamp duties must be paid in cash (CPF cannot be used for ABSD/BSD).",
    }
