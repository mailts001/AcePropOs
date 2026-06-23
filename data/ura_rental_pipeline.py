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
    IMPORTANT: Only makes live API call when force=True (called by sync_ura.py).
    In render paths, always reads from cache only — never blocks the UI thread.
    """
    # force=True always bypasses cache (used by sync_ura.py to refresh)
    if not force and RENTAL_MEDIAN_CACHE.exists():
        age = time.time() - RENTAL_MEDIAN_CACHE.stat().st_mtime
        if age < 86400 * 7:  # 1-week cache (quarterly data)
            return json.loads(RENTAL_MEDIAN_CACHE.read_text())

    # No valid cache — only fetch live if explicitly forced (sync script)
    if not force:
        return []   # caller handles empty gracefully; don't block render thread

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

    # URA structure: Result[{project, street, rentalMedian:[{district, refPeriod, median(PSF), psf25, psf75}]}]
    # median/psf25/psf75 are SGD per sqft per month
    records = []
    for item in data.get("Result", []):
        project = item.get("project", "")
        street  = item.get("street", "")
        for rm in item.get("rentalMedian", []):
            records.append({
                "project":    project,
                "street":     street,
                "district":   str(rm.get("district", "")).strip(),
                "quarter":    rm.get("refPeriod", ""),
                "median_psf": _safe_float(rm.get("median")),   # SGD/sqft/month
                "psf25":      _safe_float(rm.get("psf25")),
                "psf75":      _safe_float(rm.get("psf75")),
            })

    RENTAL_MEDIAN_CACHE.write_text(json.dumps(records))
    return records


def get_district_rental_stats(district: int | str, area_sqft: float = 1000) -> dict:
    """
    Summarise rental PSF for a district from cache only.
    Returns median/P25/P75 rental PSF for latest quarter, plus estimated monthly rent.
    area_sqft: used to compute estimated monthly rent (default 1000 sqft).
    Never makes live API call — cache populated by sync_ura.py (daily cron).
    """
    try:
        records = fetch_rental_medians(force=False)
    except Exception:
        records = []

    if not records:
        return {"district": district, "status": "no_data"}

    # Normalise district — URA stores as "15" (no D prefix in rentalMedian)
    target = str(district).replace("D", "").strip()
    dist_records = [r for r in records if str(r.get("district", "")).strip() == target]

    if not dist_records:
        return {"district": district, "status": "no_data"}

    # Latest quarter
    latest_q = max((r["quarter"] for r in dist_records if r.get("quarter")), default="")
    latest   = [r for r in dist_records if r.get("quarter") == latest_q]

    psfs    = [r["median_psf"] for r in latest if r.get("median_psf")]
    p25s    = [r["psf25"]      for r in latest if r.get("psf25")]
    p75s    = [r["psf75"]      for r in latest if r.get("psf75")]

    if not psfs:
        return {"district": district, "status": "no_data"}

    import statistics
    med_psf = round(statistics.median(psfs), 2)
    p25_psf = round(statistics.median(p25s), 2) if p25s else med_psf * 0.85
    p75_psf = round(statistics.median(p75s), 2) if p75s else med_psf * 1.15

    # Monthly rent = PSF × area
    med_rent = round(med_psf * area_sqft / 100) * 100   # round to nearest $100
    p25_rent = round(p25_psf * area_sqft / 100) * 100
    p75_rent = round(p75_psf * area_sqft / 100) * 100

    # Per-project breakdown sorted by median PSF descending
    project_rows = sorted(
        [{"project": r.get("project",""), "street": r.get("street",""),
          "median_psf": r.get("median_psf") or 0,
          "psf25": r.get("psf25") or 0, "psf75": r.get("psf75") or 0,
          "med_rent": round((r.get("median_psf") or 0) * area_sqft / 100) * 100,
         } for r in latest if r.get("project") and r.get("median_psf")],
        key=lambda x: x["median_psf"], reverse=True
    )

    return {
        "district":       district,
        "latest_quarter": latest_q,
        "median_psf":     med_psf,
        "p25_psf":        p25_psf,
        "p75_psf":        p75_psf,
        "med_rent_sgd":   med_rent,
        "p25_rent_sgd":   p25_rent,
        "p75_rent_sgd":   p75_rent,
        "area_sqft":      area_sqft,
        "project_count":  len(latest),
        "project_rows":   project_rows,        # per-project table
        "sample_projects": [r["project"] for r in project_rows[:5]],
        "status":         "ok",
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
