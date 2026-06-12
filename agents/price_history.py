"""
Project Price History — per-project PSF trend from URA cache.
Groups transactions by quarter and computes median/mean PSF.
Used for: chart on Property page, trend lines, YoY comparison.
"""

from typing import Optional
from collections import defaultdict
import statistics


def _quarter(date_str: str) -> str:
    """Convert 'MM/YYYY' or 'YYYY-MM' or 'YYYY-QX' → 'YYYY-QX'."""
    s = str(date_str).strip()
    if not s:
        return "Unknown"
    # Try MM/YYYY
    if "/" in s and len(s) <= 7:
        try:
            parts = s.split("/")
            m, y = int(parts[0]), int(parts[1])
            q = (m - 1) // 3 + 1
            return f"{y}-Q{q}"
        except Exception:
            pass
    # Try YYYY-MM-DD or YYYY-MM
    if "-" in s:
        try:
            parts = s.split("-")
            y = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 1
            q = (m - 1) // 3 + 1
            return f"{y}-Q{q}"
        except Exception:
            pass
    # Already YYYY-QX
    if "Q" in s.upper():
        return s.upper()
    return s


def get_project_history(
    project_name: str,
    transactions: list[dict],
    property_type: Optional[str] = None,
) -> dict:
    """
    Filter URA transactions for a project and return quarterly PSF summary.

    Returns:
    {
      "project": str,
      "match_count": int,
      "quarters": [{"quarter": "YYYY-QX", "median_psf": X, "mean_psf": X,
                    "min_psf": X, "max_psf": X, "count": X, "median_price": X}],
      "latest_median_psf": float,
      "earliest_median_psf": float,
      "psf_change_pct": float,
      "area_types": list[str],
    }
    """
    project_name_lower = project_name.lower().strip()
    matches = []

    for txn in transactions:
        name = str(txn.get("project", "") or txn.get("projectName", "")).lower()
        if project_name_lower not in name:
            continue
        if property_type:
            pt = str(txn.get("propertyType", "") or txn.get("property_type", "")).lower()
            if property_type.lower() not in pt:
                continue
        matches.append(txn)

    if not matches:
        return {
            "project": project_name,
            "match_count": 0,
            "quarters": [],
            "latest_median_psf": 0,
            "earliest_median_psf": 0,
            "psf_change_pct": 0,
            "area_types": [],
        }

    # Group by quarter
    by_quarter: dict[str, list[float]] = defaultdict(list)
    by_quarter_prices: dict[str, list[float]] = defaultdict(list)
    area_types = set()

    for txn in matches:
        date_str = txn.get("contractDate", "") or txn.get("saleDate", "") or ""
        q = _quarter(date_str)

        # PSF
        psf = txn.get("unitPrice", None) or txn.get("psf", None)
        if psf:
            try:
                by_quarter[q].append(float(psf))
            except (ValueError, TypeError):
                pass

        # Total price
        price = txn.get("price", None) or txn.get("transactionPrice", None)
        if price:
            try:
                by_quarter_prices[q].append(float(price))
            except (ValueError, TypeError):
                pass

        # Area type
        at = txn.get("typeOfArea", "") or txn.get("floorArea", "")
        if at and str(at) not in ("", "0"):
            area_types.add(str(at))

    # Build sorted quarter list
    quarters = []
    for q in sorted(by_quarter.keys()):
        psfs = by_quarter[q]
        prices = by_quarter_prices.get(q, [])
        if not psfs:
            continue
        quarters.append({
            "quarter": q,
            "median_psf": round(statistics.median(psfs)),
            "mean_psf": round(statistics.mean(psfs)),
            "min_psf": round(min(psfs)),
            "max_psf": round(max(psfs)),
            "count": len(psfs),
            "median_price": round(statistics.median(prices)) if prices else 0,
        })

    earliest_psf = quarters[0]["median_psf"] if quarters else 0
    latest_psf   = quarters[-1]["median_psf"] if quarters else 0
    change_pct   = ((latest_psf - earliest_psf) / earliest_psf * 100) if earliest_psf else 0

    return {
        "project": project_name,
        "match_count": len(matches),
        "quarters": quarters,
        "latest_median_psf": latest_psf,
        "earliest_median_psf": earliest_psf,
        "psf_change_pct": round(change_pct, 1),
        "area_types": sorted(area_types),
    }


def top_trending_projects(
    transactions: list[dict],
    min_txns: int = 10,
    lookback_quarters: int = 8,
    top_n: int = 10,
) -> list[dict]:
    """
    Find projects with biggest PSF appreciation over the lookback period.
    Returns list sorted by psf_change_pct descending.
    """
    from collections import Counter

    # Count transactions per project
    proj_counts = Counter()
    for txn in transactions:
        name = str(txn.get("project", "") or txn.get("projectName", "")).strip()
        if name:
            proj_counts[name] += 1

    results = []
    for proj, cnt in proj_counts.most_common(200):
        if cnt < min_txns:
            continue
        hist = get_project_history(proj, transactions)
        if len(hist["quarters"]) < 2:
            continue
        hist["project"] = proj
        hist["total_txns"] = cnt
        results.append(hist)

    results.sort(key=lambda x: x["psf_change_pct"], reverse=True)
    return results[:top_n]


def district_psf_trend(
    transactions: list[dict],
    district: str,
    min_txns_per_quarter: int = 3,
) -> list[dict]:
    """PSF trend for a whole district (not per project)."""
    by_quarter: dict[str, list[float]] = defaultdict(list)

    for txn in transactions:
        d = str(txn.get("district", "") or txn.get("districtId", "")).strip().lstrip("0")
        if d != str(district).lstrip("0"):
            continue
        date_str = txn.get("contractDate", "") or txn.get("saleDate", "") or ""
        q = _quarter(date_str)
        psf = txn.get("unitPrice") or txn.get("psf")
        if psf:
            try:
                by_quarter[q].append(float(psf))
            except (ValueError, TypeError):
                pass

    result = []
    for q in sorted(by_quarter.keys()):
        psfs = by_quarter[q]
        if len(psfs) < min_txns_per_quarter:
            continue
        result.append({
            "quarter": q,
            "median_psf": round(statistics.median(psfs)),
            "count": len(psfs),
        })
    return result
