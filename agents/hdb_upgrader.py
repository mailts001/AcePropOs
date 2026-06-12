"""
HDB Upgrader Path Calculator.
Answers: "I own a HDB flat — what private condo can I afford after selling?"

Key steps:
1. Estimate net cash from HDB sale (after CPF refund + loan + agent fees)
2. Check if SSD applies (if within 3 years of purchase)
3. ABSD timing: buying before vs after selling the HDB
4. Calculate max private property budget (TDSR + LTV rules)
5. Show comparable private properties in their budget range

Regulations (2024):
- LTV for first property: 75% bank loan (need 25% down, 5% cash)
- LTV for HDB concessionary: 80% (but can't use for private)
- ABSD: 20% on 2nd property for SC (0% if HDB sold first and count resets)
  - Can apply for ABSD remission if HDB sold within 6 months of buying private
- TDSR: 55% of gross monthly income
- CPF: OA can be used for down payment (5% cash min)
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import date


def _cpf_accrued(cpf_used: float, years_held: float) -> float:
    """CPF must be refunded with 2.5% p.a. compounded interest on sale."""
    if cpf_used <= 0:
        return 0
    return cpf_used * (1.025 ** years_held) - cpf_used


def _outstanding_loan(loan: float, rate_pa: float, tenure_years: int, years_held: float) -> float:
    r = rate_pa / 100 / 12
    n = int(tenure_years * 12)
    m = min(int(years_held * 12), n)
    if r == 0:
        return max(0, loan * (1 - m / n))
    import math
    pmt = loan * r * (1 + r) ** n / ((1 + r) ** n - 1)
    bal = loan * (1 + r) ** m - pmt * ((1 + r) ** m - 1) / r
    return max(0, bal)


def _monthly_instalment(loan: float, rate_pa: float, tenure_years: int) -> float:
    r = rate_pa / 100 / 12
    n = tenure_years * 12
    if r == 0:
        return loan / n
    return loan * r * (1 + r) ** n / ((1 + r) ** n - 1)


def _bsd(price: float) -> float:
    """Buyer's Stamp Duty."""
    bsd, rem = 0.0, price
    for band, rate in [(180000, 0.01), (180000, 0.02), (640000, 0.03),
                       (500000, 0.04), (1500000, 0.05), (float("inf"), 0.06)]:
        chunk = min(rem, band)
        bsd += chunk * rate
        rem -= chunk
        if rem <= 0:
            break
    return bsd


@dataclass
class UpgraderResult:
    # HDB sale
    hdb_estimated_value: float
    hdb_outstanding_loan: float
    hdb_cpf_to_refund: float
    hdb_agent_commission: float
    hdb_ssd: float
    hdb_net_cash: float           # cash in hand after sale

    # Buying power
    cpf_oa_available: float       # CPF OA user can use for next purchase
    total_downpayment_pool: float # cash + CPF OA available
    max_loan_by_tdsr: float       # max loan from TDSR
    max_property_price: float     # total budget

    # ABSD scenarios
    absd_if_buy_before_sell: float   # 20% on condo price
    absd_if_buy_after_sell: float    # 0% (reset after HDB sold)
    absd_remission_eligible: bool    # can apply if HDB sold within 6M

    # Affordability
    monthly_instalment_estimate: float
    tdsr_used_pct: float
    monthly_income_required: float   # minimum gross income for this loan

    # Summary
    verdict: str
    warnings: list[str]
    budget_range: dict               # min/mid/max scenarios


def calculate_upgrade(
    # Current HDB
    hdb_current_value: float,
    hdb_purchase_date: date,
    hdb_outstanding_loan: float,
    hdb_cpf_used: float,
    hdb_loan_rate_pct: float = 2.6,
    hdb_tenure_years: int = 25,

    # Buyer profile
    gross_monthly_income: float = 10_000,
    cpf_oa_balance: float = 50_000,
    other_monthly_debt: float = 0,

    # Private condo loan assumptions
    condo_loan_rate_pct: float = 3.5,
    condo_loan_tenure_years: int = 25,

    # Scenario
    buy_before_selling_hdb: bool = False,
) -> UpgraderResult:
    from datetime import date as _date
    years_held = (_date.today() - hdb_purchase_date).days / 365.25

    # SSD check
    from agents.ssd_calculator import analyse as ssd_analyse, ssd_free_date
    ssd_res = ssd_analyse(hdb_current_value, hdb_purchase_date)
    hdb_ssd = ssd_res.ssd_amount

    # HDB sale proceeds
    loan_outstanding = _outstanding_loan(
        hdb_outstanding_loan, hdb_loan_rate_pct, hdb_tenure_years, years_held
    )
    cpf_interest   = _cpf_accrued(hdb_cpf_used, years_held)
    cpf_to_refund  = hdb_cpf_used + cpf_interest
    agent_comm     = hdb_current_value * 0.02  # ~2% agent
    hdb_net_cash   = hdb_current_value - loan_outstanding - cpf_to_refund - agent_comm - hdb_ssd
    hdb_net_cash   = max(0, hdb_net_cash)

    # Down payment pool: cash from HDB sale + existing CPF OA + any cash savings
    cpf_available = cpf_to_refund + cpf_oa_balance  # CPF refund goes back to OA
    total_pool    = hdb_net_cash + cpf_available

    # Max loan from TDSR (55% of gross income minus other debts)
    tdsr_max_monthly = gross_monthly_income * 0.55 - other_monthly_debt
    # Back-calculate max loan from max monthly payment
    r = condo_loan_rate_pct / 100 / 12
    n = condo_loan_tenure_years * 12
    if r > 0:
        max_loan = tdsr_max_monthly * ((1 + r) ** n - 1) / (r * (1 + r) ** n)
    else:
        max_loan = tdsr_max_monthly * n

    # Max property price: need 25% down (min 5% cash), rest loan
    # price = down + loan, down ≥ 25%, loan ≤ 75%
    # price = total_pool + max_loan (if total_pool ≥ 25% of price)
    # Iteratively: price_max = max_loan / 0.75 (LTV constraint) OR total_pool + max_loan
    price_ltv   = max_loan / 0.75           # limited by LTV
    price_funds = total_pool + max_loan     # limited by funds available
    max_price   = min(price_ltv, price_funds)

    # ABSD
    absd_if_buy_before = max_price * 0.20  # 2nd property, SC
    absd_if_buy_after  = 0.0               # HDB sold first — back to 1st property
    absd_remission     = buy_before_selling_hdb  # 6-month window

    # Estimated monthly instalment at mid-budget
    loan_at_max = max_price * 0.75
    monthly_inst = _monthly_instalment(loan_at_max, condo_loan_rate_pct, condo_loan_tenure_years)
    tdsr_pct = (monthly_inst + other_monthly_debt) / gross_monthly_income * 100
    income_required = (monthly_inst + other_monthly_debt) / 0.55

    # Budget scenarios
    budgets = {
        "conservative":  max(0, max_price * 0.75),
        "mid":           max_price,
        "stretch":       max_price * 1.1 if hdb_net_cash > 20_000 else max_price,
    }

    # Verdict
    warnings = []
    if hdb_ssd > 0:
        warnings.append(f"⚠️ SSD of SGD {hdb_ssd:,.0f} applies — consider waiting until "
                        f"{ssd_res.ssd_free_date.strftime('%b %Y')} to save SGD {ssd_res.savings_if_wait:,.0f}.")
    if hdb_net_cash < 0:
        warnings.append("⚠️ Outstanding loan + CPF refund exceeds estimated sale price — negative equity. Consult HDB.")
    if buy_before_selling_hdb:
        warnings.append(f"⚠️ Buying before selling HDB incurs 20% ABSD (SGD {absd_if_buy_before:,.0f}). "
                        f"Apply for ABSD remission if you sell HDB within 6 months of condo purchase.")
    if tdsr_pct > 55:
        warnings.append(f"⚠️ TDSR at {tdsr_pct:.0f}% — exceeds 55% limit. Reduce loan or increase income.")
    if max_price < 800_000:
        warnings.append("Budget may limit choices to Outside Central Region (OCR) or executive condos.")

    verdict = (
        f"After selling your HDB and refunding CPF, you'll have approx **SGD {hdb_net_cash:,.0f} cash** "
        f"and **SGD {cpf_available:,.0f} CPF OA** available. "
        f"With a {condo_loan_tenure_years}-year loan at {condo_loan_rate_pct}%, "
        f"you can target a private condo up to **SGD {max_price:,.0f}** "
        f"({'SGD {:,.0f}/month instalment'.format(round(monthly_inst))})."
    )

    return UpgraderResult(
        hdb_estimated_value=round(hdb_current_value),
        hdb_outstanding_loan=round(loan_outstanding),
        hdb_cpf_to_refund=round(cpf_to_refund),
        hdb_agent_commission=round(agent_comm),
        hdb_ssd=round(hdb_ssd),
        hdb_net_cash=round(hdb_net_cash),
        cpf_oa_available=round(cpf_available),
        total_downpayment_pool=round(total_pool),
        max_loan_by_tdsr=round(max_loan),
        max_property_price=round(max_price),
        absd_if_buy_before_sell=round(absd_if_buy_before),
        absd_if_buy_after_sell=0,
        absd_remission_eligible=absd_remission,
        monthly_instalment_estimate=round(monthly_inst),
        tdsr_used_pct=round(tdsr_pct, 1),
        monthly_income_required=round(income_required),
        verdict=verdict,
        warnings=warnings,
        budget_range={k: round(v) for k, v in budgets.items()},
    )
