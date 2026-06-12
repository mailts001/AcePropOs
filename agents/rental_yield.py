"""
Rental Yield Calculator — buy-to-let analysis for Singapore properties.

Computes:
- Gross yield: annual rent / purchase price
- Net yield: after property tax, agent fees, maintenance, insurance, vacancy
- Monthly cash flow: rent - mortgage instalment - monthly expenses
- Breakeven rent: minimum rent to cover all holding costs
- Yield vs alternatives: T-bill, CPF OA, STI ETF benchmark
- Years to payback purchase price from net rental income
- Mortgage coverage ratio: rent / instalment

Singapore-specific costs factored in:
- Property tax (NOO rates on AV ≈ 10-12% of annual rent)
- Agent commission: 1 month rent/year (0.5 for renewal)
- Maintenance / sinking fund: ~$200-400/month for condo, $50 for HDB
- Fire insurance: ~$200/year (HDB mandatory, condo optional)
- Vacancy allowance: 1 month/year default (~8.3%)
- ABSD cost of carry: spread over holding period
"""

from dataclasses import dataclass, field
from typing import Optional


# Benchmark rates for comparison (update quarterly)
BENCHMARKS = {
    "tbill_6m":   3.80,   # % p.a.
    "cpf_oa":     2.50,   # % p.a.
    "sti_etf":    6.50,   # % p.a. historical total return
    "ssb":        3.10,   # % p.a.
    "sg_reit":    5.50,   # % p.a. S-REIT avg dividend yield
}

# NOO property tax bands (simplified — see property_tax.py for full calc)
def _noo_tax(av: float) -> float:
    bands = [(30_000, 0.11), (15_000, 0.16), (15_000, 0.21), (float("inf"), 0.27)]
    tax, rem = 0.0, av
    for band, rate in bands:
        chunk = min(rem, band)
        tax += chunk * rate
        rem -= chunk
        if rem <= 0:
            break
    return tax


def _monthly_instalment(loan: float, rate_pa: float, tenure_years: int) -> float:
    r = rate_pa / 100 / 12
    n = tenure_years * 12
    if r == 0 or n == 0:
        return loan / n if n else 0
    return loan * r * (1 + r) ** n / ((1 + r) ** n - 1)


@dataclass
class RentalYieldResult:
    # Inputs summary
    purchase_price: float
    monthly_rent: float
    floor_area_sqft: float
    is_mortgaged: bool

    # Yield metrics
    gross_yield_pct: float           # annual rent / price
    net_yield_pct: float             # after all costs
    net_yield_on_equity_pct: float   # net income / equity (down payment)

    # Monthly cash flow
    monthly_rent_income: float
    monthly_mortgage: float
    monthly_expenses: float          # tax + agent + maintenance + insurance / 12
    monthly_vacancy_cost: float      # 1 month vacancy / 12
    monthly_net_cashflow: float      # rent - mortgage - expenses - vacancy

    # Annual breakdown
    annual_rent: float
    annual_expenses: dict            # itemised: tax, agent, maintenance, insurance, vacancy
    annual_net_income: float

    # Thresholds
    breakeven_rent: float            # min monthly rent to break even (cover all costs)
    mortgage_coverage_ratio: float   # rent / instalment (>1.2 is healthy)

    # Payback
    years_to_payback: float          # purchase price / annual net income

    # Benchmark comparison
    benchmarks: list[dict]           # yield vs T-bill, CPF, REITs, etc.

    # Verdict
    verdict: str
    tips: list[str]


def analyse(
    purchase_price: float,
    monthly_rent: float,
    floor_area_sqft: float = 0,
    property_type: str = "condo",        # "hdb" | "condo" | "landed"

    # Mortgage (optional — set loan=0 if fully paid)
    loan_amount: float = 0,
    loan_rate_pct: float = 3.5,
    loan_tenure_years: int = 25,

    # Overrides (0 = auto-estimate)
    annual_maintenance: float = 0,       # condo maintenance fees
    vacancy_months_per_year: float = 1,  # default 1 month vacancy/year
    annual_insurance: float = 0,

    # ABSD paid (to include in cost of carry)
    absd_paid: float = 0,
    holding_years: int = 10,             # expected hold for ABSD amortisation
) -> RentalYieldResult:

    pt = property_type.lower()

    # ── Annual rent ────────────────────────────────────────────────────────────
    annual_rent = monthly_rent * 12

    # ── Annual expenses ────────────────────────────────────────────────────────
    # 1. Property tax (NOO rates, AV ≈ annual rent)
    av = annual_rent  # IRAS sets AV = estimated annual rental value
    prop_tax = _noo_tax(av)

    # 2. Agent commission (~1 month per year for 1-year tenancy, 0.5 for 2-year)
    agent_commission = monthly_rent * 1.0  # 1 month per year average

    # 3. Maintenance / sinking fund
    if annual_maintenance == 0:
        if pt == "hdb":
            annual_maintenance = 600       # ~$50/month service & conservancy
        elif pt == "landed":
            annual_maintenance = 6_000     # higher upkeep
        else:
            # Condo: estimate by size
            if floor_area_sqft >= 1500:
                annual_maintenance = 5_400  # ~$450/month
            elif floor_area_sqft >= 1000:
                annual_maintenance = 4_200  # ~$350/month
            else:
                annual_maintenance = 3_000  # ~$250/month

    # 4. Fire / landlord insurance
    if annual_insurance == 0:
        annual_insurance = 600 if pt == "condo" else 200  # fire + content basic

    # 5. Vacancy cost
    vacancy_cost = monthly_rent * vacancy_months_per_year

    # 6. ABSD cost of carry (amortised over holding period)
    absd_annual = absd_paid / holding_years if holding_years > 0 else 0

    # 7. Minor repairs / touch-up between tenancies
    repairs = monthly_rent * 0.5  # half-month per year

    annual_expenses_dict = {
        "Property Tax (NOO)":  round(prop_tax),
        "Agent Commission":    round(agent_commission),
        "Maintenance/S&CC":    round(annual_maintenance),
        "Insurance":           round(annual_insurance),
        "Vacancy":             round(vacancy_cost),
        "Repairs/Touch-up":    round(repairs),
        "ABSD Amortised":      round(absd_annual),
    }
    total_annual_expenses = sum(annual_expenses_dict.values())

    # ── Mortgage ───────────────────────────────────────────────────────────────
    monthly_mortgage = 0.0
    if loan_amount > 0:
        monthly_mortgage = _monthly_instalment(loan_amount, loan_rate_pct, loan_tenure_years)
    annual_mortgage = monthly_mortgage * 12

    # ── Net income ─────────────────────────────────────────────────────────────
    annual_net_income = annual_rent - total_annual_expenses
    monthly_net_cashflow = annual_net_income / 12 - monthly_mortgage

    # ── Yield calculations ─────────────────────────────────────────────────────
    gross_yield = annual_rent / purchase_price * 100 if purchase_price else 0
    net_yield   = annual_net_income / purchase_price * 100 if purchase_price else 0

    equity = purchase_price - loan_amount
    net_yield_on_equity = annual_net_income / equity * 100 if equity > 0 else 0

    # ── Breakeven rent ─────────────────────────────────────────────────────────
    # Solve: 12 × R - expenses(R) - 12 × mortgage = 0
    # expenses depend on R (prop tax + agent + vacancy + repairs ~ 3.5 months of R + fixed)
    # Iterative approach: fixed costs + variable % of rent
    fixed_costs = annual_maintenance + annual_insurance + absd_annual
    # variable = prop_tax(12R) + 1×R(agent) + vacancy_months×R + 0.5×R(repairs)
    # prop_tax on NOO: first 30k @ 11% etc — for small AV, ~11% of AV = 11% of 12R = 1.32R
    # variable ≈ 1.32 + 1 + vacancy + 0.5 = variable multiplier on monthly_rent
    var_multiplier = 1.32 + 1.0 + vacancy_months_per_year + 0.5  # months equiv per year
    # breakeven: 12R = fixed + var_multiplier × R + 12 × mortgage
    # R × (12 - var_multiplier) = fixed + 12 × mortgage
    denom = 12 - var_multiplier
    if denom > 0:
        breakeven_rent = (fixed_costs + annual_mortgage) / denom
    else:
        breakeven_rent = monthly_mortgage + (fixed_costs / 12)

    # ── Mortgage coverage ratio ────────────────────────────────────────────────
    mcr = monthly_rent / monthly_mortgage if monthly_mortgage > 0 else float("inf")

    # ── Payback ───────────────────────────────────────────────────────────────
    years_payback = purchase_price / annual_net_income if annual_net_income > 0 else float("inf")

    # ── Benchmark comparison ──────────────────────────────────────────────────
    benchmarks = []
    for name, rate in BENCHMARKS.items():
        return_sgd = purchase_price * rate / 100
        benchmarks.append({
            "Instrument":         name.replace("_", " ").title(),
            "Yield (%)":          rate,
            "Annual Return (SGD)": round(return_sgd),
            "vs Your Net Yield":  round(net_yield - rate, 2),
        })
    benchmarks.sort(key=lambda x: x["Yield (%)"], reverse=True)

    # ── Verdict ────────────────────────────────────────────────────────────────
    tips = []
    if net_yield < 2.5:
        tips.append("⚠️ Net yield below 2.5% — T-bills currently offer similar returns with zero effort.")
    if net_yield < BENCHMARKS["tbill_6m"]:
        tips.append(f"⚠️ Net yield ({net_yield:.1f}%) is below current T-bill rate ({BENCHMARKS['tbill_6m']}%). "
                    f"Consider whether the capital appreciation thesis justifies the spread.")
    if mcr < 1.2 and monthly_mortgage > 0:
        tips.append(f"⚠️ Mortgage coverage ratio {mcr:.1f}x — rent barely covers instalment. "
                    f"Any vacancy month creates negative cashflow.")
    if mcr >= 1.5:
        tips.append(f"✅ Strong mortgage coverage {mcr:.1f}x — rent covers instalment with buffer.")
    if monthly_net_cashflow > 0:
        tips.append(f"✅ Positive monthly cashflow SGD {monthly_net_cashflow:,.0f} after all costs and mortgage.")
    else:
        tips.append(f"⚠️ Negative monthly cashflow SGD {monthly_net_cashflow:,.0f} — you're topping up each month.")
    if net_yield >= 4.0:
        tips.append("✅ Net yield ≥ 4% — healthy buy-to-let return for Singapore market.")
    tips.append(f"💡 Your breakeven rent is SGD {breakeven_rent:,.0f}/month. "
                f"{'You are above breakeven.' if monthly_rent >= breakeven_rent else 'Current rent is below breakeven — adjust pricing.'}")
    tips.append("🛡️ Ensure you have landlord fire insurance (from ~SGD 200/year) and content insurance to protect your investment.")

    if net_yield >= 4.0 and monthly_net_cashflow > 0:
        verdict = (
            f"**Strong buy-to-let case.** Net yield of **{net_yield:.1f}%** with positive monthly "
            f"cashflow of **SGD {monthly_net_cashflow:,.0f}**. Above T-bill rate and generating real income."
        )
    elif net_yield >= 2.5:
        verdict = (
            f"**Marginal yield — capital appreciation is key.** Net yield **{net_yield:.1f}%** is below "
            f"T-bill benchmark. This investment makes sense only if you expect property value appreciation "
            f"of >{BENCHMARKS['tbill_6m'] - net_yield:.1f}%/year to compensate."
        )
    else:
        verdict = (
            f"**Yield is weak at {net_yield:.1f}%.** Net income barely justifies the risk and illiquidity "
            f"vs financial instruments. Re-evaluate rental pricing or holding costs."
        )

    return RentalYieldResult(
        purchase_price=round(purchase_price),
        monthly_rent=round(monthly_rent),
        floor_area_sqft=floor_area_sqft,
        is_mortgaged=loan_amount > 0,
        gross_yield_pct=round(gross_yield, 2),
        net_yield_pct=round(net_yield, 2),
        net_yield_on_equity_pct=round(net_yield_on_equity, 2),
        monthly_rent_income=round(monthly_rent),
        monthly_mortgage=round(monthly_mortgage),
        monthly_expenses=round(total_annual_expenses / 12),
        monthly_vacancy_cost=round(vacancy_cost / 12),
        monthly_net_cashflow=round(monthly_net_cashflow),
        annual_rent=round(annual_rent),
        annual_expenses=annual_expenses_dict,
        annual_net_income=round(annual_net_income),
        breakeven_rent=round(breakeven_rent),
        mortgage_coverage_ratio=round(mcr, 2),
        years_to_payback=round(years_payback, 1),
        benchmarks=benchmarks,
        verdict=verdict,
        tips=tips,
    )
