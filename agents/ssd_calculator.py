"""
Seller's Stamp Duty (SSD) Calculator — Singapore residential properties.
SSD applies if you sell within 3 years of purchase (since Jan 2011).
Rates based on holding period at time of sale.

Rules (current, effective Jan 2024):
  Sold in Year 1 (≤12 months): 12% of higher of sale price or market value
  Sold in Year 2 (13–24 months): 8%
  Sold in Year 3 (25–36 months): 4%
  After 3 years: 0% (no SSD)

Industrial properties have different rates — not covered here.
Reference: IRAS (iras.gov.sg/taxes/stamp-duty/for-property/selling-property)
"""

from datetime import date, datetime
from dataclasses import dataclass
from typing import Optional


SSD_BRACKETS = [
    (12,  0.12),   # ≤12 months: 12%
    (24,  0.08),   # 13–24 months: 8%
    (36,  0.04),   # 25–36 months: 4%
]


def months_held(purchase_date: date, sale_date: Optional[date] = None) -> int:
    """Return whole months between purchase_date and sale_date (default: today)."""
    if sale_date is None:
        sale_date = date.today()
    delta = (sale_date.year - purchase_date.year) * 12 + (sale_date.month - purchase_date.month)
    # Partial month counts as a full month if day of sale < day of purchase
    if sale_date.day < purchase_date.day:
        delta -= 1
    return max(0, delta)


def ssd_rate(months: int) -> float:
    """Return SSD rate (0.0–0.12) for a given holding period in months."""
    for cap, rate in SSD_BRACKETS:
        if months <= cap:
            return rate
    return 0.0


def ssd_amount(price: float, months: int) -> float:
    """SSD payable = price × rate."""
    return price * ssd_rate(months)


def ssd_free_date(purchase_date: date) -> date:
    """Date on which SSD drops to 0% (36 months + 1 day after purchase)."""
    # Add 36 months
    y = purchase_date.year + (purchase_date.month + 36 - 1) // 12
    m = (purchase_date.month + 36 - 1) % 12 + 1
    d = min(purchase_date.day, [31,28,31,30,31,30,31,31,30,31,30,31][m-1])
    try:
        return date(y, m, d)
    except ValueError:
        return date(y, m, 28)


@dataclass
class SSDResult:
    purchase_date: date
    sale_date: date
    months_held: int
    ssd_rate_pct: float
    ssd_amount: float
    is_ssd_free: bool
    ssd_free_date: date
    days_to_ssd_free: int
    savings_if_wait: float        # SSD saved by waiting to year 3+
    net_proceeds_now: float       # after SSD
    net_proceeds_after_ssd: float # if they wait for SSD-free date
    year_brackets: list[dict]     # schedule of rates per year


def analyse(
    purchase_price: float,
    purchase_date: date,
    estimated_sale_price: Optional[float] = None,
    sale_date: Optional[date] = None,
) -> SSDResult:
    if estimated_sale_price is None:
        estimated_sale_price = purchase_price
    if sale_date is None:
        sale_date = date.today()

    # SSD is on the higher of sale price or purchase price (simplified)
    taxable_value = max(estimated_sale_price, purchase_price)

    mh = months_held(purchase_date, sale_date)
    rate = ssd_rate(mh)
    ssd = ssd_amount(taxable_value, mh)
    free_dt = ssd_free_date(purchase_date)
    days_left = max(0, (free_dt - sale_date).days)
    is_free = mh > 36

    # What if they wait until SSD-free?
    ssd_after = 0.0
    savings = ssd if not is_free else 0.0
    net_now = estimated_sale_price - ssd
    net_after = estimated_sale_price  # no SSD

    # Year-by-year bracket table
    brackets = []
    for cap, r in SSD_BRACKETS:
        prev = (SSD_BRACKETS[SSD_BRACKETS.index((cap, r)) - 1][0]
                if SSD_BRACKETS.index((cap, r)) > 0 else 0)
        in_bracket = prev < mh <= cap
        brackets.append({
            "period": f"Month {prev + 1}–{cap}",
            "rate_pct": r * 100,
            "ssd_on_price": round(taxable_value * r),
            "current": in_bracket,
        })
    brackets.append({
        "period": "After month 36",
        "rate_pct": 0,
        "ssd_on_price": 0,
        "current": mh > 36,
    })

    return SSDResult(
        purchase_date=purchase_date,
        sale_date=sale_date,
        months_held=mh,
        ssd_rate_pct=rate * 100,
        ssd_amount=round(ssd),
        is_ssd_free=is_free,
        ssd_free_date=free_dt,
        days_to_ssd_free=days_left,
        savings_if_wait=round(savings),
        net_proceeds_now=round(net_now),
        net_proceeds_after_ssd=round(net_after),
        year_brackets=brackets,
    )
