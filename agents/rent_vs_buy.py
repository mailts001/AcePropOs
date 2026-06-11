"""
Rent vs Buy Analysis for Singapore properties.
Rule-based: zero LLM cost.

Compares total cost of renting vs buying over N years.
Accounts for: opportunity cost, CPF interest, appreciation, transaction costs (BSD/ABSD).
"""

from dataclasses import dataclass, field


@dataclass
class RentVsBuyInput:
    # Property
    purchase_price: float          # SGD
    flat_type: str = "HDB"        # "HDB" | "Condo" | "EC"
    is_first_property: bool = True
    is_sc: bool = True            # Singapore Citizen
    is_pr: bool = False           # Permanent Resident
    down_pmt_pct: float = 0.25    # % of purchase price (25% typical for 75% LTV)
    loan_rate_pct: float = 3.5    # % p.a.
    loan_tenure_years: int = 25
    cpf_used_pct: float = 0.20    # fraction of down payment from CPF OA

    # Rental alternative
    monthly_rent: float = 0       # comparable unit rent SGD/mo
    # If 0, estimated at 3.5% gross yield of purchase price

    # Assumptions
    years_horizon: int = 5
    property_appreciation_pct: float = 3.5  # % p.a.
    investment_return_pct: float = 5.0      # % p.a. if renting and investing the diff

    # Recurring costs
    monthly_maintenance: float = 300       # HDB S&CC / condo maintenance fees
    property_tax_pct: float = 0.4          # % of annual value (owner-occupier)


@dataclass
class RentVsBuyResult:
    buy_total_cost: float = 0
    rent_total_cost: float = 0
    buy_net_position: float = 0    # equity - costs at year N
    rent_net_position: float = 0   # investment portfolio value at year N
    buy_wins: bool = False
    delta_sgd: float = 0           # positive = buying is better by this amount
    breakeven_year: int = 0        # year renting becomes more expensive
    details: dict = field(default_factory=dict)
    verdict: str = ""
    assumptions: list = field(default_factory=list)


def _bsd(price: float) -> float:
    """Buyer's Stamp Duty (2023 rates)."""
    bsd = 0.0
    brackets = [
        (180_000, 0.01),
        (180_000, 0.02),
        (640_000, 0.03),
        (500_000, 0.04),
        (1_500_000, 0.05),
        (float("inf"), 0.06),
    ]
    rem = price
    for band, rate in brackets:
        chunk = min(rem, band)
        bsd += chunk * rate
        rem -= chunk
        if rem <= 0:
            break
    return bsd


def _absd(price: float, is_sc: bool, is_pr: bool, first_property: bool) -> float:
    """Additional Buyer's Stamp Duty (Feb 2023 rates)."""
    if first_property and is_sc:
        return 0.0
    if first_property and is_pr:
        return price * 0.05
    if not first_property and is_sc:
        return price * 0.20
    if not first_property and is_pr:
        return price * 0.30
    # Foreigner
    return price * 0.60


def _monthly_instalment(loan: float, rate_pa: float, years: int) -> float:
    r = rate_pa / 100 / 12
    n = years * 12
    if r == 0:
        return loan / n
    return loan * r * (1 + r)**n / ((1 + r)**n - 1)


def analyse(inp: RentVsBuyInput) -> RentVsBuyResult:
    result = RentVsBuyResult()
    details = {}

    price = inp.purchase_price
    years = inp.years_horizon

    # ── Buy side ──────────────────────────────────────────────────────────────
    # Upfront costs
    bsd = _bsd(price)
    absd = _absd(price, inp.is_sc, inp.is_pr, inp.is_first_property)
    stamp_duty = bsd + absd

    loan = price * (1 - inp.down_pmt_pct)
    down_pmt_cash = price * inp.down_pmt_pct * (1 - inp.cpf_used_pct)
    down_pmt_cpf = price * inp.down_pmt_pct * inp.cpf_used_pct
    legal_valuation = max(3_000, price * 0.005)
    upfront_cash = down_pmt_cash + stamp_duty + legal_valuation

    # Monthly costs
    monthly_loan = _monthly_instalment(loan, inp.loan_rate_pct, inp.loan_tenure_years)
    monthly_maint = inp.monthly_maintenance
    property_tax_annual = price * 0.05 * inp.property_tax_pct  # AV ~5% of price
    monthly_tax = property_tax_annual / 12
    monthly_total_buy = monthly_loan + monthly_maint + monthly_tax

    # Over N years
    total_loan_paid = monthly_loan * years * 12
    total_maint = monthly_maint * years * 12
    total_tax = monthly_tax * years * 12
    total_interest = total_loan_paid - (loan - _outstanding_loan(loan, inp.loan_rate_pct, inp.loan_tenure_years, years))
    total_interest = max(0, total_interest)

    # CPF accrued interest (must refund on sale)
    cpf_accrued = down_pmt_cpf * ((1.025 ** years) - 1)
    cpf_to_refund = down_pmt_cpf + cpf_accrued

    # Property value at year N
    future_value = price * (1 + inp.property_appreciation_pct / 100) ** years
    selling_cost = future_value * 0.01  # agent commission ~1%
    outstanding = _outstanding_loan(loan, inp.loan_rate_pct, inp.loan_tenure_years, years)
    equity = future_value - outstanding - cpf_to_refund - selling_cost

    buy_total_outlays = upfront_cash + total_maint + total_tax + total_interest
    result.buy_total_cost = buy_total_outlays
    result.buy_net_position = equity  # what you pocket after selling

    details["buy"] = {
        "upfront_cash_required": round(upfront_cash),
        "down_payment_cash": round(down_pmt_cash),
        "down_payment_cpf": round(down_pmt_cpf),
        "stamp_duty_bsd": round(bsd),
        "stamp_duty_absd": round(absd),
        "legal_valuation": round(legal_valuation),
        "monthly_loan_instalment": round(monthly_loan),
        "monthly_maintenance": round(monthly_maint),
        "monthly_property_tax": round(monthly_tax),
        "monthly_total": round(monthly_total_buy),
        "total_interest_paid": round(total_interest),
        "total_outlays_over_period": round(buy_total_outlays),
        "future_property_value": round(future_value),
        "outstanding_loan_at_sale": round(outstanding),
        "cpf_to_refund_incl_interest": round(cpf_to_refund),
        "net_proceeds_after_sale": round(equity),
    }

    # ── Rent side ─────────────────────────────────────────────────────────────
    if inp.monthly_rent <= 0:
        monthly_rent = price * 0.035 / 12  # est 3.5% gross yield
    else:
        monthly_rent = inp.monthly_rent

    total_rent = monthly_rent * years * 12

    # What you invest instead: the down payment cash + monthly savings
    monthly_savings = max(0, monthly_total_buy - monthly_rent)
    invested_lump = down_pmt_cash + stamp_duty + legal_valuation
    r = inp.investment_return_pct / 100

    # Future value of lump sum
    fv_lump = invested_lump * (1 + r) ** years
    # Future value of monthly savings (annuity)
    r_monthly = r / 12
    n_months = years * 12
    if r_monthly > 0:
        fv_savings = monthly_savings * ((1 + r_monthly)**n_months - 1) / r_monthly
    else:
        fv_savings = monthly_savings * n_months

    investment_portfolio = fv_lump + fv_savings
    result.rent_total_cost = total_rent
    result.rent_net_position = investment_portfolio

    details["rent"] = {
        "monthly_rent": round(monthly_rent),
        "total_rent_paid": round(total_rent),
        "monthly_savings_vs_buying": round(monthly_savings),
        "capital_deployed_to_investments": round(invested_lump),
        "assumed_investment_return_pct": inp.investment_return_pct,
        "investment_portfolio_value": round(investment_portfolio),
    }

    # ── Verdict ───────────────────────────────────────────────────────────────
    result.delta_sgd = round(result.buy_net_position - result.rent_net_position)
    result.buy_wins = result.buy_net_position > result.rent_net_position

    # Breakeven year
    bev = _find_breakeven(inp)
    result.breakeven_year = bev

    if result.buy_wins:
        result.verdict = (
            f"**Buying ahead by ${abs(result.delta_sgd):,.0f}** over {years} years. "
            f"Property appreciation ({inp.property_appreciation_pct}% p.a.) outpaces "
            f"renting + investing ({inp.investment_return_pct}% p.a.)."
        )
    else:
        result.verdict = (
            f"**Renting ahead by ${abs(result.delta_sgd):,.0f}** over {years} years. "
            f"Investment returns ({inp.investment_return_pct}% p.a.) exceed property gains, "
            f"but buying may still win after year {bev if bev > 0 else '?'}."
        )

    result.assumptions = [
        f"Property appreciation: {inp.property_appreciation_pct}% p.a.",
        f"Investment return (renting scenario): {inp.investment_return_pct}% p.a.",
        f"Loan rate: {inp.loan_rate_pct}% p.a., {inp.loan_tenure_years}-year tenure",
        f"Down payment: {inp.down_pmt_pct*100:.0f}% ({inp.cpf_used_pct*100:.0f}% from CPF OA)",
        "CPF OA accrued interest: 2.5% p.a.",
        "Selling costs: ~1% of future value",
        "Analysis is illustrative — does not account for taxes on investment returns.",
    ]

    result.details = details
    return result


def _outstanding_loan(loan, rate_pa, tenure_years, years_elapsed):
    """Remaining loan balance after years_elapsed years."""
    r = rate_pa / 100 / 12
    n = tenure_years * 12
    m = min(int(years_elapsed * 12), n)
    if r == 0:
        return max(0, loan - loan / n * m)
    pmt = loan * r * (1 + r)**n / ((1 + r)**n - 1)
    bal = loan * (1 + r)**m - pmt * ((1 + r)**m - 1) / r
    return max(0, bal)


def _find_breakeven(inp: RentVsBuyInput) -> int:
    """Year at which buying net position overtakes renting."""
    for yr in range(1, 31):
        test = RentVsBuyInput(
            purchase_price=inp.purchase_price,
            flat_type=inp.flat_type,
            is_first_property=inp.is_first_property,
            is_sc=inp.is_sc,
            is_pr=inp.is_pr,
            down_pmt_pct=inp.down_pmt_pct,
            loan_rate_pct=inp.loan_rate_pct,
            loan_tenure_years=inp.loan_tenure_years,
            cpf_used_pct=inp.cpf_used_pct,
            monthly_rent=inp.monthly_rent,
            years_horizon=yr,
            property_appreciation_pct=inp.property_appreciation_pct,
            investment_return_pct=inp.investment_return_pct,
            monthly_maintenance=inp.monthly_maintenance,
            property_tax_pct=inp.property_tax_pct,
        )
        r = analyse(test)
        if r.buy_wins:
            return yr
    return 0


def analyse_dict(
    purchase_price: float,
    flat_type: str = "HDB",
    is_first_property: bool = True,
    is_sc: bool = True,
    is_pr: bool = False,
    down_pmt_pct: float = 0.25,
    loan_rate_pct: float = 3.5,
    loan_tenure_years: int = 25,
    cpf_used_pct: float = 0.20,
    monthly_rent: float = 0,
    years_horizon: int = 5,
    property_appreciation_pct: float = 3.5,
    investment_return_pct: float = 5.0,
    monthly_maintenance: float = 300,
    property_tax_pct: float = 0.4,
) -> dict:
    inp = RentVsBuyInput(
        purchase_price=purchase_price,
        flat_type=flat_type,
        is_first_property=is_first_property,
        is_sc=is_sc,
        is_pr=is_pr,
        down_pmt_pct=down_pmt_pct,
        loan_rate_pct=loan_rate_pct,
        loan_tenure_years=loan_tenure_years,
        cpf_used_pct=cpf_used_pct,
        monthly_rent=monthly_rent,
        years_horizon=years_horizon,
        property_appreciation_pct=property_appreciation_pct,
        investment_return_pct=investment_return_pct,
        monthly_maintenance=monthly_maintenance,
        property_tax_pct=property_tax_pct,
    )
    r = analyse(inp)
    return {
        "buy_net_position": r.buy_net_position,
        "rent_net_position": r.rent_net_position,
        "buy_wins": r.buy_wins,
        "delta_sgd": r.delta_sgd,
        "breakeven_year": r.breakeven_year,
        "verdict": r.verdict,
        "buy_details": r.details.get("buy", {}),
        "rent_details": r.details.get("rent", {}),
        "assumptions": r.assumptions,
    }
