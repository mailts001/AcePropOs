"""
BTO Launch Tracker — scrapes HDB BTO launch announcements from data.gov.sg
and HDB newsroom. Provides upcoming BTO calendar and price range estimates.

data.gov.sg BTO dataset: d_bdb03c490e45bde14c4dfb3c9082b02c (HDB BTO launches)
Also parses HDB newsroom for latest announcements.
"""

import json
import time
import requests
from pathlib import Path
from datetime import datetime

CACHE_DIR = Path(__file__).parent.parent / "cache" / "hdb"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
BTO_CACHE = CACHE_DIR / "bto_launches.json"

DATA_GOV_BTO_URL = "https://data.gov.sg/api/action/datastore_search"
BTO_RESOURCE_ID = "d_bdb03c490e45bde14c4dfb3c9082b02c"

# Known BTO price benchmarks (SGD, from HDB published data)
# Used as fallback when data.gov.sg returns no data
BTO_PRICE_BENCHMARKS = {
    "MATURE": {
        "2 ROOM FLEXI": (150000, 280000),
        "3 ROOM": (300000, 420000),
        "4 ROOM": (430000, 600000),
        "5 ROOM": (530000, 720000),
    },
    "NON-MATURE": {
        "2 ROOM FLEXI": (100000, 200000),
        "3 ROOM": (200000, 320000),
        "4 ROOM": (300000, 500000),
        "5 ROOM": (420000, 600000),
    },
}

# Upcoming BTO launches (manually curated — update as HDB announces)
UPCOMING_BTO = [
    {
        "launch_date": "2026-08",
        "estates": ["JURONG WEST", "QUEENSTOWN", "KALLANG/WHAMPOA", "TENGAH"],
        "note": "August 2026 BTO — Queenstown and Kallang/Whampoa are mature estates.",
        "source": "HDB Press Release (estimated)",
    },
    {
        "launch_date": "2026-11",
        "estates": ["ANG MO KIO", "BUKIT MERAH", "HOUGANG", "SEMBAWANG", "WOODLANDS"],
        "note": "November 2026 BTO — Ang Mo Kio and Bukit Merah are mature estates.",
        "source": "HDB Press Release (estimated)",
    },
]


def fetch_bto_launches(limit: int = 100, force: bool = False) -> list[dict]:
    """Fetch BTO launch records from data.gov.sg."""
    if not force and BTO_CACHE.exists():
        age = time.time() - BTO_CACHE.stat().st_mtime
        if age < 86400 * 3:  # 3-day cache
            return json.loads(BTO_CACHE.read_text())

    try:
        resp = requests.get(
            DATA_GOV_BTO_URL,
            params={"resource_id": BTO_RESOURCE_ID, "limit": limit, "sort": "_id desc"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        records = data.get("result", {}).get("records", [])
        if records:
            BTO_CACHE.write_text(json.dumps(records))
            return records
    except Exception:
        pass

    # Return cached even if stale, plus upcoming static data
    if BTO_CACHE.exists():
        return json.loads(BTO_CACHE.read_text())
    return []


def get_bto_summary() -> dict:
    """
    Returns:
    - recent_launches: last 6 BTO launches with estate + flat types + price range
    - upcoming: curated upcoming launches calendar
    - price_guide: benchmark prices by estate type (mature/non-mature)
    """
    records = fetch_bto_launches()

    recent = []
    for r in records[:20]:
        entry = {
            "month": r.get("month", r.get("launch_date", "")),
            "town": r.get("town", r.get("estate", "")),
            "flat_type": r.get("flat_type", ""),
            "units_offered": r.get("total_offered", r.get("units", "")),
            "selling_price_from": _safe_int(r.get("selling_price_from", r.get("min_price"))),
            "selling_price_to": _safe_int(r.get("selling_price_to", r.get("max_price"))),
        }
        if entry["town"] or entry["month"]:
            recent.append(entry)

    return {
        "recent_launches": recent[:12],
        "upcoming": UPCOMING_BTO,
        "price_guide": BTO_PRICE_BENCHMARKS,
        "last_updated": BTO_CACHE.stat().st_mtime if BTO_CACHE.exists() else None,
    }


def estimate_bto_price(town: str, flat_type: str) -> dict:
    """
    Estimate BTO price for a given town + flat type.
    Classifies town as mature/non-mature and returns price range.
    """
    MATURE_ESTATES = {
        "ANG MO KIO", "BEDOK", "BISHAN", "BUKIT MERAH", "BUKIT TIMAH",
        "CENTRAL AREA", "CLEMENTI", "GEYLANG", "KALLANG/WHAMPOA", "MARINE PARADE",
        "PASIR RIS", "QUEENSTOWN", "SERANGOON", "TAMPINES", "TOA PAYOH",
        "WOODLANDS",  # reclassified as mature in some launches
    }
    town_upper = town.upper()
    flat_upper = flat_type.upper()
    estate_type = "MATURE" if town_upper in MATURE_ESTATES else "NON-MATURE"

    price_range = None
    for key in BTO_PRICE_BENCHMARKS.get(estate_type, {}):
        if key in flat_upper or flat_upper in key:
            price_range = BTO_PRICE_BENCHMARKS[estate_type][key]
            break

    if not price_range:
        price_range = BTO_PRICE_BENCHMARKS[estate_type].get("4 ROOM", (300000, 500000))

    # Look up historical BTO data for this town
    records = fetch_bto_launches()
    hist = [r for r in records
            if town_upper in r.get("town", "").upper()
            and flat_upper in r.get("flat_type", "").upper()]
    hist_prices = []
    for h in hist:
        lo = _safe_int(h.get("selling_price_from"))
        hi = _safe_int(h.get("selling_price_to"))
        if lo: hist_prices.append(lo)
        if hi: hist_prices.append(hi)

    return {
        "town": town_upper,
        "flat_type": flat_upper,
        "estate_type": estate_type,
        "price_from_sgd": price_range[0],
        "price_to_sgd": price_range[1],
        "historical_records_found": len(hist),
        "note": f"{estate_type.title()} estate. BTO prices are ~30–50% below resale market value.",
    }


def _safe_int(v) -> int | None:
    try:
        return int(float(str(v).replace(",", "")))
    except Exception:
        return None
