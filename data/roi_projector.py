"""
Property Investment ROI Projector — Singapore.
Computes net rental yield, leveraged/unleveraged return, capital gain scenarios.
Zero API cost — all rule-based arithmetic.
"""

# Historical Singapore private condo capital appreciation (annual %, rough benchmarks)
CAPITAL_GAIN_SCENARIOS = {
    "bear":   {"label": "Bear (flat market)", "annual_pct": 0.5},
    "base":   {"label": "Base (moderate growth)", "annual_pct": 3.0},
    "bull":   {"label": "Bull (strong demand)", "annual_pct": 5.5},
    "prime":  {"label": "Prime district boom", "annual_pct": 7.0},
}

# Singapore average gross rental yields by property type (2024-25 data)
GROSS_YIELD_BENCHMARKS = {
    "HDB": {"low": 3.5, "mid": 4.5, "high": 5.5},
    "Condo (outside central)": {"low": 2.8, "mid": 3.5, "high": 4.2},
    "Condo (central)": {"low": 2.2, "mid": 2.8, "high": 3.5},
    "Landed": {"low": 1.8, "mid": 2.3, "high": 2.8},
}

# Typical annual holding costs as % of property value
HOLDING_COST_RATES = {
    "property_tax_owner_occupied": 0.004,   # owner-occupied progressive, avg ~0.4%
    "property_tax_investment": 0.012,        # investment property, avg ~1.2%
    "maintenance_condo": 0.006,              # S&CC + maintenance, avg ~0.6%
    "maintenance_hdb": 0.003,
    "insurance": 0.001,
    "vacancy_allowance": 0.08,              # 1 month vacancy per year = 8.3%
    "agent_fee": 0.083,                      # 1 month rent = ~8.3% of annual rent
    "repairs": 0.005,
}


def project_roi(
    purchase_price: float,
    loan_amount: float,
    annual_rate_pct: float,
    tenure_years: int,
    monthly_rent_sgd: float,
    property_type: str = "Condo (outside central)",
    hold_years: int = 5,
    absd_sgd: float = 0,
    bsd_sgd: float = 0,
) -> dict:
    """
    Full investment return breakdown:
    - Gross / net rental yield
    - Monthly cash flow (after mortgage + costs)
    - Capital gain scenarios over hold period
    - Total return (income + capital) leveraged vs unleveraged
    - Payback period
    """
    annual_rent = monthly_rent_sgd * 12
    gross_yield = annual_rent / purchase_price * 100

    # ── Annual costs ──────────────────────────────────────────────────────────
    holding = HOLDING_COST_RATES
    prop_tax = purchase_price * holding["property_tax_investment"]
    maint_key = "maintenance_hdb" if "HDB" in property_type else "maintenance_condo"
    maintenance = purchase_price * holding[maint_key]
    insurance = purchase_price * holding["insurance"]
    vacancy = annual_rent * holding["vacancy_allowance"]
    agent = annual_rent * holding["agent_fee"]
    repairs = purchase_price * holding["repairs"]
    total_annual_costs = prop_tax + maintenance + insurance + vacancy + agent + repairs

    net_annual_income = annual_rent - total_annual_costs
    net_yield = net_annual_income / purchase_price * 100

    # ── Mortgage ──────────────────────────────────────────────────────────────
    r = annual_rate_pct / 100 / 12
    n = tenure_years * 12
    monthly_mortgage = loan_amount * r * (1 + r)**n / ((1 + r)**n - 1) if r > 0 else loan_amount / n
    annual_mortgage = monthly_mortgage * 12

    monthly_cashflow = monthly_rent_sgd - monthly_mortgage - total_annual_costs / 12
    annual_cashflow = monthly_cashflow * 12

    # ── Capital gain scenarios ─────────────────────────────────────────────────
    equity_invested = purchase_price - loan_amount + absd_sgd + bsd_sgd
    scenarios = {}
    for key, scen in CAPITAL_GAIN_SCENARIOS.items():
        future_value = purchase_price * (1 + scen["annual_pct"] / 100) ** hold_years
        capital_gain = future_value - purchase_price
        # Outstanding loan at hold_years
        n_remaining = (tenure_years - hold_years) * 12
        if r > 0 and n_remaining > 0:
            outstanding = monthly_mortgage * ((1 + r)**n_remaining - 1) / (r * (1 + r)**n_remaining)
        else:
            outstanding = max(0, loan_amount - monthly_mortgage * hold_years * 12)
        net_proceeds = future_value - outstanding
        total_income = annual_cashflow * hold_years
        total_return_sgd = capital_gain + total_income
        roi_unleveraged = total_return_sgd / purchase_price * 100
        roi_leveraged = total_return_sgd / equity_invested * 100 if equity_invested > 0 else 0
        annual_roi = (1 + roi_leveraged / 100) ** (1 / hold_years) - 1

        scenarios[key] = {
            "label": scen["label"],
            "annual_appreciation_pct": scen["annual_pct"],
            "future_value_sgd": round(future_value, 0),
            "capital_gain_sgd": round(capital_gain, 0),
            "total_rental_income_sgd": round(total_income, 0),
            "total_return_sgd": round(total_return_sgd, 0),
            "roi_unleveraged_pct": round(roi_unleveraged, 1),
            "roi_leveraged_pct": round(roi_leveraged, 1),
            "annualised_roi_pct": round(annual_roi * 100, 1),
            "net_sale_proceeds_sgd": round(net_proceeds, 0),
        }

    # Payback: years until cumulative net cashflow turns positive
    payback_years = None
    cumulative = -equity_invested
    for yr in range(1, 31):
        cumulative += annual_cashflow
        fv = purchase_price * (1 + CAPITAL_GAIN_SCENARIOS["base"]["annual_pct"] / 100) ** yr
        if cumulative + (fv - purchase_price) >= 0:
            payback_years = yr
            break

    # Yield benchmark comparison
    bench = GROSS_YIELD_BENCHMARKS.get(property_type, GROSS_YIELD_BENCHMARKS["Condo (outside central)"])
    yield_vs_benchmark = "above" if gross_yield >= bench["mid"] else "below"

    return {
        "purchase_price": purchase_price,
        "equity_invested": round(equity_invested, 0),
        "annual_rent": round(annual_rent, 0),
        "gross_yield_pct": round(gross_yield, 2),
        "net_yield_pct": round(net_yield, 2),
        "monthly_cashflow_sgd": round(monthly_cashflow, 0),
        "annual_cashflow_sgd": round(annual_cashflow, 0),
        "cashflow_positive": monthly_cashflow > 0,
        "annual_costs_breakdown": {
            "property_tax_sgd": round(prop_tax, 0),
            "maintenance_sgd": round(maintenance, 0),
            "insurance_sgd": round(insurance, 0),
            "vacancy_allowance_sgd": round(vacancy, 0),
            "agent_fees_sgd": round(agent, 0),
            "repairs_sgd": round(repairs, 0),
            "total_sgd": round(total_annual_costs, 0),
        },
        "capital_scenarios": scenarios,
        "payback_years": payback_years,
        "yield_benchmark": {
            "property_type": property_type,
            "market_low_pct": bench["low"],
            "market_mid_pct": bench["mid"],
            "market_high_pct": bench["high"],
            "vs_benchmark": yield_vs_benchmark,
        },
        "monthly_mortgage_sgd": round(monthly_mortgage, 0),
    }


def affordability_planner(
    gross_monthly_income: float,
    cpf_oa_monthly: float,
    cash_savings: float,
    is_hdb: bool = True,
    profile: str = "SC",
    property_count: int = 1,
    tenure_years: int = 25,
    rate_pct: float = 3.68,
) -> dict:
    """
    What can I afford? Derives max purchase price from income + CPF + cash.
    Accounts for ABSD, BSD, downpayment, TDSR.
    """
    from data.stamp_duty import full_stamp_duty

    TDSR_LIMIT = 0.55
    MSR_LIMIT = 0.30
    limit = MSR_LIMIT if is_hdb and property_count == 1 else TDSR_LIMIT
    max_monthly_repayment = gross_monthly_income * limit

    # Max loan from repayment capacity
    r = rate_pct / 100 / 12
    n = tenure_years * 12
    max_loan = max_monthly_repayment * ((1 + r)**n - 1) / (r * (1 + r)**n) if r > 0 else max_monthly_repayment * n

    # LTV for first property
    ltv = 0.80 if is_hdb else 0.75

    # Max price from loan capacity: price = loan / ltv
    max_price_from_loan = max_loan / ltv

    # Now check if cash + CPF can cover downpayment + stamp duties at that price
    # Iterate: stamp duties depend on price
    best_price = max_price_from_loan
    for _ in range(3):  # converge in 3 steps
        sd = full_stamp_duty(best_price, profile, property_count, is_hdb)
        cash_needed = sd["min_cash_downpayment_sgd"] * (1 - ltv) / (1 - ltv) + sd["total_stamp_duty_sgd"]
        # 5% must be cash (no CPF for first 5%), rest can be CPF OA
        cash_5pct = best_price * 0.05
        cpf_portion = best_price * (1 - ltv) - cash_5pct
        total_cash_needed = cash_5pct + sd["total_stamp_duty_sgd"]
        total_cpf_needed = cpf_portion

        if cash_savings < total_cash_needed:
            # Scale down price until affordable
            best_price = best_price * cash_savings / total_cash_needed * 0.95

    sd = full_stamp_duty(best_price, profile, property_count, is_hdb)
    loan = best_price * ltv
    monthly = loan * r * (1 + r)**n / ((1 + r)**n - 1) if r > 0 else loan / n

    return {
        "max_purchase_price_sgd": round(best_price, -3),  # round to nearest 1k
        "max_loan_sgd": round(loan, 0),
        "monthly_repayment_sgd": round(monthly, 0),
        "cash_needed_for_downpayment_sgd": round(best_price * 0.05, 0),
        "cpf_for_downpayment_sgd": round(best_price * (1 - ltv) - best_price * 0.05, 0),
        "stamp_duty_cash_sgd": round(sd["total_stamp_duty_sgd"], 0),
        "total_cash_outlay_sgd": round(best_price * 0.05 + sd["total_stamp_duty_sgd"], 0),
        "income_limit_used": f"{'MSR 30%' if is_hdb and property_count == 1 else 'TDSR 55%'}",
        "profile": profile,
        "is_hdb": is_hdb,
    }
