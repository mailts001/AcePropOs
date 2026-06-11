"""
MOP (Minimum Occupation Period) Tracker for HDB flats.
Rules as of 2021 HDB policy.
"""
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

MOP_YEARS = 5          # Standard HDB MOP from date of key collection
MOP_YEARS_SUBSIDISED = 5   # Same for subsidised flats (BTO/DBSS/SBF)
MOP_YEARS_PRIVATE = 0  # Private property — no MOP

# What you can do AFTER MOP
POST_MOP_OPTIONS = [
    "Sell the flat on the open resale market",
    "Rent out the entire flat (not just rooms)",
    "Apply for a new BTO or purchase an EC",
    "Upgrade to a private property while keeping the HDB",
    "Transfer flat ownership to an eligible family member",
]

# Common questions
MOP_NOTES = [
    "MOP starts from the date you collect your keys (Vacant Possession date), not the purchase date or SPA signing.",
    "The MOP clock pauses if you rent out your entire flat illegally or move out for an extended period.",
    "You can still rent out individual rooms during MOP with HDB approval.",
    "Subletting the whole flat during MOP is not allowed — only individual rooms.",
    "Buying a private property during MOP is allowed, but you must continue living in the HDB.",
    "If you sell within MOP, you must repay the CPF used plus accrued interest (2.5% p.a.).",
]


def calculate_mop(
    key_collection_date: date,
    flat_type: str = "BTO",
) -> dict:
    """
    Calculate MOP completion date and status.
    key_collection_date: date keys were received from HDB
    """
    mop_years = MOP_YEARS
    mop_end = key_collection_date + relativedelta(years=mop_years)
    today = date.today()

    if today >= mop_end:
        status = "completed"
        days_remaining = 0
        months_remaining = 0
        pct_complete = 100.0
    else:
        status = "in_progress"
        delta = mop_end - today
        days_remaining = delta.days
        months_remaining = (mop_end.year - today.year) * 12 + (mop_end.month - today.month)
        total_days = (mop_end - key_collection_date).days
        elapsed_days = (today - key_collection_date).days
        pct_complete = round(min(100, elapsed_days / total_days * 100), 1)

    years_elapsed = relativedelta(today, key_collection_date)

    return {
        "key_collection_date": str(key_collection_date),
        "mop_end_date": str(mop_end),
        "mop_years": mop_years,
        "status": status,
        "days_remaining": days_remaining,
        "months_remaining": months_remaining,
        "pct_complete": pct_complete,
        "years_elapsed": years_elapsed.years,
        "months_elapsed": years_elapsed.months,
        "approaching_mop": 0 < months_remaining <= 12,
        "post_mop_options": POST_MOP_OPTIONS if status == "completed" else [],
        "notes": MOP_NOTES,
    }


def mop_financial_snapshot(
    purchase_price: float,
    cpf_used: float,
    current_market_value: float,
    outstanding_loan: float,
    key_collection_date: date,
) -> dict:
    """
    Financial snapshot for MOP decision — what you'd net if you sell now vs wait.
    CPF accrued interest must be refunded to CPF OA on sale.
    """
    mop = calculate_mop(key_collection_date)
    today = date.today()

    # CPF accrued interest at 2.5% p.a. from date CPF was used
    years_used = (today - key_collection_date).days / 365.25
    cpf_accrued_interest = cpf_used * ((1.025 ** years_used) - 1)
    cpf_to_refund = cpf_used + cpf_accrued_interest

    # Net proceeds
    gross_proceeds = current_market_value
    net_after_loan = gross_proceeds - outstanding_loan
    net_after_cpf = net_after_loan - cpf_to_refund
    capital_gain = current_market_value - purchase_price
    gain_pct = capital_gain / purchase_price * 100

    # Implied annual appreciation
    if years_used > 0:
        annual_appreciation = (current_market_value / purchase_price) ** (1 / years_used) - 1
    else:
        annual_appreciation = 0

    return {
        "mop_status": mop["status"],
        "mop_end_date": mop["mop_end_date"],
        "purchase_price": purchase_price,
        "current_market_value": current_market_value,
        "capital_gain_sgd": round(capital_gain, 0),
        "gain_pct": round(gain_pct, 1),
        "annual_appreciation_pct": round(annual_appreciation * 100, 1),
        "outstanding_loan_sgd": outstanding_loan,
        "cpf_used_sgd": cpf_used,
        "cpf_accrued_interest_sgd": round(cpf_accrued_interest, 0),
        "cpf_to_refund_sgd": round(cpf_to_refund, 0),
        "net_cash_in_hand_sgd": round(net_after_cpf, 0),
        "can_sell_today": mop["status"] == "completed",
        "warning": "Cannot sell entire flat yet — MOP not completed." if mop["status"] != "completed" else None,
        "tip": (
            f"You have {mop['months_remaining']} months until MOP. "
            f"Consider preparing paperwork and engaging an agent 3 months before MOP end date."
            if mop.get("approaching_mop") else
            "MOP completed — you are free to list on the open market." if mop["status"] == "completed" else
            f"MOP ends {mop['mop_end_date']}. You are {mop['pct_complete']}% through."
        ),
    }
