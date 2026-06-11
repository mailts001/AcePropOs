"""
Property Portfolio Tracker — tracks user's owned properties,
calculates unrealised gain, CPF accrued interest, net equity.
Stored in SQLite.
"""
import sqlite3
import json
from pathlib import Path
from datetime import date, datetime

DB_PATH = Path(__file__).parent.parent / "propos.db"


def ensure_schema():
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id TEXT,
                property_name TEXT,
                property_type TEXT,
                town_or_district TEXT,
                flat_type TEXT,
                purchase_price REAL,
                purchase_date TEXT,
                loan_amount REAL,
                annual_rate_pct REAL DEFAULT 3.5,
                tenure_years INTEGER DEFAULT 25,
                cpf_used REAL DEFAULT 0,
                current_est_value REAL,
                monthly_rent_sgd REAL DEFAULT 0,
                notes TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def add_property(
    telegram_id: str,
    property_name: str,
    property_type: str,
    town_or_district: str,
    flat_type: str,
    purchase_price: float,
    purchase_date: str,
    loan_amount: float,
    annual_rate_pct: float,
    tenure_years: int,
    cpf_used: float,
    current_est_value: float,
    monthly_rent_sgd: float = 0,
    notes: str = "",
) -> int:
    ensure_schema()
    with sqlite3.connect(str(DB_PATH)) as conn:
        cur = conn.execute("""
            INSERT INTO portfolio
            (telegram_id,property_name,property_type,town_or_district,flat_type,
             purchase_price,purchase_date,loan_amount,annual_rate_pct,tenure_years,
             cpf_used,current_est_value,monthly_rent_sgd,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (telegram_id, property_name, property_type, town_or_district, flat_type,
              purchase_price, purchase_date, loan_amount, annual_rate_pct, tenure_years,
              cpf_used, current_est_value, monthly_rent_sgd, notes))
        conn.commit()
        return cur.lastrowid


def get_portfolio(telegram_id: str) -> list[dict]:
    ensure_schema()
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM portfolio WHERE telegram_id=? ORDER BY purchase_date", (telegram_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_property(prop_id: int, telegram_id: str):
    ensure_schema()
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("DELETE FROM portfolio WHERE id=? AND telegram_id=?", (prop_id, telegram_id))
        conn.commit()


def update_valuation(prop_id: int, new_value: float):
    ensure_schema()
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            "UPDATE portfolio SET current_est_value=?, updated_at=datetime('now') WHERE id=?",
            (new_value, prop_id)
        )
        conn.commit()


def analyse_property(prop: dict) -> dict:
    """
    Financial snapshot for one portfolio property.
    Returns capital gain, outstanding loan estimate, CPF accrued interest, net equity.
    """
    try:
        purchase_date = datetime.strptime(prop["purchase_date"], "%Y-%m-%d").date()
    except Exception:
        purchase_date = date.today()

    years_held = (date.today() - purchase_date).days / 365.25

    # Capital gain
    purchase_price = prop["purchase_price"]
    current_value = prop["current_est_value"] or purchase_price
    capital_gain = current_value - purchase_price
    gain_pct = capital_gain / purchase_price * 100 if purchase_price else 0
    annual_appreciation = (current_value / purchase_price) ** (1 / max(years_held, 0.1)) - 1 if purchase_price else 0

    # Estimated outstanding loan (simple amortisation estimate)
    loan = prop["loan_amount"]
    rate_monthly = prop["annual_rate_pct"] / 100 / 12
    n = prop["tenure_years"] * 12
    if rate_monthly > 0 and n > 0:
        monthly_pmt = loan * rate_monthly * (1 + rate_monthly)**n / ((1 + rate_monthly)**n - 1)
        months_paid = min(int(years_held * 12), n)
        outstanding = loan * (1 + rate_monthly)**months_paid - monthly_pmt * ((1 + rate_monthly)**months_paid - 1) / rate_monthly
        outstanding = max(0, outstanding)
    else:
        monthly_pmt = 0
        outstanding = loan

    # CPF accrued interest at 2.5% p.a.
    cpf_used = prop.get("cpf_used", 0)
    cpf_interest = cpf_used * ((1.025 ** years_held) - 1) if cpf_used else 0
    cpf_to_refund = cpf_used + cpf_interest

    # Net equity
    gross_equity = current_value - outstanding
    net_equity = gross_equity - cpf_to_refund

    # Rental yield
    monthly_rent = prop.get("monthly_rent_sgd", 0)
    gross_yield = (monthly_rent * 12 / current_value * 100) if monthly_rent and current_value else 0
    net_yield = max(0, gross_yield - 1.5)

    # Total return (capital + rental income)
    rental_income_total = monthly_rent * 12 * years_held if monthly_rent else 0
    total_return = capital_gain + rental_income_total

    return {
        "id": prop["id"],
        "property_name": prop["property_name"],
        "property_type": prop["property_type"],
        "purchase_price": purchase_price,
        "current_value": current_value,
        "capital_gain_sgd": round(capital_gain),
        "gain_pct": round(gain_pct, 1),
        "annual_appreciation_pct": round(annual_appreciation * 100, 1),
        "years_held": round(years_held, 1),
        "outstanding_loan": round(outstanding),
        "monthly_payment": round(monthly_pmt),
        "cpf_used": cpf_used,
        "cpf_to_refund": round(cpf_to_refund),
        "gross_equity": round(gross_equity),
        "net_equity": round(net_equity),
        "monthly_rent": monthly_rent,
        "gross_yield_pct": round(gross_yield, 2),
        "net_yield_pct": round(net_yield, 2),
        "rental_income_total": round(rental_income_total),
        "total_return_sgd": round(total_return),
        "purchase_date": str(purchase_date),
    }


def portfolio_summary(telegram_id: str) -> dict:
    """Aggregate stats across all properties."""
    props = get_portfolio(telegram_id)
    if not props:
        return {"count": 0}

    analyses = [analyse_property(p) for p in props]

    total_purchase = sum(a["purchase_price"] for a in analyses)
    total_current = sum(a["current_value"] for a in analyses)
    total_gain = sum(a["capital_gain_sgd"] for a in analyses)
    total_equity = sum(a["net_equity"] for a in analyses)
    total_rental = sum(a["rental_income_total"] for a in analyses)
    total_return = sum(a["total_return_sgd"] for a in analyses)
    total_loans = sum(a["outstanding_loan"] for a in analyses)

    return {
        "count": len(analyses),
        "total_purchase_price": round(total_purchase),
        "total_current_value": round(total_current),
        "total_capital_gain": round(total_gain),
        "total_gain_pct": round(total_gain / total_purchase * 100, 1) if total_purchase else 0,
        "total_net_equity": round(total_equity),
        "total_outstanding_loans": round(total_loans),
        "total_rental_income": round(total_rental),
        "total_return": round(total_return),
        "properties": analyses,
    }
