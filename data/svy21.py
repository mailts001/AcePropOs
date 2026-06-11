"""
SVY21 (EPSG:3414) ↔ WGS84 coordinate converter for Singapore.
URA API returns x/y in SVY21. We need WGS84 (lat/lon) for folium maps.
Reference: https://www.sla.gov.sg/sirent/Content/SVY21_Conversion_Formulae.pdf
"""
import math


def svy21_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """
    Convert SVY21 (E, N) in metres to WGS84 (latitude, longitude).
    Returns (lat, lon).
    """
    # SVY21 projection constants
    a = 6378137.0           # semi-major axis (WGS84)
    f = 1 / 298.257223563   # flattening
    b = a * (1 - f)
    e2 = 2*f - f*f

    # SVY21 origin
    lat0 = math.radians(1.366666)    # 1° 22' 00"N
    lon0 = math.radians(103.833333)  # 103° 50' 00"E
    N0, E0 = 38744.572, 28001.642    # false northing/easting
    k0 = 1.0                          # scale factor

    # Intermediate values
    n = (a - b) / (a + b)
    G = a * (1 - n) * (1 - n*n) * (1 + 9*n*n/4 + 225*n**4/64) * math.pi / 180

    # Meridional arc
    M_prime = (northing - N0) / k0
    sigma = M_prime * math.pi / (180 * G)

    # Footprint latitude
    lat_prime = (sigma
                 + (3*n/2 - 27*n**3/32) * math.sin(2*sigma)
                 + (21*n**2/16 - 55*n**4/32) * math.sin(4*sigma)
                 + (151*n**3/96) * math.sin(6*sigma)
                 + (1097*n**4/512) * math.sin(8*sigma))

    rho = a * (1 - e2) / (1 - e2 * math.sin(lat_prime)**2)**1.5
    nu = a / math.sqrt(1 - e2 * math.sin(lat_prime)**2)
    psi = nu / rho
    t = math.tan(lat_prime)

    E_prime = (easting - E0) / (k0 * nu)

    # Latitude
    term1 = t / (k0 * rho) * (easting - E0) * E_prime / 2
    term2 = t / (k0 * rho) * (easting - E0) * E_prime**3 / 24 * (-4*psi**2 + 9*psi*(1 - t**2) + 12*t**2)
    lat = lat_prime - term1 + term2

    # Longitude
    sec_lat = 1 / math.cos(lat_prime)
    lon = (lon0
           + E_prime * sec_lat
           - E_prime**3 * sec_lat / 6 * (psi + 2*t**2)
           + E_prime**5 * sec_lat / 120 * (-2*psi**3*(1 - 28*t**2) + psi**2*(5 - 72*t**2) + 660*psi*t**2 + 576*t**4))

    return math.degrees(lat), math.degrees(lon)


def wgs84_to_svy21(lat: float, lon: float) -> tuple[float, float]:
    """Convert WGS84 (lat, lon) to SVY21 (easting, northing)."""
    a = 6378137.0
    f = 1 / 298.257223563
    b = a * (1 - f)
    e2 = 2*f - f*f

    lat0 = math.radians(1.366666)
    lon0 = math.radians(103.833333)
    N0, E0 = 38744.572, 28001.642
    k0 = 1.0

    lat_r = math.radians(lat)
    lon_r = math.radians(lon)

    n_val = (a - b) / (a + b)
    rho = a * (1 - e2) / (1 - e2 * math.sin(lat_r)**2)**1.5
    nu = a / math.sqrt(1 - e2 * math.sin(lat_r)**2)
    psi = nu / rho
    t = math.tan(lat_r)
    l = lon_r - lon0

    # Meridional arc from equator to lat
    A0 = 1 - e2/4 - 3*e2**2/64 - 5*e2**3/256
    A2 = 3/8 * (e2 + e2**2/4 + 15*e2**3/128)
    A4 = 15/256 * (e2**2 + 3*e2**3/4)
    A6 = 35*e2**3/3072
    M = a * (A0*lat_r - A2*math.sin(2*lat_r) + A4*math.sin(4*lat_r) - A6*math.sin(6*lat_r))
    M0 = a * (A0*lat0 - A2*math.sin(2*lat0) + A4*math.sin(4*lat0) - A6*math.sin(6*lat0))

    northing = k0 * (M - M0 + nu*math.tan(lat_r) * (
        l**2/2 + l**4/24*(5 - t**2 + 9*psi + 4*psi**2)
    )) + N0

    easting = k0 * nu * (
        l + l**3/6*(psi - t**2) + l**5/120*(5 - 18*t**2 + t**4 + 14*psi - 58*psi*t**2)
    ) * math.cos(lat_r) + E0

    return easting, northing
