"""
HDB Resale + Rental Transaction Pipeline
Source: data.gov.sg (free, no API key needed for basic access)
Datasets:
  - Resale: https://data.gov.sg/collections/189/view
  - Rental: https://data.gov.sg/collections/1886/view
"""

import json
import time
import requests
from pathlib import Path
from datetime import datetime, date

CACHE_DIR = Path(__file__).parent.parent / "cache" / "hdb"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DATAGOV_API = "https://data.gov.sg/api/action/datastore_search"

# Resource IDs from data.gov.sg (verify these at data.gov.sg if they change)
# Current resale dataset — confirmed up to June 2026
HDB_RESALE_RESOURCE_ID = "d_8b84c4ee58e3cfc0ece0d773c8ca6abc"
# Legacy dataset (2012-2017 era, kept as fallback)
HDB_RESALE_RESOURCE_ID_LEGACY = "f1765b54-a209-4718-8d38-a39237f502b3"
HDB_RENTAL_RESOURCE_ID = None  # Not available via API


def fetch_hdb_resale(limit: int = 10000, offset: int = 0) -> list[dict]:
    """Fetch HDB resale transactions from data.gov.sg."""
    cache_path = CACHE_DIR / f"resale_{offset}_{limit}.json"

    if cache_path.exists():
        data = json.loads(cache_path.read_text())
        if time.time() - data["fetched_at"] < 604800:  # 7-day cache
            return data["records"]

    resp = requests.get(
        DATAGOV_API,
        params={
            "resource_id": HDB_RESALE_RESOURCE_ID,
            "limit": limit,
            "offset": offset,
            "sort": "month desc",  # Most recent first
        },
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()

    if raw.get("success") is not True:
        raise RuntimeError(f"data.gov.sg HDB resale error: {raw}")

    records = _normalise_resale(raw["result"]["records"])
    cache_path.write_text(json.dumps({"fetched_at": time.time(), "records": records}))
    return records


def _normalise_resale(records: list) -> list[dict]:
    out = []
    for r in records:
        try:
            price = float(r.get("resale_price", 0))
            floor_area = float(r.get("floor_area_sqm", 0))
            psf = round(price / (floor_area * 10.7639), 0) if floor_area > 0 else 0
            out.append({
                "town": r.get("town", ""),
                "flat_type": r.get("flat_type", ""),
                "block": r.get("block", ""),
                "street_name": r.get("street_name", ""),
                "storey_range": r.get("storey_range", ""),
                "floor_area_sqm": floor_area,
                "floor_area_sqft": round(floor_area * 10.7639, 0),
                "flat_model": r.get("flat_model", ""),
                "lease_commence_date": r.get("lease_commence_date", ""),
                "remaining_lease": r.get("remaining_lease", r.get("remaining_lease_months", "")),
                "resale_price": price,
                "psf_sgd": psf,
                "month": r.get("month", ""),
            })
        except (ValueError, TypeError):
            continue
    return out


def fetch_hdb_rental(limit: int = 5000) -> list[dict]:
    """Fetch HDB approved rental transactions."""
    cache_path = CACHE_DIR / "rental_latest.json"

    if cache_path.exists():
        data = json.loads(cache_path.read_text())
        if time.time() - data["fetched_at"] < 604800:
            return data["records"]

    resp = requests.get(
        DATAGOV_API,
        params={"resource_id": HDB_RENTAL_RESOURCE_ID, "limit": limit},
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()

    records = raw["result"]["records"] if raw.get("success") else []
    cache_path.write_text(json.dumps({"fetched_at": time.time(), "records": records}))
    return records


def get_town_stats(town: str, flat_type: str = "") -> dict:
    """
    Return median price, PSF, and count for an HDB town.
    Used by ValuationAgent for HDB benchmarking.
    """
    cache_path = CACHE_DIR / "resale_0_10000.json"
    if not cache_path.exists():
        return {"town": town, "count": 0, "error": "No data cached. Run sync first."}

    data = json.loads(cache_path.read_text())
    records = data["records"]

    filtered = [
        r for r in records
        if r["town"].lower() == town.lower()
        and (not flat_type or flat_type.lower() in r["flat_type"].lower())
        and r["psf_sgd"] > 0
    ]

    if not filtered:
        return {"town": town, "count": 0}

    prices = sorted(r["resale_price"] for r in filtered)
    psfs = sorted(r["psf_sgd"] for r in filtered)
    n = len(prices)

    return {
        "town": town,
        "flat_type": flat_type or "all",
        "count": n,
        "median_price": prices[n // 2],
        "median_psf": psfs[n // 2],
        "p25_price": prices[n // 4],
        "p75_price": prices[3 * n // 4],
        "min_price": prices[0],
        "max_price": prices[-1],
    }


def find_below_market_hdb(threshold_pct: float = 8.0, limit: int = 20,
                          town: str | None = None, flat_type: str | None = None,
                          max_price: float | None = None) -> list[dict]:
    """
    Find recent HDB transactions that were priced significantly below town median.
    Used by DealHunterAgent for HDB opportunity detection.
    """
    cache_path = CACHE_DIR / "resale_0_10000.json"
    if not cache_path.exists():
        return []

    data = json.loads(cache_path.read_text())
    records = data["records"]

    # Build town+flat_type medians
    medians: dict[str, float] = {}
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    for r in records:
        key = f"{r['town']}|{r['flat_type']}"
        groups[key].append(r["psf_sgd"])

    for key, psfs in groups.items():
        psfs_sorted = sorted(psfs)
        medians[key] = psfs_sorted[len(psfs_sorted) // 2]

    # Find recent records below threshold
    # Sort by month descending, take recent 3 months
    records_sorted = sorted(records, key=lambda x: x.get("month", ""), reverse=True)
    recent = records_sorted[:3000]

    opportunities = []
    for r in recent:
        if town and town.upper() not in r.get("town", "").upper():
            continue
        if flat_type and flat_type.upper() not in r.get("flat_type", "").upper():
            continue
        if max_price and r.get("resale_price", 0) > max_price:
            continue
        key = f"{r['town']}|{r['flat_type']}"
        median = medians.get(key, 0)
        if median <= 0 or r["psf_sgd"] <= 0:
            continue
        discount_pct = (median - r["psf_sgd"]) / median * 100
        if discount_pct >= threshold_pct:
            opportunities.append({
                **r,
                "median_psf": median,
                "discount_pct": round(discount_pct, 1),
                "potential_gain_sgd": round(
                    (median - r["psf_sgd"]) * r["floor_area_sqft"], 0
                ),
            })

    opportunities.sort(key=lambda x: x["discount_pct"], reverse=True)
    return opportunities[:limit]


def lookup_by_address(block: str, street: str, flat_type: str = "") -> dict:
    """
    Look up transaction history for a specific HDB block + street address.
    Returns all matching transactions + statistical summary.
    Example: lookup_by_address("123", "TAMPINES ST 11", "4 ROOM")
    """
    cache_path = CACHE_DIR / "resale_0_10000.json"
    if not cache_path.exists():
        return {"error": "No data cached. Run sync first."}

    records = json.loads(cache_path.read_text())["records"]

    block_clean = block.strip().upper()
    street_clean = street.strip().upper()

    matches = [
        r for r in records
        if r["block"].upper() == block_clean
        and street_clean in r["street_name"].upper()
        and (not flat_type or flat_type.upper() in r["flat_type"].upper())
    ]

    if not matches:
        # Fuzzy: try partial street match
        matches = [
            r for r in records
            if r["block"].upper() == block_clean
            and any(word in r["street_name"].upper() for word in street_clean.split() if len(word) > 2)
        ]

    if not matches:
        return {
            "found": False,
            "block": block,
            "street": street,
            "message": f"No transactions found for Block {block} {street}. "
                       "Try nearby blocks or check the street name spelling.",
        }

    matches.sort(key=lambda x: x.get("month", ""), reverse=True)
    prices = [r["resale_price"] for r in matches]
    psfs = [r["psf_sgd"] for r in matches if r["psf_sgd"] > 0]
    n = len(matches)

    # Get town benchmark for comparison
    town = matches[0]["town"]
    ftype = matches[0]["flat_type"]
    benchmark = get_town_stats(town, ftype)
    median_town_price = benchmark.get("median_price", 0)

    latest = matches[0]
    vs_town = round((latest["resale_price"] - median_town_price) / median_town_price * 100, 1) if median_town_price else None

    return {
        "found": True,
        "block": block,
        "street": street,
        "town": town,
        "flat_type": ftype if not flat_type else flat_type,
        "transaction_count": n,
        "latest_transaction": {
            "price": latest["resale_price"],
            "psf": latest["psf_sgd"],
            "month": latest["month"],
            "storey": latest["storey_range"],
            "area_sqft": latest["floor_area_sqft"],
            "remaining_lease": latest.get("remaining_lease", ""),
        },
        "price_range": {
            "min": min(prices),
            "max": max(prices),
            "median": sorted(prices)[n // 2],
        },
        "avg_psf": round(sum(psfs) / len(psfs), 0) if psfs else 0,
        "vs_town_median_pct": vs_town,
        "town_median_price": median_town_price,
        "all_transactions": matches[:10],
    }


def search_by_street(street_keyword: str, town: str = "", limit: int = 20) -> list[dict]:
    """
    Search transactions by partial street name. Helps users find the right address.
    Example: search_by_street("TAMPINES ST 11") or search_by_street("ANG MO KIO AVE")
    """
    cache_path = CACHE_DIR / "resale_0_10000.json"
    if not cache_path.exists():
        return []

    records = json.loads(cache_path.read_text())["records"]
    keyword = street_keyword.strip().upper()

    matches = [
        r for r in records
        if keyword in r["street_name"].upper()
        and (not town or town.upper() in r["town"].upper())
    ]
    matches.sort(key=lambda x: x.get("month", ""), reverse=True)

    # Deduplicate by block+street+flat_type, keep most recent
    seen = set()
    deduped = []
    for r in matches:
        key = f"{r['block']}|{r['street_name']}|{r['flat_type']}"
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    return deduped[:limit]


def sync_all():
    """Full HDB sync. Run weekly via cron."""
    print(f"[HDB] Starting sync at {datetime.now().isoformat()}")
    resale = fetch_hdb_resale(limit=10000, offset=0)
    print(f"[HDB] Resale: {len(resale)} records")
    # HDB rental not available via data.gov.sg API — skipping
    print("[HDB] Sync complete")


if __name__ == "__main__":
    sync_all()
