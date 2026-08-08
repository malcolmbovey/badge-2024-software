# Offline ICAO -> airline name lookup, used only as a fallback when a logo
# image (see app.py's _ensure_logo) can't be fetched or hasn't loaded yet --
# the logo itself is fetched dynamically per flight from FlightRadar24's CDN
# and works for essentially any airline FR24 tracks, so this table doesn't
# need to be exhaustive. It leans towards carriers seen at/around London
# Heathrow (compiled by hand, not scraped -- treat as best-effort, not
# authoritative) plus a few of the most common UK/European low-cost and
# cargo operators likely to be overflying rather than landing nearby.
#
# Anything missing here just falls back to showing the raw ICAO code, which
# is always correct even if not pretty -- so gaps are low-risk.

AIRLINE_NAMES = {
    # UK & Ireland
    "BAW": "British Airways",
    "VIR": "Virgin Atlantic",
    "EIN": "Aer Lingus",
    "LOG": "Loganair",
    "TOM": "TUI Airways",
    "EXS": "Jet2.com",
    "EZY": "easyJet",
    "RYR": "Ryanair",
    "WZZ": "Wizz Air",
    "NAX": "Norwegian",
    "NOZ": "Norse Atlantic Airways",
    # Western Europe
    "AFR": "Air France",
    "KLM": "KLM",
    "DLH": "Lufthansa",
    "SWR": "Swiss International Air Lines",
    "AUA": "Austrian Airlines",
    "BEL": "Brussels Airlines",
    "IBE": "Iberia",
    "VLG": "Vueling",
    "TAP": "TAP Air Portugal",
    "ITY": "ITA Airways",
    "NOS": "Neos",
    # Nordics & Baltics
    "SAS": "Scandinavian Airlines",
    "FIN": "Finnair",
    "ICE": "Icelandair",
    "BTI": "Air Baltic",
    # Central & Eastern Europe
    "LOT": "LOT Polish Airlines",
    "ROT": "TAROM",
    "AEE": "Aegean Airlines",
    "ASL": "Air Serbia",
    "THY": "Turkish Airlines",
    "PGT": "Pegasus Airlines",
    "AHY": "Azerbaijan Airlines",
    "KZR": "Air Astana",
    "UZB": "Uzbekistan Airways",
    # Middle East
    "UAE": "Emirates",
    "QTR": "Qatar Airways",
    "ETD": "Etihad Airways",
    "SVA": "Saudia",
    "GFA": "Gulf Air",
    "KAC": "Kuwait Airways",
    "RJA": "Royal Jordanian",
    "MEA": "Middle East Airlines",
    "OMA": "Oman Air",
    # Africa
    "ETH": "Ethiopian Airlines",
    "KQA": "Kenya Airways",
    "SAA": "South African Airways",
    "RAM": "Royal Air Maroc",
    "MSR": "EgyptAir",
    "DAH": "Air Algerie",
    # South & Southeast Asia
    "AIC": "Air India",
    "BBC": "Biman Bangladesh Airlines",
    "THA": "Thai Airways",
    "MAS": "Malaysia Airlines",
    "PAL": "Philippine Airlines",
    "GIA": "Garuda Indonesia",
    "HVN": "Vietnam Airlines",
    "SIA": "Singapore Airlines",
    "RBA": "Royal Brunei Airlines",
    # East Asia
    "ANA": "All Nippon Airways",
    "JAL": "Japan Airlines",
    "CCA": "Air China",
    "CES": "China Eastern",
    "CSN": "China Southern",
    "CHH": "Hainan Airlines",
    "CXA": "Xiamen Airlines",
    "KAL": "Korean Air",
    "AAR": "Asiana Airlines",
    "CPA": "Cathay Pacific",
    # Oceania
    "QFA": "Qantas",
    # North America
    "AAL": "American Airlines",
    "DAL": "Delta Air Lines",
    "UAL": "United Airlines",
    "ACA": "Air Canada",
    "WJA": "WestJet",
    "JBU": "JetBlue Airways",
    "ASA": "Alaska Airlines",
    # Latin America
    "LAN": "LATAM Airlines",
    "AVA": "Avianca",
    "AMX": "Aeromexico",
    # Cargo (occasionally the nearest aircraft is an overflying freighter)
    "FDX": "FedEx Express",
    "UPS": "UPS Airlines",
    "DHK": "DHL Air",
}


def airline_name(icao):
    """Return the full airline name for an ICAO code, or None if unknown."""
    if not icao:
        return None
    return AIRLINE_NAMES.get(icao.upper())


# Approximate brand colour per airline, for the outer LED ring (see
# app.py's _apply_led_color). Hand-picked to be recognisable rather than
# colour-accurate -- these are 18-LED decorative lights, not a swatch book.
# Only covers a subset of AIRLINE_NAMES: airlines without a strong single
# "signature" colour (or that would be indistinguishable from another entry
# at LED resolution) are left out on purpose, and the LEDs just keep their
# normal pattern for those rather than showing a made-up colour.
AIRLINE_COLORS = {
    # UK & Ireland
    "BAW": (10, 40, 100),     # British Airways -- navy blue
    "VIR": (227, 6, 19),      # Virgin Atlantic -- red
    "EIN": (0, 99, 65),       # Aer Lingus -- shamrock green
    "TOM": (0, 101, 156),     # TUI Airways -- TUI blue
    "EZY": (255, 102, 0),     # easyJet -- orange
    "RYR": (7, 53, 144),      # Ryanair -- blue (with gold harp accent)
    "WZZ": (198, 0, 126),     # Wizz Air -- magenta
    "NAX": (203, 32, 39),     # Norwegian -- red
    # Western Europe
    "AFR": (190, 30, 45),     # Air France -- red
    "KLM": (0, 161, 222),     # KLM -- sky blue
    "DLH": (5, 30, 74),       # Lufthansa -- navy blue
    "SWR": (255, 0, 0),       # Swiss -- red
    "IBE": (215, 25, 32),     # Iberia -- red
    "TAP": (0, 105, 92),      # TAP Air Portugal -- teal green
    "ITY": (0, 60, 113),      # ITA Airways -- blue
    # Nordics
    "SAS": (13, 43, 92),      # Scandinavian Airlines -- navy blue
    "FIN": (0, 44, 119),      # Finnair -- blue
    "ICE": (0, 61, 165),      # Icelandair -- blue
    # Central & Eastern Europe / Turkey
    "THY": (227, 10, 23),     # Turkish Airlines -- red
    "PGT": (255, 90, 0),      # Pegasus Airlines -- orange
    # Middle East
    "UAE": (209, 32, 40),     # Emirates -- red
    "QTR": (119, 24, 45),     # Qatar Airways -- maroon
    "ETD": (198, 146, 61),    # Etihad Airways -- gold
    "GFA": (161, 30, 45),     # Gulf Air -- burgundy
    "RJA": (150, 24, 41),     # Royal Jordanian -- maroon
    # Africa
    "ETH": (0, 128, 68),      # Ethiopian Airlines -- green
    "KQA": (198, 30, 46),     # Kenya Airways -- red
    "MSR": (0, 84, 60),       # EgyptAir -- green
    # South & Southeast Asia
    "AIC": (240, 90, 40),     # Air India -- vermillion
    "THA": (90, 24, 130),     # Thai Airways -- purple
    "SIA": (196, 155, 87),    # Singapore Airlines -- gold
    # East Asia
    "JAL": (189, 16, 27),     # Japan Airlines -- red
    "ANA": (19, 68, 143),     # All Nippon Airways -- blue
    "CPA": (0, 101, 100),     # Cathay Pacific -- jade green
    "KAL": (7, 42, 105),      # Korean Air -- blue
    # Oceania
    "QFA": (238, 24, 34),     # Qantas -- red
    # North America
    "AAL": (0, 61, 165),      # American Airlines -- blue
    "DAL": (224, 25, 48),     # Delta Air Lines -- red
    "UAL": (0, 51, 160),      # United Airlines -- blue
    "ACA": (241, 27, 44),     # Air Canada -- red
    "JBU": (0, 87, 181),      # JetBlue Airways -- blue
    # Latin America
    "AVA": (220, 20, 60),     # Avianca -- red
    # Cargo
    "FDX": (76, 26, 128),     # FedEx Express -- purple
    "UPS": (60, 33, 12),      # UPS Airlines -- brown
    "DHK": (255, 204, 0),     # DHL Air -- yellow
}


def airline_color(icao):
    """Return an (r, g, b) tuple (0-255) for an ICAO code, or None if this
    airline doesn't have an assigned colour -- callers should leave the LEDs
    on their normal pattern in that case rather than guessing a colour."""
    if not icao:
        return None
    return AIRLINE_COLORS.get(icao.upper())
