"""
MRT proximity calculator — finds nearest MRT stations to a given location.
Uses Haversine distance formula. No external API needed.
"""
import math
from data.mrt_data import MRT_STATIONS, get_line_color

# Average walking speed: 80m/min → 4.8 km/h
WALK_SPEED_MPS = 80  # metres per minute


def haversine(lat1, lon1, lat2, lon2) -> float:
    """Return distance in metres between two WGS84 coordinates."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def nearest_mrt(lat: float, lon: float, top_n: int = 5) -> list[dict]:
    """Return top_n nearest MRT stations with distance and walk time."""
    results = []
    for name, line, mlat, mlon, district in MRT_STATIONS:
        dist = haversine(lat, lon, mlat, mlon)
        walk_min = round(dist / WALK_SPEED_MPS)
        results.append({
            "station": name,
            "line": line,
            "distance_m": round(dist),
            "walk_min": walk_min,
            "walk_label": f"{walk_min} min walk" if walk_min <= 20 else f"{round(dist/1000, 1)} km",
            "color": get_line_color(line),
            "lat": mlat,
            "lon": mlon,
        })
    results.sort(key=lambda x: x["distance_m"])
    return results[:top_n]


# District centroid coordinates (approximate geometric centre)
DISTRICT_CENTROIDS = {
    1:  (1.2830, 103.8500), 2:  (1.2780, 103.8420), 3:  (1.2890, 103.8140),
    4:  (1.2680, 103.8150), 5:  (1.3060, 103.7800), 6:  (1.2940, 103.8490),
    7:  (1.3020, 103.8570), 8:  (1.3100, 103.8560), 9:  (1.3060, 103.8310),
    10: (1.3210, 103.8040), 11: (1.3200, 103.8380), 12: (1.3310, 103.8470),
    13: (1.3290, 103.8830), 14: (1.3170, 103.8910), 15: (1.3050, 103.8950),
    16: (1.3290, 103.9250), 17: (1.3680, 103.9700), 18: (1.3550, 103.9460),
    19: (1.3810, 103.8840), 20: (1.3690, 103.8480), 21: (1.3340, 103.7820),
    22: (1.3410, 103.7110), 23: (1.3640, 103.7590), 24: (1.3980, 103.7040),
    25: (1.4350, 103.7870), 26: (1.4000, 103.8250), 27: (1.4290, 103.8290),
    28: (1.4040, 103.8990),
}

# HDB town → approximate centroid
TOWN_CENTROIDS = {
    "ANG MO KIO":    (1.3700, 103.8490), "BEDOK":          (1.3240, 103.9300),
    "BISHAN":        (1.3510, 103.8490), "BUKIT BATOK":    (1.3490, 103.7490),
    "BUKIT MERAH":   (1.2900, 103.8160), "BUKIT PANJANG":  (1.3790, 103.7760),
    "CENTRAL AREA":  (1.2840, 103.8510), "CHOA CHU KANG":  (1.3850, 103.7440),
    "CLEMENTI":      (1.3150, 103.7650), "GEYLANG":        (1.3180, 103.8870),
    "HOUGANG":       (1.3710, 103.8930), "JURONG EAST":    (1.3330, 103.7420),
    "JURONG WEST":   (1.3480, 103.7050), "KALLANG/WHAMPOA":(1.3110, 103.8620),
    "MARINE PARADE": (1.3020, 103.9040), "PASIR RIS":      (1.3730, 103.9490),
    "PUNGGOL":       (1.4060, 103.9020), "QUEENSTOWN":     (1.2950, 103.8060),
    "SEMBAWANG":     (1.4490, 103.8200), "SENGKANG":       (1.3920, 103.8950),
    "SERANGOON":     (1.3490, 103.8730), "TAMPINES":       (1.3530, 103.9450),
    "TOA PAYOH":     (1.3330, 103.8470), "WOODLANDS":      (1.4370, 103.7860),
    "YISHUN":        (1.4290, 103.8350),
}


def mrt_for_district(district: int, top_n: int = 5) -> list[dict]:
    coords = DISTRICT_CENTROIDS.get(district)
    if not coords:
        return []
    return nearest_mrt(coords[0], coords[1], top_n)


def mrt_for_town(town: str, top_n: int = 5) -> list[dict]:
    coords = TOWN_CENTROIDS.get(town.upper())
    if not coords:
        return []
    return nearest_mrt(coords[0], coords[1], top_n)


def mrt_score(nearest: list[dict]) -> int:
    """
    Connectivity score 0-100 based on nearest MRT distances.
    ≤400m = excellent, ≤800m = good, ≤1200m = fair.
    """
    if not nearest:
        return 0
    closest = nearest[0]["distance_m"]
    if closest <= 400:
        base = 90
    elif closest <= 800:
        base = 70
    elif closest <= 1200:
        base = 50
    elif closest <= 1600:
        base = 30
    else:
        base = 10
    # Bonus if 2+ stations within 1km
    within_1km = sum(1 for s in nearest if s["distance_m"] <= 1000)
    bonus = min(10, within_1km * 3)
    return min(100, base + bonus)
