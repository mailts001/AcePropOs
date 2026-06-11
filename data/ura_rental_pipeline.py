"""
URA Private Residential Rental Pipeline
Services: PMI_Resi_Rental (individual transactions), PMI_Resi_Rental_Median (district medians)
Requires Singapore IP (blocked by captcha from non-SG IPs).
"""

import os
import json
import time
import requests
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import statistics

from data.ura_pipeline import get_daily_token, URA_BASE, _URA_HEADERS

CACHE_DIR = Path(__file__).parent.parent / "cache" / "ura"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

RENTAL_CACHE = CACHE_DIR / "rentals.json"
RENTAL_MEDIAN_CACHE = CACHE_DIR / "rental_medians.json"


def fetch_rental_transactions(batch: int = 1, force: bool = False) -> list[dict]:
    """
    Individual private rental transactions.
    URA returns ~3 months per batch (batches 1-4 = full year).
    """
    cache_path = CACHE_DIR / f"rentals_batch{batch}.json"
    if not force and cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < 86400:  # 24h cache
            return json.loads(cache_path.read_text())

    token = get_daily_token()
    resp = requests.get(
        f"{URA_BASE}/invokeUraDS/v1",
        params={"service": "PMI_Resi_Rental", "batch": batch},
        headers={**_URA_HEADERS, "AccessKey": os.environ.get("URA_ACCESS_KEY", ""), "Token": token},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("Status") != "Success":
        raise RuntimeError(f"URA rental fetch error: {data}")

    records = []
    for project in data.get("Result", []):
        proj_name = project.get("project", "")
        district = project.get("district", "")
        for txn in project.get("rental", []):
            area_sqft = None
            area_str = txn.get("areaSqft", "")
            if " to " in str(area_str):
                lo, hi = area_str.split(" to ")
                try:
                    area_sqft = (float(lo) + float(hi)) / 2
                except Exception:
                    pass
            elif area_str:
                try:
                    area_sqft = float(area_str)
                except Exception:
                    pass

            records.append({
                "project": proj_name,
                "district": district,
                "area_sqft": area_sqft,
                "monthly_rent": _safe_float(txn.get("rent")),
                "lease_date": txn.get("leaseDate", ""),
                "property_type": txn.get("propertyType", ""),
                "no_of_bedrooms": txn.get("noOfBedRoom", ""),
            })

    cache_path.write_text(json.dumps(records))
    return records


def fetch_rental_medians(force: bool = False) -> list[dict]:
    """
    URA quarterly median rental by district + property type + bedroom count.
    Very useful for yield benchmarking without needing individual transactions.
    """
    if not force and RENTAL_MEDIAN_CACHE.exists():
        age = time.time() - RENTAL_MEDIAN_CACHE.stat().st_mtime
        if age < 86400 * 7:  # 1-week cache (quarterly data)
            return json.loads(RENTAL_MEDIAN_CACHE.read_text())

    token = get_daily_token()
    resp = requests.get(
        f"{URA_BASE}/invokeUraDS/v1",
        params={"service": "PMI_Resi_Rental_Median"},
        headers={**_URA_HEADERS, "AccessKey": os.environ.get("URA_ACCESS_KEY", ""), "Token": token},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("Status") != "Success":
        raise RuntimeError(f"URA rental median error: {data}")

    records = []
    for item in data.get("Result", []):
        records.append({
            "district": item.get("district", ""),
            "property_type": item.get("propertyType", ""),
            "bedrooms": item.get("noOfBedRoom", ""),
            "quarter": item.get("refPeriod", ""),
            "median_rent": _safe_float(item.get("median")),
            "p25_rent": _safe_float(item.get("psf25th")),
            "p75_rent": _safe_float(item.get("psf75th")),
        })

    RENTAL_MEDIAN_CACHE.write_text(json.dumps(records))
    return records


def get_district_rental_stats(district: int | str) -> dict:
    """
    Summarise rental market for a district: median by bedroom count,
    estimated gross yield range (requires private transaction prices).
    """
    medians = fetch_rental_medians()
    district = str(district).zfill(2)
    district_data = [m for m in medians if str(m.get("district", "")).zfill(2) == district]

    if not district_data:
        return {"district": district, "status": "no_data"}

    # Latest quarter
    latest_q = max(d["quarter"] for d in district_data if d.get("quarter"))
    latest = [d for d in district_data if d.get("quarter") == latest_q]

    by_bedrooms = {}
    for row in latest:
        bed = row.get("bedrooms", "unknown")
        by_bedrooms[bed] = {
            "median_rent_sgd": row["median_rent"],
            "p25_rent_sgd": row["p25_rent"],
            "p75_rent_sgd": row["p75_rent"],
            "property_type": row["property_type"],
        }

    return {
        "district": district,
        "latest_quarter": latest_q,
        "by_bedrooms": by_bedrooms,
        "status": "ok",
    }


def get_all_rental_transactions() -> list[dict]:
    """Load all batches, merge and return. Used for deal analysis."""
    all_records = []
    for batch in range(1, 5):
        try:
            all_records.extend(fetch_rental_transactions(batch))
        except Exception:
            break
    # Deduplicate by project+date+rent
    seen = set()
    unique = []
    for r in all_records:
        key = (r.get("project"), r.get("lease_date"), r.get("monthly_rent"))
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _safe_float(v) -> float | None:
    try:
        return float(v)
    except Exception:
        return None
