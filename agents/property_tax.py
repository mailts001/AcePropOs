"""
Singapore Property Tax Calculator with Investment Offset Analysis.

Property tax is assessed on Annual Value (AV) of the property.
Due date: 31 January every year (IRAS issues notices in Dec/Jan).

Owner-Occupier (OO) Rates (2024, progressive on AV):
  First $8,000:   0%
  Next $47,000:   4%
  Next $5,000:    6%
  Next $10,000:   10%
  Next $15,000:   14%
  Next $15,000:   20%
  ...up to 32%

Non-Owner-Occupier (NOO) Rates (2024, progressive on AV):
  First $30,000:  11%
  Next $15,000:   16%
  Next $15,000:   21%
  Balance:        27%

Investment Offset: You can time your investments to generate returns that
cover the tax bill, due Jan 31. Options analysed:
  - T-bills (6M/1Y): auction via SGS, SGD yields ~3.5-4.0%
  - Singapore Savings Bonds (SSBs): flexible, ~3.0% 1Y step-up
  - Fixed deposits (FD): bank FDs, ~3.2% p.a.
  - CPF OA direct payment: IRAS allows CPF OA to pay property tax directly
  - REITs: dividends, higher yield but price risk

T-bill laddering strategy: buy T-bills so they mature just before Jan 31.
CPF path: apply via CPF Board to use OA balance; simplest option for HDB owners.

Reference: iras.gov.sg/taxes/property-tax
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
import math


# ── Tax band tables ────────────────────────────────────────────────────────────

OO_BANDS = [
    (8_000,   0.00),
    (47_000,  0.04),
    (5_000,   0.06),
    (10_000,  0.10),
    (15_000,  0.14),
    (15_000,  0.20),
    (15_000,  0.26),
    (float("inf"), 0.32),
]

NOO_BANDS = [
    (30_000,  0.11),
    (15_000,  0.16),
    (15_000,  0.21),
    (float("inf"), 0.27),
]

# Indicative yields (update quarterly)
INVESTMENT_RATES = {
    "tbill_6m":   3.80,  # % p.a. — 6-month T-bill, last cut-off yield
    "tbill_1y":   3.70,  # % p.a. — 1-year T-bill
    "ssb":        3.10,  # % p.a. average 10Y SSB (1Y effective ~2.8%)
    "ssb_1y":     2.80,  # % p.a. effective 1Y return
    "fd_6m":      3.20,  # % p.a. — best 6M FD
    "fd_12m":     3.10,  # % p.a. — best 12M FD
    "cpf_oa":     2.50,  # % p.a. — CPF OA rate
    "reits_div":  5.50,  # % p.a. — S-REIT dividend yield (estimated)
}


def _calc_tax(av: float, bands: list) -> float:
    tax, rem = 0.0, av
    for band, rate in bands:
        chunk = min(rem, band)
        tax += chunk * rate
        rem -= chunk
        if rem <= 0:
            break
    return tax


def calc_oo_tax(av: float) -> float:
    return _calc_tax(av, OO_BANDS)


def calc_noo_tax(av: float) -> float:
    return _calc_tax(av, NOO_BANDS)


def effective_rate(av: float, owner_occupied: bool) -> float:
    tax = calc_oo_tax(av) if owner_occupied else calc_noo_tax(av)
    return (tax / av * 100) if av > 0 else 0


def _days_to_jan31(from_date: date = None) -> int:
    """Days from from_date to next Jan 31."""
    if from_date is None:
        from_date = date.today()
    this_yr_jan31 = date(from_date.year, 1, 31)
    next_yr_jan31 = date(from_date.year + 1, 1, 31)
    target = this_yr_jan31 if from_date <= this_yr_jan31 else next_yr_jan31
    return (target - from_date).days


def _tbill_return(principal: float, rate_pa: float, tenure_days: int) -> float:
    """Simple T-bill discount return (annualised)."""
    return principal * rate_pa / 100 * tenure_days / 365


def _fd_return(principal: float, rate_pa: float, tenure_days: int) -> float:
    return principal * rate_pa / 100 * tenure_days / 365


def _invest_options(tax_amount: float, days_to_due: int) -> list[dict]:
    """
    For each investment type, how much do you need to invest today
    to generate enough return to cover the tax bill?
    Returns a list of dicts, sorted by required principal.
    """
    options = []

    def _principal_needed(rate_pa: float, days: int) -> float:
        if rate_pa <= 0 or days <= 0:
            return float("inf")
        return tax_amount / (rate_pa / 100 * days / 365)

    # T-bill 6M — only feasible if days_to_due ≥ 90
    if days_to_due >= 90:
        d = min(182, days_to_due - 7)  # leave 7-day buffer
        p = _principal_needed(INVESTMENT_RATES["tbill_6m"], d)
        ret = _tbill_return(p, INVESTMENT_RATES["tbill_6m"], d)
        options.append({
            "instrument": "T-Bill (6M)",
            "rate_pa": INVESTMENT_RATES["tbill_6m"],
            "tenure_days": d,
            "principal_needed": round(p),
            "return_generated": round(ret),
            "principal_returned": round(p),
            "risk": "Very Low",
            "liquidity": "Illiquid until maturity",
            "notes": "Bid at SGS auction via DBS/OCBC/UOB iB. Face value returned at maturity.",
            "timing_ok": True,
            "cpf_eligible": False,
        })

    # T-bill 1Y
    if days_to_due >= 270:
        d = min(365, days_to_due - 7)
        p = _principal_needed(INVESTMENT_RATES["tbill_1y"], d)
        ret = _tbill_return(p, INVESTMENT_RATES["tbill_1y"], d)
        options.append({
            "instrument": "T-Bill (1Y)",
            "rate_pa": INVESTMENT_RATES["tbill_1y"],
            "tenure_days": d,
            "principal_needed": round(p),
            "return_generated": round(ret),
            "principal_returned": round(p),
            "risk": "Very Low",
            "liquidity": "Illiquid until maturity",
            "notes": "Auction every ~4 weeks. Set maturity date ≤ Jan 31.",
            "timing_ok": True,
            "cpf_eligible": False,
        })

    # SSB 1Y effective
    if days_to_due >= 60:
        p = _principal_needed(INVESTMENT_RATES["ssb_1y"], 365)
        ret = p * INVESTMENT_RATES["ssb_1y"] / 100
        options.append({
            "instrument": "Singapore Savings Bond (1Y)",
            "rate_pa": INVESTMENT_RATES["ssb_1y"],
            "tenure_days": 365,
            "principal_needed": round(p),
            "return_generated": round(ret),
            "principal_returned": round(p),
            "risk": "Very Low",
            "liquidity": "Redeemable monthly (T+1 business day)",
            "notes": "Apply via internet banking. Max $200k/person. Redeem in Dec to get Jan payment.",
            "timing_ok": True,
            "cpf_eligible": False,
        })

    # Fixed deposit 6M
    if days_to_due >= 60:
        d = min(182, days_to_due - 3)
        p = _principal_needed(INVESTMENT_RATES["fd_6m"], d)
        ret = _fd_return(p, INVESTMENT_RATES["fd_6m"], d)
        options.append({
            "instrument": "Fixed Deposit (6M)",
            "rate_pa": INVESTMENT_RATES["fd_6m"],
            "tenure_days": d,
            "principal_needed": round(p),
            "return_generated": round(ret),
            "principal_returned": round(p),
            "risk": "Very Low",
            "liquidity": "Illiquid (early withdrawal penalty)",
            "notes": "Compare DBS/OCBC/UOB promotions. Ensure maturity before Jan 31.",
            "timing_ok": True,
            "cpf_eligible": False,
        })

    # CPF OA — can pay property tax directly
    cpf_annual_return = tax_amount  # using OA means you don't earn 2.5% on that portion
    cpf_opportunity = tax_amount * INVESTMENT_RATES["cpf_oa"] / 100
    options.append({
        "instrument": "CPF OA (Direct Payment)",
        "rate_pa": INVESTMENT_RATES["cpf_oa"],
        "tenure_days": 0,
        "principal_needed": round(tax_amount),
        "return_generated": 0,
        "principal_returned": 0,
        "risk": "Zero",
        "liquidity": "Immediate (GIRO/CPF portal)",
        "notes": (
            "Apply via CPF Board portal or GIRO. CPF OA earns 2.5% — "
            f"using SGD {tax_amount:,.0f} of OA foregoes SGD {cpf_opportunity:,.0f}/year in CPF interest. "
            "Best if you have excess OA above housing needs."
        ),
        "timing_ok": True,
        "cpf_eligible": True,
    })

    # REITs (higher yield, but price risk)
    d = 365
    shares_needed = tax_amount / (INVESTMENT_RATES["reits_div"] / 100)
    options.append({
        "instrument": "S-REITs (Dividend)",
        "rate_pa": INVESTMENT_RATES["reits_div"],
        "tenure_days": d,
        "principal_needed": round(shares_needed),
        "return_generated": round(tax_amount),
        "principal_returned": round(shares_needed),  # market risk — not guaranteed
        "risk": "Medium (price fluctuation)",
        "liquidity": "High (exchange-listed)",
        "notes": (
            "Buy diversified REIT ETF (e.g. Lion-Phillip S-REIT ETF). "
            "Dividend yield ~5.5% but principal value can fall. "
            "Dividend paid quarterly — accumulate Jan 31 pot over year."
        ),
        "timing_ok": True,
        "cpf_eligible": False,
    })

    # Sort by principal needed (ascending)
    options.sort(key=lambda x: x["principal_needed"])
    return options


def _tbill_ladder(tax_amount: float, today: date = None) -> list[dict]:
    """
    Recommend a T-bill laddering strategy to accumulate tax payment by Jan 31.
    Splits into 2 tranches if >1 year away; single tranche if <180 days.
    """
    if today is None:
        today = date.today()
    dtd = _days_to_jan31(today)
    if dtd <= 0:
        dtd = 365

    result = []
    if dtd >= 270:
        # Split into two T-bill buys
        tranche1 = round(tax_amount * 0.5)
        tranche2 = tax_amount - tranche1
        mat1 = today + timedelta(days=180)
        # Rollover tranche1 into 6M T-bill at mat1
        mat2_days = (_days_to_jan31(today) - 7)
        result.append({
            "tranche": 1,
            "amount": tranche1,
            "buy_date": today.strftime("%b %Y"),
            "tenure": "6M",
            "maturity": mat1.strftime("%b %Y"),
            "action": f"Buy SGD {tranche1:,} 6M T-bill now. At maturity, reinvest into another T-bill maturing ≤ Jan 31."
        })
        result.append({
            "tranche": 2,
            "amount": tranche2,
            "buy_date": today.strftime("%b %Y"),
            "tenure": "6M",
            "maturity": (today + timedelta(days=min(182, dtd - 7))).strftime("%b %Y"),
            "action": f"Buy SGD {tranche2:,} 6M T-bill now, maturing before Jan 31."
        })
    elif dtd >= 90:
        mat = today + timedelta(days=min(182, dtd - 7))
        result.append({
            "tranche": 1,
            "amount": tax_amount,
            "buy_date": today.strftime("%b %Y"),
            "tenure": f"{min(182, dtd - 7)} days",
            "maturity": mat.strftime("%b %Y"),
            "action": f"Buy single SGD {tax_amount:,} T-bill now, maturing just before Jan 31."
        })
    else:
        result.append({
            "tranche": 1,
            "amount": tax_amount,
            "buy_date": "Now",
            "tenure": "—",
            "maturity": "—",
            "action": (
                f"Too close to Jan 31 for T-bill. Use CPF OA or existing cash. "
                f"For next year, start T-bill ladder in {today.strftime('%b')} of the prior year."
            )
        })

    return result


@dataclass
class PropertyTaxResult:
    annual_value: float
    owner_occupied: bool
    tax_amount: float
    effective_rate_pct: float
    days_to_jan31: int
    next_jan31: date

    # Tax breakdown by band
    band_breakdown: list[dict]

    # Investment options to fund the tax
    investment_options: list[dict]

    # T-bill ladder recommendation
    tbill_ladder: list[dict]

    # Best recommendation
    recommended_instrument: str
    recommended_notes: str

    # CPF option details
    cpf_option_available: bool
    cpf_opportunity_cost: float   # CPF interest foregone


def analyse(
    annual_value: float,
    owner_occupied: bool = True,
    today: Optional[date] = None,
) -> PropertyTaxResult:
    if today is None:
        today = date.today()

    bands = OO_BANDS if owner_occupied else NOO_BANDS
    tax = _calc_tax(annual_value, bands)
    eff = (tax / annual_value * 100) if annual_value > 0 else 0

    # Band breakdown for display
    breakdown = []
    rem = annual_value
    for band, rate in bands:
        if rem <= 0:
            break
        chunk = min(rem, band)
        tax_chunk = chunk * rate
        breakdown.append({
            "band": f"On first SGD {band:,.0f}" if band < float("inf") else "Balance",
            "rate_pct": rate * 100,
            "av_in_band": round(chunk),
            "tax": round(tax_chunk),
        })
        rem -= chunk

    # Days to Jan 31
    dtd = _days_to_jan31(today)
    this_yr_jan31 = date(today.year, 1, 31)
    next_yr_jan31 = date(today.year + 1, 1, 31)
    next_jan31 = this_yr_jan31 if today <= this_yr_jan31 else next_yr_jan31

    invest_opts = _invest_options(tax, dtd)
    ladder = _tbill_ladder(tax, today)

    # Recommendation logic
    cpf_opp = tax * INVESTMENT_RATES["cpf_oa"] / 100
    if dtd < 90:
        rec = "CPF OA (Direct Payment)"
        rec_notes = (
            f"Only {dtd} days to Jan 31 — too close for T-bills. "
            f"Pay via CPF OA directly through IRAS myTax Portal or set up GIRO from CPF OA. "
            f"Opportunity cost: SGD {cpf_opp:,.0f}/year CPF interest foregone."
        )
    elif tax < 500:
        rec = "Cash (GIRO auto-debit)"
        rec_notes = (
            f"Tax bill of SGD {tax:,.0f} is low — set up GIRO for hassle-free auto-payment. "
            f"Investment overhead not worth it for small amounts."
        )
    else:
        best = next((o for o in invest_opts if o["instrument"].startswith("T-Bill") and o["timing_ok"]), None)
        if best:
            rec = best["instrument"]
            rec_notes = (
                f"Invest SGD {best['principal_needed']:,} in {best['instrument']} at {best['rate_pa']}% p.a. "
                f"Return of SGD {best['return_generated']:,} covers your SGD {tax:,.0f} tax. "
                f"Principal of SGD {best['principal_needed']:,} returned at maturity. "
                + best["notes"]
            )
        else:
            rec = "CPF OA (Direct Payment)"
            rec_notes = (
                f"Use CPF OA for simplicity. Opportunity cost: SGD {cpf_opp:,.0f}/year. "
                f"Set up recurring GIRO from CPF OA to avoid late payment charges."
            )

    return PropertyTaxResult(
        annual_value=round(annual_value),
        owner_occupied=owner_occupied,
        tax_amount=round(tax),
        effective_rate_pct=round(eff, 2),
        days_to_jan31=dtd,
        next_jan31=next_jan31,
        band_breakdown=breakdown,
        investment_options=invest_opts,
        tbill_ladder=ladder,
        recommended_instrument=rec,
        recommended_notes=rec_notes,
        cpf_option_available=True,
        cpf_opportunity_cost=round(cpf_opp),
    )
