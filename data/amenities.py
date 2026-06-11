"""
Singapore amenity data for map overlays.
- Hawker centres (data.gov.sg, ~114 NEA-managed hawkers)
- Shopping malls (hardcoded ~55 major malls)
- Primary schools (MOE, hardcoded representative set)
- Parks / green spaces (NParks representative set)
No external API needed at runtime — static dataset.
"""

# ────────────────────────────────────────────────────────────────────────────
# HAWKER CENTRES (NEA-managed, ~114 centres, representative subset of 80+)
# (name, lat, lon)
# ────────────────────────────────────────────────────────────────────────────
HAWKER_CENTRES = [
    ("Adam Road Food Centre", 1.3250, 103.8138),
    ("Alexandra Village Food Centre", 1.2889, 103.8067),
    ("Amoy Street Food Centre", 1.2801, 103.8472),
    ("Ang Mo Kio 628 Market", 1.3720, 103.8454),
    ("Ang Mo Kio 724 Hawker Centre", 1.3695, 103.8476),
    ("Bedok Interchange Hawker Centre", 1.3240, 103.9303),
    ("Bedok North Street 1 Blk 511", 1.3345, 103.9308),
    ("Berseh Food Centre", 1.3078, 103.8567),
    ("Bishan North Hawker Centre", 1.3662, 103.8440),
    ("Blk 79 Redhill Lane", 1.2888, 103.8190),
    ("Bukit Merah Central Food Centre", 1.2820, 103.8218),
    ("Bukit Timah Market", 1.3263, 103.8013),
    ("Changi Village Hawker Centre", 1.3871, 103.9870),
    ("Chinatown Complex Food Centre", 1.2847, 103.8442),
    ("Chong Pang Market", 1.4383, 103.8224),
    ("Ci Yuan Hawker Centre", 1.3720, 103.8748),
    ("Circuit Road Hawker Centre", 1.3201, 103.8890),
    ("Clementi 448 Market", 1.3148, 103.7654),
    ("Commonwealth Crescent Market", 1.3020, 103.7990),
    ("Dunman Food Centre", 1.3066, 103.9009),
    ("East Coast Lagoon Food Village", 1.3078, 103.9108),
    ("Geylang Serai Market", 1.3145, 103.8981),
    ("Golden Mile Food Centre", 1.3020, 103.8640),
    ("Ghim Moh Market", 1.3098, 103.7863),
    ("Haig Road Market", 1.3137, 103.8934),
    ("Holland Drive Market", 1.3115, 103.7965),
    ("Hong Lim Food Centre", 1.2844, 103.8456),
    ("Hougang 105 Market", 1.3734, 103.8859),
    ("Hougang Hawker Centre 253", 1.3713, 103.8931),
    ("IMM Building Food Court", 1.3330, 103.7422),
    ("Jurong East Hawker Centre 505", 1.3437, 103.7433),
    ("Jurong West 505 Hawker Centre", 1.3470, 103.7095),
    ("Kaki Bukit 538 Market", 1.3355, 103.9095),
    ("Kallang Estate Fresh Market", 1.3133, 103.8717),
    ("Kampung Admiralty Hawker Centre", 1.4411, 103.8006),
    ("Kebun Baru Hawker Centre", 1.3744, 103.8355),
    ("Kovan Hawker Centre 210", 1.3605, 103.8848),
    ("Lau Pa Sat Festival Market", 1.2801, 103.8503),
    ("Lavender Food Square", 1.3087, 103.8623),
    ("Marine Parade Central Market", 1.3019, 103.9064),
    ("Maxwell Food Centre", 1.2803, 103.8448),
    ("Mei Ling Street Market 159", 1.2900, 103.8040),
    ("Marsiling Mall Hawker Centre", 1.4326, 103.7739),
    ("Newton Food Centre", 1.3130, 103.8376),
    ("Nee Soon Central Hawker Centre", 1.4262, 103.8284),
    ("Old Airport Road Hawker Centre", 1.3127, 103.8841),
    ("Our Tampines Hub Hawker Centre", 1.3524, 103.9449),
    ("Pasir Ris Central Hawker Centre", 1.3728, 103.9494),
    ("Pek Kio Market & Food Centre", 1.3116, 103.8491),
    ("People's Park Food Centre", 1.2839, 103.8437),
    ("Potong Pasir Hawker 148A", 1.3322, 103.8703),
    ("Punggol Oasis Hawker Centre", 1.4035, 103.9082),
    ("Queenstown Hawker 49A", 1.2953, 103.8065),
    ("Redhill Food Centre", 1.2890, 103.8180),
    ("Seletar Mall Food Hall", 1.3954, 103.8677),
    ("Sembawang Hills Food Centre", 1.3706, 103.8293),
    ("Serangoon Garden Market", 1.3624, 103.8653),
    ("Shunfu Mart", 1.3560, 103.8404),
    ("Siglap South Hawker 55", 1.3065, 103.9278),
    ("Taman Jurong Market", 1.3307, 103.7208),
    ("Tampines Round Market", 1.3560, 103.9405),
    ("Tekka Centre", 1.3065, 103.8499),
    ("Toa Payoh Lorong 1 Market", 1.3347, 103.8454),
    ("Toa Payoh Lorong 7 Hawker", 1.3370, 103.8540),
    ("Toa Payoh Lorong 8 Market", 1.3369, 103.8440),
    ("Tiong Bahru Market", 1.2866, 103.8263),
    ("Whampoa Drive Makan Place", 1.3195, 103.8616),
    ("West Coast Drive Market 726", 1.2944, 103.7778),
    ("Woodlands 11 Market", 1.4335, 103.7855),
    ("Woodlands 6A Hawker 306", 1.4308, 103.7867),
    ("Yishun Park Hawker Centre", 1.4293, 103.8357),
    ("Zion Road Food Centre", 1.2871, 103.8312),
]

# ────────────────────────────────────────────────────────────────────────────
# SHOPPING MALLS (major malls, 55+)
# ────────────────────────────────────────────────────────────────────────────
SHOPPING_MALLS = [
    # Central / Orchard
    ("ION Orchard", 1.3040, 103.8319),
    ("Ngee Ann City / Takashimaya", 1.3026, 103.8318),
    ("Wisma Atria", 1.3027, 103.8325),
    ("313@somerset", 1.3001, 103.8385),
    ("Orchard Central", 1.3014, 103.8385),
    ("Mandarin Gallery", 1.3028, 103.8348),
    ("Plaza Singapura", 1.3003, 103.8463),
    ("Bugis Junction", 1.2994, 103.8546),
    ("Bugis+", 1.2997, 103.8551),
    ("Raffles City", 1.2930, 103.8529),
    ("Marina Square", 1.2892, 103.8581),
    ("Suntec City", 1.2942, 103.8577),
    ("Marina Bay Sands", 1.2834, 103.8607),
    ("VivoCity", 1.2644, 103.8218),
    ("HarbourFront Centre", 1.2660, 103.8212),
    ("Great World City", 1.2929, 103.8243),
    ("Valley Point", 1.2942, 103.8219),
    ("Tiong Bahru Plaza", 1.2860, 103.8263),
    # North
    ("Causeway Point", 1.4351, 103.7865),
    ("Northpoint City", 1.4296, 103.8356),
    ("Sun Plaza", 1.4490, 103.8203),
    ("Sembawang Shopping Centre", 1.4487, 103.8198),
    ("Woodlands Mall", 1.4370, 103.7884),
    ("Canberra Plaza", 1.4432, 103.8299),
    # North-East
    ("AMK Hub", 1.3699, 103.8495),
    ("Djitsun Mall Ang Mo Kio", 1.3723, 103.8457),
    ("NEX", 1.3501, 103.8723),
    ("Heartland Mall Kovan", 1.3609, 103.8855),
    ("Hougang Mall", 1.3715, 103.8924),
    ("Compass One", 1.3916, 103.8954),
    ("Waterway Point", 1.4056, 103.9023),
    ("Rivervale Mall", 1.3939, 103.8776),
    # East
    ("Tampines Mall", 1.3527, 103.9455),
    ("Century Square", 1.3528, 103.9453),
    ("Eastpoint Mall", 1.3432, 103.9531),
    ("Parkway Parade", 1.3023, 103.9056),
    ("Bedok Mall", 1.3239, 103.9298),
    ("White Sands", 1.3727, 103.9493),
    ("Changi City Point", 1.3354, 103.9616),
    # West
    ("JEM", 1.3332, 103.7425),
    ("IMM", 1.3331, 103.7426),
    ("Westgate", 1.3336, 103.7430),
    ("Bukit Panjang Plaza", 1.3789, 103.7759),
    ("Hillion Mall", 1.3790, 103.7757),
    ("Lot One", 1.3852, 103.7445),
    ("West Mall", 1.3493, 103.7494),
    ("Jurong Point", 1.3387, 103.7061),
    ("The Star Vista", 1.3074, 103.7889),
    # Central-ish
    ("Novena Square", 1.3202, 103.8435),
    ("Square 2", 1.3200, 103.8430),
    ("The Centrepoint", 1.3024, 103.8377),
    ("Toa Payoh HDB Hub", 1.3325, 103.8469),
    ("Bishan Junction 8", 1.3509, 103.8488),
    ("Thomson Plaza", 1.3533, 103.8317),
    ("United Square", 1.3200, 103.8444),
]

# ────────────────────────────────────────────────────────────────────────────
# PRIMARY SCHOOLS — MOE (hardcoded representative 80+, P1 registration zones
# ────────────────────────────────────────────────────────────────────────────
PRIMARY_SCHOOLS = [
    ("Anglo-Chinese School (Primary)", 1.3046, 103.8447),
    ("Anglo-Chinese School (Junior)", 1.3216, 103.8143),
    ("Ai Tong School", 1.3596, 103.8499),
    ("Anchor Green Primary", 1.3571, 103.9564),
    ("Anderson Primary", 1.3790, 103.8320),
    ("Bedok Green Primary", 1.3295, 103.9377),
    ("Bendemeer Primary", 1.3130, 103.8628),
    ("Bukit Timah Primary", 1.3411, 103.7829),
    ("Bukit View Primary", 1.3576, 103.7595),
    ("Cantonment Primary", 1.2810, 103.8383),
    ("Catholic High School (Primary)", 1.3509, 103.8480),
    ("CHIJ (Katong) Primary", 1.2988, 103.9012),
    ("CHIJ Primary (Toa Payoh)", 1.3360, 103.8462),
    ("Chua Chu Kang Primary", 1.3887, 103.7434),
    ("Clementi Primary", 1.3151, 103.7649),
    ("Compassvale Primary", 1.3948, 103.8961),
    ("Coral Primary", 1.3720, 103.9491),
    ("Da Qiao Primary", 1.3815, 103.8927),
    ("Damai Primary", 1.3356, 103.9295),
    ("East Spring Primary", 1.3582, 103.9435),
    ("Edgefield Primary", 1.4014, 103.8997),
    ("Elias Park Primary", 1.3741, 103.9478),
    ("Endeavour Primary", 1.4340, 103.7884),
    ("Eunos Primary", 1.3198, 103.9024),
    ("Fairfield Methodist School (Primary)", 1.2948, 103.8085),
    ("Farrer Park Primary", 1.3110, 103.8567),
    ("Fengshan Primary", 1.3218, 103.9365),
    ("Fernvale Primary", 1.3947, 103.8697),
    ("Geylang Methodist School (Primary)", 1.3171, 103.8887),
    ("Gongshang Primary", 1.3534, 103.9339),
    ("Henry Park Primary", 1.3070, 103.7850),
    ("Holy Innocents' Primary", 1.3724, 103.8906),
    ("Hong Kah Primary", 1.3490, 103.7223),
    ("Hougang Primary", 1.3677, 103.8833),
    ("Keming Primary", 1.3510, 103.7570),
    ("Kuo Chuan Presbyterian Primary", 1.3513, 103.8478),
    ("Lakeside Primary", 1.3450, 103.7219),
    ("Maha Bodhi School", 1.3072, 103.8831),
    ("Marymount Convent School", 1.3492, 103.8378),
    ("Meridian Primary", 1.3743, 103.9486),
    ("Methodist Girls' School (Primary)", 1.3211, 103.8141),
    ("Montfort Junior School", 1.3426, 103.8800),
    ("Nanyang Primary", 1.3238, 103.8066),
    ("Nanhua Primary", 1.3040, 103.7703),
    ("Naval Base Primary", 1.4386, 103.8249),
    ("North Spring Primary", 1.3812, 103.8939),
    ("North View Primary", 1.4299, 103.8363),
    ("Northland Primary", 1.4370, 103.7880),
    ("Oasis Primary", 1.3889, 103.9080),
    ("Opera Estate Primary", 1.3139, 103.9170),
    ("Park View Primary", 1.3965, 103.8991),
    ("Peiying Primary", 1.4143, 103.8155),
    ("Poi Ching School", 1.3548, 103.9459),
    ("Princess Elizabeth Primary", 1.3493, 103.7497),
    ("Qihua Primary", 1.3899, 103.8021),
    ("Red Swastika School", 1.3256, 103.9306),
    ("Rivervale Primary", 1.3944, 103.8779),
    ("Rosyth School", 1.3617, 103.8631),
    ("Sembawang Primary", 1.4505, 103.8245),
    ("Sengkang Green Primary", 1.4044, 103.8948),
    ("Springdale Primary", 1.3880, 103.8912),
    ("St. Anthony's Canossian Primary", 1.3147, 103.8893),
    ("St. Hilda's Primary", 1.3552, 103.9453),
    ("St. Margaret's Primary", 1.3044, 103.8367),
    ("Tampines Primary", 1.3561, 103.9416),
    ("Tao Nan School", 1.3012, 103.9049),
    ("Telok Kurau Primary", 1.3073, 103.9009),
    ("Waterway Primary", 1.4074, 103.9077),
    ("Wellington Primary", 1.3799, 103.8462),
    ("West Grove Primary", 1.3432, 103.7164),
    ("Westwood Primary", 1.3483, 103.7018),
    ("White Sands Primary", 1.3682, 103.9480),
    ("Woodgrove Primary", 1.4282, 103.7923),
    ("Yuhua Primary", 1.3416, 103.7218),
    ("Yusof Ishak Primary", 1.3391, 103.7448),
    ("Zhangde Primary", 1.3396, 103.8455),
    ("Zhenghua Primary", 1.3778, 103.7702),
]

# ────────────────────────────────────────────────────────────────────────────
# PARKS / GREEN CORRIDORS (major parks and nature areas)
# ────────────────────────────────────────────────────────────────────────────
PARKS = [
    ("East Coast Park", 1.3010, 103.9121),
    ("Bishan-Ang Mo Kio Park", 1.3611, 103.8459),
    ("Botanic Gardens", 1.3138, 103.8159),
    ("West Coast Park", 1.2949, 103.7765),
    ("Punggol Waterway Park", 1.4065, 103.9071),
    ("Pasir Ris Park", 1.3780, 103.9543),
    ("Bedok Reservoir Park", 1.3362, 103.9323),
    ("Jurong Lake Gardens", 1.3383, 103.7256),
    ("Kent Ridge Park", 1.2911, 103.7843),
    ("MacRitchie Reservoir Park", 1.3535, 103.8219),
    ("Lower Seletar Reservoir Park", 1.4009, 103.8639),
    ("Tampines Eco Green", 1.3558, 103.9573),
    ("Sembawang Park", 1.4618, 103.8177),
    ("Sungei Buloh Wetland Reserve", 1.4471, 103.7236),
    ("Gardens by the Bay", 1.2816, 103.8636),
    ("Fort Canning Park", 1.2943, 103.8447),
    ("Hort Park", 1.2818, 103.8021),
    ("Labrador Nature Reserve", 1.2666, 103.8029),
    ("Clementi Forest", 1.3220, 103.7650),
    ("Admiralty Park", 1.4446, 103.7997),
    ("Coney Island Park", 1.4123, 103.9153),
    ("Bukit Timah Nature Reserve", 1.3549, 103.7762),
    ("Hindhede Nature Park", 1.3490, 103.7757),
    ("Central Catchment Nature Reserve", 1.3582, 103.8223),
    ("Windsor Nature Park", 1.3743, 103.8174),
]


def get_amenities_by_type(amenity_type: str) -> list[tuple]:
    """
    Returns list of (name, lat, lon) for the given amenity type.
    amenity_type: 'hawker', 'mall', 'school', 'park'
    """
    mapping = {
        "hawker": HAWKER_CENTRES,
        "mall": SHOPPING_MALLS,
        "school": PRIMARY_SCHOOLS,
        "park": PARKS,
    }
    return mapping.get(amenity_type, [])


def nearest_amenities(lat: float, lon: float, amenity_type: str, top_n: int = 5) -> list[dict]:
    """
    Return top_n nearest amenities of the given type sorted by distance.
    Uses Haversine.
    """
    import math

    def _hav(lat1, lon1, lat2, lon2):
        R = 6_371_000
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    data = get_amenities_by_type(amenity_type)
    results = []
    for name, alat, alon in data:
        dist = _hav(lat, lon, alat, alon)
        results.append({"name": name, "lat": alat, "lon": alon, "distance_m": round(dist),
                        "walk_min": round(dist / 80)})
    results.sort(key=lambda x: x["distance_m"])
    return results[:top_n]
