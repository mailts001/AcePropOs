"""
En-Bloc Potential Scanner — Singapore private property.
Scores condos/apartments on collective sale potential based on:
- Age (>20 years = eligible, >30 = prime candidate)
- Plot ratio headroom (current FAR vs URA Master Plan allowable)
- Tenure (freehold/999yr > 99yr for en-bloc)
- Unit count (50–500 units sweet spot for developers)
- Historical en-bloc attempts

Data: derived from URA transaction cache + static knowledge base.
"""

from pathlib import Path
import json
from collections import defaultdict

CACHE_DIR = Path(__file__).parent.parent / "cache" / "ura"

# Known en-bloc sales (sample — expandable)
ENBLOC_HISTORY = [
    {"project": "PEARL BANK APARTMENTS", "district": 2, "year": 2018, "price_m": 728, "units": 288},
    {"project": "NORMANTON PARK", "district": 5, "year": 2017, "price_m": 830, "units": 488},
    {"project": "PACIFIC MANSION", "district": 9, "year": 2018, "price_m": 980, "units": 164},
    {"project": "CASA MEYFORT", "district": 15, "year": 2018, "price_m": 319, "units": 76},
    {"project": "GOLDEN MILE COMPLEX", "district": 7, "year": 2022, "price_m": 700, "units": 718},
    {"project": "DIANA TOWERS", "district": 9, "year": 2022, "price_m": 56, "units": 18},
    {"project": "DUNEARN GARDENS", "district": 10, "year": 2022, "price_m": 86, "units": 28},
    {"project": "CRYSTAL TOWER", "district": 9, "year": 2022, "price_m": 60, "units": 36},
]

# District-level development charge baselines (simplified)
# Higher DC = lower developer appetite
DC_PRESSURE = {
    1: "low", 2: "low", 3: "medium", 4: "low",
    5: "medium", 6: "low", 7: "medium", 8: "medium",
    9: "low", 10: "low", 11: "low", 12: "medium",
    13: "medium", 14: "medium", 15: "low", 16: "medium",
    17: "high", 18: "high", 19: "medium", 20: "medium",
    21: "medium", 22: "high", 23: "high", 24: "high",
    25: "high", 26: "high", 27: "high", 28: "high",
}


def score_enbloc_potential(
    project_name: str,
    district: int,
    completion_year: int,
    tenure: str,
    units: int,
    current_plot_ratio: float = 1.4,
    allowable_plot_ratio: float = 2.8,
    site_area_sqm: float = 5000,
) -> dict:
    """
    Score a development's en-bloc potential (0–100).
    Higher = more attractive to developers for collective sale.
    """
    from datetime import date
    age = date.today().year - completion_year
    score = 0
    factors = []

    # Age score (max 30 pts)
    if age >= 30:
        score += 30
        factors.append(("Age", f"{age} years — prime collective sale candidate", 30))
    elif age >= 20:
        pts = int((age - 20) / 10 * 30)
        score += pts
        factors.append(("Age", f"{age} years — eligible (≥20 years)", pts))
    else:
        factors.append(("Age", f"{age} years — not yet eligible (need 20+)", 0))

    # Plot ratio headroom (max 25 pts)
    headroom_pct = (allowable_plot_ratio - current_plot_ratio) / allowable_plot_ratio * 100
    if headroom_pct >= 50:
        score += 25
        factors.append(("Plot ratio headroom", f"{headroom_pct:.0f}% — significant upside for developer", 25))
    elif headroom_pct >= 25:
        pts = int(headroom_pct / 50 * 25)
        score += pts
        factors.append(("Plot ratio headroom", f"{headroom_pct:.0f}% — moderate upside", pts))
    else:
        factors.append(("Plot ratio headroom", f"{headroom_pct:.0f}% — limited upside", 0))

    # Tenure (max 20 pts)
    tenure_lower = tenure.lower()
    if "freehold" in tenure_lower or "999" in tenure_lower:
        score += 20
        factors.append(("Tenure", "Freehold/999yr — highly attractive for redevelopment", 20))
    elif "99" in tenure_lower:
        remaining_lease = 99 - age
        if remaining_lease > 50:
            score += 10
            factors.append(("Tenure", f"99yr leasehold, ~{remaining_lease}yr remaining — viable", 10))
        else:
            score += 3
            factors.append(("Tenure", f"99yr leasehold, ~{remaining_lease}yr remaining — less attractive", 3))

    # Unit count sweet spot (max 15 pts)
    if 50 <= units <= 400:
        score += 15
        factors.append(("Unit count", f"{units} units — ideal size for collective sale", 15))
    elif units < 50:
        score += 10
        factors.append(("Unit count", f"{units} units — small, easier consensus but lower payout scale", 10))
    else:
        score += 5
        factors.append(("Unit count", f"{units} units — large, harder to get 80% consent", 5))

    # District demand (max 10 pts)
    dc_level = DC_PRESSURE.get(district, "medium")
    if dc_level == "low":
        score += 10
        factors.append(("District demand", f"D{district} — prime, strong developer appetite", 10))
    elif dc_level == "medium":
        score += 5
        factors.append(("District demand", f"D{district} — moderate demand", 5))
    else:
        factors.append(("District demand", f"D{district} — suburban, weaker developer appetite", 0))

    # Historical en-bloc in same district (bonus)
    dist_history = [e for e in ENBLOC_HISTORY if e["district"] == district]
    if dist_history:
        score = min(100, score + 5)
        factors.append(("District track record", f"{len(dist_history)} previous en-bloc(s) in D{district}", 5))

    # Potential payout estimate
    potential_payout_per_unit = None
    if site_area_sqm > 0 and allowable_plot_ratio > 0:
        # Developer's bid ≈ residual land value
        # GFA = site_area × plot_ratio, rough $1,800-2,500 PSF build cost
        gfa_sqft = site_area_sqm * 10.764 * allowable_plot_ratio
        est_gdv = gfa_sqft * 2000  # conservative SGD 2,000 PSF sale
        dev_cost = gfa_sqft * 400   # build cost
        land_bid = (est_gdv - dev_cost) * 0.6  # developer takes 40% margin
        potential_payout_per_unit = round(land_bid / units, -3) if units > 0 else None

    rating = "🔴 Low" if score < 30 else "🟡 Moderate" if score < 55 else "🟠 Good" if score < 75 else "🟢 High"

    return {
        "project": project_name,
        "district": district,
        "age_years": age,
        "tenure": tenure,
        "units": units,
        "score": score,
        "rating": rating,
        "factors": factors,
        "potential_payout_per_unit_sgd": potential_payout_per_unit,
        "eligible": age >= 20,
        "note": (
            "Requires 80% of owners (by share value and strata area) to consent. "
            "En-bloc sale typically takes 12–24 months to complete after collective sale agreement."
        ),
    }


def get_district_enbloc_history(district: int) -> list[dict]:
    return [e for e in ENBLOC_HISTORY if e["district"] == district]


def scan_from_ura_cache(min_age: int = 20, min_score: int = 40) -> list[dict]:
    """
    Scan URA transaction cache for projects that may be en-bloc candidates.
    Groups transactions by project and estimates age from earliest transaction date.
    """
    results = []
    cache_files = list(CACHE_DIR.glob("transactions_batch*.json"))
    if not cache_files:
        return []

    projects: dict[str, dict] = {}
    for cf in cache_files:
        try:
            data = json.loads(cf.read_text())
            txns = data.get("transactions", [])
        except Exception:
            continue
        for t in txns:
            pname = t.get("project", "")
            if not pname:
                continue
            if pname not in projects:
                projects[pname] = {
                    "project": pname,
                    "district": t.get("district", 0),
                    "tenure": t.get("tenure", ""),
                    "transactions": [],
                }
            projects[pname]["transactions"].append(t)

    for pname, proj in projects.items():
        txns = proj["transactions"]
        unit_count = len(set(
            f"{t.get('area_sqm', 0):.0f}"
            for t in txns
        ))  # rough proxy — distinct area sizes
        unit_count = max(10, unit_count * 3)  # scale up (each area = multiple units)

        # Estimate completion year from earliest transaction date
        dates = [t.get("contract_date", "") for t in txns if t.get("contract_date")]
        if not dates:
            continue
        earliest = min(dates)
        try:
            year = int(earliest[:4]) - 3  # units transact ~3yr after TOP
        except Exception:
            continue

        score_result = score_enbloc_potential(
            project_name=pname,
            district=proj["district"],
            completion_year=year,
            tenure=proj["tenure"],
            units=unit_count,
        )
        if score_result["eligible"] and score_result["score"] >= min_score:
            results.append(score_result)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:50]
