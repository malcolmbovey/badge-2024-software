# Pure-Python helpers for talking to FlightRadar24's unofficial live-feed
# endpoint and picking the nearest aircraft out of the response. Kept free of
# any network/hardware calls (those live in app.py) so this module can be
# exercised in the desktop sim -- or plain CPython -- without wifi/requests.
#
# The feed's per-flight array layout below was confirmed against the
# FlightRadarAPI reference implementation's entities/flight.py, not guessed:
# https://github.com/JeanExtreme002/FlightRadarAPI

import math

DEFAULT_FEED_URL = "https://data-cloud.flightradar24.com/zones/fcgi/feed.js"

# FR24 fronts this endpoint with Cloudflare bot management, which mainly
# fingerprints the TLS handshake -- these headers are a best-effort match for
# a real browser's HTTP-level request, but they can't fix a MicroPython TLS
# stack looking nothing like Chrome's. See the app's README for what to do
# if requests start getting blocked.
FEED_HEADERS = {
    "accept": "application/json",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
    "origin": "https://www.flightradar24.com",
    "referer": "https://www.flightradar24.com/",
}

# Field indices within each flight's array in the feed response.
_LATITUDE = 1
_LONGITUDE = 2
_HEADING = 3
_ALTITUDE = 4
_GROUND_SPEED = 5
_AIRCRAFT_CODE = 8
_ORIGIN_IATA = 11
_DESTINATION_IATA = 12
_FLIGHT_NUMBER = 13
_ON_GROUND = 14
_CALLSIGN = 16
_AIRLINE_ICAO = 18

_COMPASS_POINTS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)

KNOTS_TO_KMH = 1.852
_KM_PER_DEGREE_LAT = 111.32


def bounding_box(lat, lon, radius_km):
    """Return an FR24 "bounds" query value (north,south,west,east) for a
    square of the given half-width in km, centred on (lat, lon)."""
    lat_rad = math.radians(lat)
    dlat = radius_km / _KM_PER_DEGREE_LAT
    # Longitude degrees shrink towards the poles; clamp so this stays finite
    # at very high latitudes instead of blowing up near cos(90deg) == 0.
    dlon = radius_km / (_KM_PER_DEGREE_LAT * max(math.cos(lat_rad), 0.01))
    north = lat + dlat
    south = lat - dlat
    west = lon - dlon
    east = lon + dlon
    return "{:.4f},{:.4f},{:.4f},{:.4f}".format(north, south, west, east)


def feed_url(lat, lon, radius_km, base_url=DEFAULT_FEED_URL):
    """Build the full feed URL for the nearest-plane search area.

    gnd/vehicles are left off (0) since only airborne traffic is of
    interest here; find_nearest() also filters on the on-ground flag as a
    belt-and-braces check in case a grounded aircraft slips through anyway.
    """
    bounds = bounding_box(lat, lon, radius_km)
    params = (
        "bounds={}&faa=1&satellite=1&mlat=1&flarm=1&adsb=1"
        "&gnd=0&air=1&vehicles=0&estimated=1&maxage=14400&gliders=0&stats=0"
    ).format(bounds)
    return "{}?{}".format(base_url, params)


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points, in kilometres."""
    earth_radius_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * earth_radius_km * math.asin(math.sqrt(min(1, a)))


def compass_point(degrees):
    """Turn a heading in degrees into a 16-point compass label, e.g. 'NE'."""
    if degrees is None:
        return None
    index = int((degrees % 360) / 22.5 + 0.5) % 16
    return _COMPASS_POINTS[index]


def _get(entry, index, default=None):
    try:
        value = entry[index]
    except (IndexError, TypeError):
        return default
    return value if value not in (None, "") else default


def parse_flight(entry):
    """Turn one raw feed array into a plain dict of the fields this app
    displays. Returns None if the entry is missing a usable position."""
    lat = _get(entry, _LATITUDE)
    lon = _get(entry, _LONGITUDE)
    if lat is None or lon is None:
        return None

    flight_number = _get(entry, _FLIGHT_NUMBER)
    callsign = _get(entry, _CALLSIGN)

    return {
        "lat": lat,
        "lon": lon,
        "heading": _get(entry, _HEADING),
        "altitude_ft": _get(entry, _ALTITUDE),
        "ground_speed_kt": _get(entry, _GROUND_SPEED),
        "aircraft_type": _get(entry, _AIRCRAFT_CODE),
        "origin": _get(entry, _ORIGIN_IATA),
        "destination": _get(entry, _DESTINATION_IATA),
        "flight_number": flight_number,
        "callsign": callsign,
        "label": flight_number or callsign or "Unknown",
        "airline_icao": _get(entry, _AIRLINE_ICAO),
        "on_ground": _get(entry, _ON_GROUND) == 1,
    }


def find_nearest(feed_json, home_lat, home_lon):
    """Parse a raw feed response dict and return the nearest airborne
    flight, with a "distance_km" key added, or None if there isn't one."""
    nearest = None
    nearest_distance = None

    for flight_id, entry in feed_json.items():
        # Non-flight keys in the response ("full_count", "version", "stats")
        # don't start with a digit; real flight IDs are hex-ish but always
        # digit-first, matching the check the reference client uses.
        if not flight_id or not flight_id[0].isdigit():
            continue
        flight = parse_flight(entry)
        if flight is None or flight["on_ground"]:
            continue
        distance = haversine_km(home_lat, home_lon, flight["lat"], flight["lon"])
        if nearest_distance is None or distance < nearest_distance:
            nearest = flight
            nearest_distance = distance

    if nearest is not None:
        nearest["distance_km"] = nearest_distance
    return nearest
