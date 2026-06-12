"""
Mortgage Refinancing Alert — calculates whether it's worth refinancing now.
Compares current loan rate vs indicative market rates.
Accounts for break-in period, legal fees, clawback penalties, and break-even.

Current market indicative rates (June 2026 — update quarterly):
  - 3M SORA: ~3.2%  (check MAS daily)
  - SORA + 0.8% spread (typical bank): ~4.0%
  - Best fixed 2Y package: ~3.1–3.5%
  - HDB Concessionary: 2.6% (fixed, HDB loan, no refi needed)
"""

from dataclasses import dataclass, field
from typing import Optional


# ── Live indicative market rates (update quarterly) ─────────────────────────
MARKET_RATES = {
    "sora_3m":        3.20,   # 3M SORA compounded (MAS published)
    "best_fixed_2y":  3.10,   # best bank fixed 2Y package
    "best_float":     3.80,   # SORA + typical spread
    "hdb_loan":       2.60,   # HDB concessionary rate (fixed)
}

# Typical refinancing costs
LEGAL_FEES_SGD    = 2_500   # conveyancing + legal
VALUATION_SGD     =   600   # bank valuation
FIRE_INSURANCE    =   200   # annual (already paying, assume neutral)
UPFRONT_COST_BASE = LEGAL_FEES_SGD + VALUATION_SGD  # SGD 3,100


def _monthly_instalment(loan: float, rate_pa: float, n_months: int) -> float:
    r = rate_pa / 100 / 12
    if r == 0:
        return loan / n_months
    return loan * r * (1 + r) ** n_months / ((1 + r) ** n_months - 1)


def _outstanding_loan(loan: float, rate_pa: float, tenure_months: int, paid_months: int) -> float:
    r = rate_pa / 100 / 12
    m = min(paid_months, tenure_months)
    if r == 0:
        return max(0, loan * (1 - m / tenure_months))
    pmt = _monthly_instalment(loan, rate_pa, tenure_months)
    bal = loan * (1 + r) ** m - pmt * ((1 + r) ** m - 1) / r
    return max(0, bal)


@dataclass
class RefiResult:
    current_rate_pct: float
    new_rate_pct: float
    outstanding_loan: float
    current_monthly: float
    new_monthly: float
    monthly_savings: float
    annual_savings: float
    clawback_sgd: float         # penalty for breaking lock-in
    total_refi_cost: float      # clawback + legal + valuation
    breakeven_months: int       # months until savings cover costs
    breakeven_years: float
    savings_over_5y: float      # net savings after costs, 5 years
    recommended: bool
    verdict: str
    rate_comparison: list[dict]  # table of market options


def analyse_refi(
    outstanding_loan: float,
    current_rate_pct: float,
    remaining_tenure_months: int,
    months_since_last_refi: int = 0,
    lock_in_years: float = 0,        # remaining lock-in period
    clawback_pct: float = 0.0,       # % of outstanding if break lock-in (e.g. 1.5%)
    property_type: str = "private",  # "private" | "hdb"
) -> RefiResult:

    if property_type.lower() == "hdb":
        # HDB concessionary rate is 2.6% — compare with bank best
        target_rate = MARKET_RATES["best_fixed_2y"]
        if current_rate_pct <= MARKET_RATES["hdb_loan"] + 0.1:
            # Already on HDB loan at 2.6% — better than most bank rates
            target_rate = MARKET_RATES["best_fixed_2y"]
    else:
        target_rate = min(MARKET_RATES["best_fixed_2y"], MARKET_RATES["best_float"])

    current_monthly = _monthly_instalment(outstanding_loan, current_rate_pct, remaining_tenure_months)
    new_monthly     = _monthly_instalment(outstanding_loan, target_rate, remaining_tenure_months)
    monthly_savings = current_monthly - new_monthly
    annual_savings  = monthly_savings * 12

    # Clawback if still in lock-in
    clawback = outstanding_loan * (clawback_pct / 100) if clawback_pct > 0 else 0
    total_cost = UPFRONT_COST_BASE + clawback

    # Break-even
    if monthly_savings > 0:
        breakeven_months = int(total_cost / monthly_savings) + 1
    else:
        breakeven_months = 9999

    # 5-year net savings
    savings_5y = monthly_savings * 60 - total_cost

    recommended = (
        monthly_savings >= 100
        and breakeven_months <= 24
        and current_rate_pct - target_rate >= 0.3
    )

    if current_rate_pct - target_rate < 0.1:
        verdict = (
            f"Your rate ({current_rate_pct}%) is already competitive. "
            f"Best market rate is {target_rate}% — saving is too small to justify refinancing costs."
        )
    elif not recommended:
        verdict = (
            f"Monthly savings of **SGD {monthly_savings:,.0f}** exist but break-even is "
            f"**{breakeven_months} months** — too long to justify. "
            f"Consider refinancing when your lock-in expires."
        )
    else:
        verdict = (
            f"**Refinancing is worthwhile.** Save **SGD {monthly_savings:,.0f}/month** "
            f"(SGD {annual_savings:,.0f}/year). Break-even in **{breakeven_months} months**. "
            f"Net saving over 5 years: **SGD {savings_5y:,.0f}** after all costs."
        )

    # Rate comparison table
    rate_comparison = []
    for label, rate in [
        ("Your current rate",    current_rate_pct),
        ("Best fixed 2Y",        MARKET_RATES["best_fixed_2y"]),
        ("Best float (SORA+)",   MARKET_RATES["best_float"]),
        ("HDB concessionary",    MARKET_RATES["hdb_loan"]),
    ]:
        m = _monthly_instalment(outstanding_loan, rate, remaining_tenure_months)
        rate_comparison.append({
            "Package": label,
            "Rate (%)": rate,
            "Monthly (SGD)": round(m),
            "vs Current (SGD/mo)": round(current_monthly - m),
        })

    return RefiResult(
        current_rate_pct=current_rate_pct,
        new_rate_pct=target_rate,
        outstanding_loan=round(outstanding_loan),
        current_monthly=round(current_monthly),
        new_monthly=round(new_monthly),
        monthly_savings=round(monthly_savings),
        annual_savings=round(annual_savings),
        clawback_sgd=round(clawback),
        total_refi_cost=round(total_cost),
        breakeven_months=breakeven_months,
        breakeven_years=round(breakeven_months / 12, 1),
        savings_over_5y=round(savings_5y),
        recommended=recommended,
        verdict=verdict,
        rate_comparison=rate_comparison,
    )
