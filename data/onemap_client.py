"""
OneMap Singapore API client.
Token-required APIs: Search, Routing, Themes, Planning Area, Population Query.
Token-free APIs: Basemaps, Static Map (no token needed).
Token expires every 3 days — stored in .env as ONEMAP_TOKEN.
Renew at: https://www.onemap.gov.sg/apidocs/
"""

import os
import json
import requests
from pathlib import Path

ONEMAP_BASE = "https://www.onemap.gov.sg/api"
CACHE_DIR = Path(__file__).parent.parent / "cache" / "onemap"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _get_token() -> str:
    token = os.environ.get("ONEMAP_TOKEN", "")
    if not token:
        raise EnvironmentError(
            "ONEMAP_TOKEN not set. Renew at https://www.onemap.gov.sg/apidocs/ "
            "and update .env. Token expires every 3 days."
        )
    return token


def search_address(search_val: str) -> list[dict]:
    """
    Search for an address or postal code. Returns list of matching results.
    Useful for geocoding user-entered property addresses.
    Token required.
    """
    cache_path = CACHE_DIR / f"search_{search_val.replace(' ', '_')[:30]}.json"
    if cache_path.exists():
        import time
        data = json.loads(cache_path.read_text())
        if time.time() - data.get("ts", 0) < 86400:
            return data["results"]

    resp = requests.get(
        f"{ONEMAP_BASE}/common/elastic/search",
        params={
            "searchVal": search_val,
            "returnGeom": "Y",
            "getAddrDetails": "Y",
            "pageNum": 1,
        },
        headers={"Authorization": _get_token()},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])

    import time
    cache_path.write_text(json.dumps({"ts": time.time(), "results": results}))
    return results


def get_mrt_distance(lat: float, lng: float) -> dict:
    """
    Find nearest MRT station to coordinates using OneMap routing/themes.
    Returns nearest MRT name and walking distance.
    Used by ValuationAgent to score location quality.
    """
    # MRT station lookup via Themes API
    try:
        resp = requests.get(
            f"{ONEMAP_BASE}/public/themesvc/retrieveTheme",
            params={"queryName": "mrt_lrt_station"},
            headers={"Authorization": _get_token()},
            timeout=10,
        )
        if resp.status_code != 200:
            return {"nearest_mrt": "Unknown", "distance_m": None}

        stations = resp.json().get("SrchResults", [])
        if not stations:
            return {"nearest_mrt": "Unknown", "distance_m": None}

        # Find nearest by Haversine distance
        import math
        def haversine(lat1, lon1, lat2, lon2):
            R = 6371000
            phi1, phi2 = math.radians(lat1), math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlambda = math.radians(lon2 - lon1)
            a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
            return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

        nearest = None
        min_dist = float("inf")
        for s in stations:
            try:
                s_lat = float(s.get("LATITUDE", 0))
                s_lng = float(s.get("LONGITUDE", 0))
                d = haversine(lat, lng, s_lat, s_lng)
                if d < min_dist:
                    min_dist = d
                    nearest = s.get("NAME", "Unknown")
            except (ValueError, TypeError):
                continue

        return {
            "nearest_mrt": nearest or "Unknown",
            "distance_m": round(min_dist, 0) if nearest else None,
            "walking_minutes": round(min_dist / 80, 0) if nearest else None,  # ~80m/min walking
        }
    except Exception as e:
        return {"nearest_mrt": "Unknown", "distance_m": None, "error": str(e)}


def get_planning_area(lat: float, lng: float) -> str:
    """Return the URA planning area for given coordinates. Token required."""
    try:
        resp = requests.get(
            f"{ONEMAP_BASE}/public/popapi/getPlanningarea",
            params={"lat": lat, "lng": lng},
            headers={"Authorization": _get_token()},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data[0].get("pln_area_n", "Unknown") if data else "Unknown"
    except Exception:
        return "Unknown"


def xy_to_latlong(x: float, y: float) -> tuple[float, float]:
    """Convert SVY21 (Singapore) coordinates to WGS84 lat/lng. Token required."""
    try:
        resp = requests.get(
            f"{ONEMAP_BASE}/common/convert/3414to4326",
            params={"X": x, "Y": y},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return float(data["latitude"]), float(data["longitude"])
    except Exception:
        return 0.0, 0.0
