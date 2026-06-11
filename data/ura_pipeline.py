"""
URA Private Residential Transaction Pipeline
API docs: https://www.ura.gov.sg/maps/api/
Free registration required for access key.
Data: private condo/apartment transactions with price, area, district.
"""

import os
import json
import time
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional

CACHE_DIR = Path(__file__).parent.parent / "cache" / "ura"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# URA migrated their API in 2024. Try both bases — eservice is the new home.
# URA API v1 — confirmed working endpoint (eservice.ura.gov.sg/uraDataService/*/v1)
URA_BASE = "https://eservice.ura.gov.sg/uraDataService"
# URA requires a daily token fetched from the access key
_token_cache_path = CACHE_DIR / "daily_token.json"

# URA's WAF (L7 gateway) blocks requests without browser-like headers.
# These headers bypass the bot-protection challenge page.
_URA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-SG,en;q=0.9",
    "Referer": "https://www.ura.gov.sg/maps/",
    "Origin": "https://www.ura.gov.sg",
    "Connection": "keep-alive",
}


def get_daily_token() -> str:
    """Fetch or return cached URA daily auth token (valid 24h)."""
    if _token_cache_path.exists():
        data = json.loads(_token_cache_path.read_text())
        if time.time() - data["ts"] < 82800:  # 23h to be safe
            return data["token"]

    access_key = os.environ.get("URA_ACCESS_KEY", "")
    if not access_key:
        raise EnvironmentError("URA_ACCESS_KEY not set. Register at https://www.ura.gov.sg/maps/api/reg.html")

    resp = requests.get(
        f"{URA_BASE}/insertNewToken/v1",
        headers={**_URA_HEADERS, "AccessKey": access_key},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("Status") != "Success":
        raise RuntimeError(f"URA token error: {data}")

    token = data["Result"]
    _token_cache_path.write_text(json.dumps({"token": token, "ts": time.time()}))
    return token


def fetch_private_transactions(batch: int = 1) -> list[dict]:
    """
    Fetch private residential transactions. URA returns data in 4 quarterly batches.
    batch=1 is most recent. Call batches 1-4 for full year.
    Returns list of normalised transaction dicts.
    """
    cache_path = CACHE_DIR / f"transactions_batch{batch}.json"

    # Use cached data if less than 24h old
    if cache_path.exists():
        data = json.loads(cache_path.read_text())
        if time.time() - data["fetched_at"] < 86400:
            return data["transactions"]

    token = get_daily_token()
    access_key = os.environ["URA_ACCESS_KEY"]

    resp = requests.get(
        f"{URA_BASE}/invokeUraDS/v1",
        params={"service": "PMI_Resi_Transaction", "batch": str(batch)},
        headers={**_URA_HEADERS, "AccessKey": access_key, "Token": token},
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()

    if raw.get("Status") != "Success":
        raise RuntimeError(f"URA transaction fetch failed: {raw}")

    transactions = _normalise_transactions(raw.get("Result", []))
    cache_path.write_text(json.dumps({"fetched_at": time.time(), "transactions": transactions}))
    print(f"URA batch {batch}: {len(transactions)} transactions fetched and cached")
    return transactions


def _normalise_transactions(raw_results: list) -> list[dict]:
    """Flatten URA's nested structure into flat transaction records."""
    out = []
    for project in raw_results:
        project_name = project.get("project", "")
        street = project.get("street", "")
        x_coord = project.get("x", "")
        y_coord = project.get("y", "")

        for txn in project.get("transaction", []):
            try:
                area_sqm = float(txn.get("area", 0))
                price = float(txn.get("price", 0))
                psf = round(price / (area_sqm * 10.7639), 0) if area_sqm > 0 else 0

                out.append({
                    "project": project_name,
                    "street": street,
                    "district": _extract_district(txn.get("districtId", "")),
                    "area_sqm": area_sqm,
                    "area_sqft": round(area_sqm * 10.7639, 0),
                    "price_sgd": price,
                    "psf_sgd": psf,
                    "property_type": txn.get("propertyType", ""),
                    "tenure": txn.get("tenure", ""),
                    "floors": txn.get("noOfUnits", ""),
                    "floor_range": txn.get("floorRange", ""),
                    "type_of_sale": txn.get("typeOfSale", ""),
                    "contract_date": txn.get("contractDate", ""),
                    "x_coord": x_coord,
                    "y_coord": y_coord,
                })
            except (ValueError, TypeError):
                continue
    return out


def _extract_district(district_id: str) -> int:
    try:
        return int(str(district_id).replace("D", "").strip())
    except (ValueError, TypeError):
        return 0


def get_district_stats(district: int, property_type: str = "") -> dict:
    """
    Return median PSF, median price, transaction count for a district.
    Aggregates from all cached batches.
    Used by ValuationAgent as the baseline.
    """
    all_txns = []
    for batch in range(1, 5):
        cache_path = CACHE_DIR / f"transactions_batch{batch}.json"
        if cache_path.exists():
            data = json.loads(cache_path.read_text())
            all_txns.extend(data["transactions"])

    filtered = [
        t for t in all_txns
        if t["district"] == district
        and (not property_type or property_type.lower() in t["property_type"].lower())
        and t["psf_sgd"] > 0
    ]

    if not filtered:
        return {"district": district, "count": 0}

    psfs = sorted(t["psf_sgd"] for t in filtered)
    prices = sorted(t["price_sgd"] for t in filtered)
    n = len(psfs)

    return {
        "district": district,
        "count": n,
        "median_psf": psfs[n // 2],
        "p25_psf": psfs[n // 4],
        "p75_psf": psfs[3 * n // 4],
        "median_price": prices[n // 2],
        "min_price": prices[0],
        "max_price": prices[-1],
        "avg_psf": round(sum(psfs) / n, 0),
    }


def search_transactions(
    district: Optional[int] = None,
    project: Optional[str] = None,
    min_psf: Optional[float] = None,
    max_psf: Optional[float] = None,
    limit: int = 50,
) -> list[dict]:
    """Search cached transactions with filters. Used by DealHunterAgent."""
    all_txns = []
    for batch in range(1, 5):
        cache_path = CACHE_DIR / f"transactions_batch{batch}.json"
        if cache_path.exists():
            data = json.loads(cache_path.read_text())
            all_txns.extend(data["transactions"])

    results = all_txns
    if district:
        results = [t for t in results if t["district"] == district]
    if project:
        results = [t for t in results if project.lower() in t["project"].lower()]
    if min_psf:
        results = [t for t in results if t["psf_sgd"] >= min_psf]
    if max_psf:
        results = [t for t in results if t["psf_sgd"] <= max_psf]

    # Sort by most recent contract date
    results.sort(key=lambda x: x.get("contract_date", ""), reverse=True)
    return results[:limit]


def sync_all_batches():
    """Sync all 4 quarterly batches from URA. Run daily via cron."""
    print(f"[URA] Starting full sync at {datetime.now().isoformat()}")
    total = 0
    for batch in range(1, 5):
        try:
            txns = fetch_private_transactions(batch)
            total += len(txns)
            time.sleep(1)  # Be polite to URA API
        except Exception as e:
            print(f"[URA] Batch {batch} failed: {e}")
    print(f"[URA] Sync complete. Total transactions: {total}")
    return total


# Allow running as script
if __name__ == "__main__":
    sync_all_batches()
