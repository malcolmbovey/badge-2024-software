# Nearest Plane (flight_tracker)

Shows live info about the nearest aircraft to your location on the badge
screen: flight number, airline (name and, where available, logo), aircraft
type, origin/destination, distance, speed, heading and altitude. The outer
LED ring also tints to the airline's brand colour where known (e.g. easyJet
→ orange).

## Features

- Polls FlightRadar24's unofficial live-feed endpoint for aircraft within a
  configurable radius of your location, and picks the closest one.
- Distance, speed and altitude are computed/converted client-side (haversine
  distance in km, knots → km/h, heading → 16-point compass label).
- **Airline identity** is resolved in three falling-back steps, cheapest/best
  first:
  1. A logo image, fetched from FlightRadar24's CDN by airline code and
     cached locally (`logo_cache/`) so it's only downloaded once per airline
     ever seen. This works for essentially any airline FR24 has art for, not
     just a preset list.
  2. If no logo is available, the full airline name from a small hand-built
     offline lookup (`airlines.py`) — best-effort, leans towards carriers
     seen around London/Heathrow.
  3. If neither, the raw 3-letter ICAO code (e.g. `BAW`), same as before.
- **Outer LEDs** switch to the airline's brand colour (also `airlines.py`,
  hand-picked, not colour-accurate) while a flight with a known colour is on
  screen, and revert to the normal pattern otherwise or on exit.
- Location is currently a hardcoded lat/lon in `.env`, but reading it goes
  through a small `LocationProvider` abstraction (`location.py`) so it can be
  swapped for a real GPS sensor later without touching `app.py`.
- **CANCEL** exits the app (the badge-wide default — unlike `tfl_bus_times`,
  there's nothing here to cycle between, so no button roles are swapped).

## A caveat on the data source

FlightRadar24 doesn't offer a free public API. This app uses the same
unofficial endpoints as the popular
[`FlightRadarAPI`](https://github.com/JeanExtreme002/FlightRadarAPI) Python
package — no API key needed, but also no guarantee: FR24 fronts these
endpoints with Cloudflare, and the reference implementation only gets past
it by impersonating a real browser's TLS fingerprint (`curl_cffi`). The
badge's MicroPython `requests` module can't do that, so direct requests from
the badge may work fine, get blocked intermittently, or get blocked
outright — indistinguishable, on screen, from "no planes nearby" (it'll show
as a `FR24 error 403` instead, at least).

If that turns out to be a real problem in practice, the fix doesn't require
touching this app's code: point `FLIGHT_FEED_URL` in `.env` at a small relay
(e.g. a Raspberry Pi or laptop on your home network running `curl_cffi` and
re-serving the same JSON shape) instead of FR24 directly.

Airline logo images are served from a *different* host (FR24's CDN /
static asset server, not the Cloudflare-fronted feed API) and were reachable
directly with plain headers when this was tested — no TLS-impersonation
workaround needed there. If that changes, logo fetches just fail silently
per-airline and `draw()` falls back to the name/code text; there's no
separate override for the logo URLs.

### A second, separate caveat: empty-envelope responses

Distinct from the Cloudflare issue above (and observed directly while
building this app): FR24's feed endpoint sits behind a load balancer, and
some backends occasionally answer with a perfectly valid `200` but *zero*
flight entries — a bare `{"full_count": ..., "version": 4}` with nothing
else, regardless of the query. On screen that's indistinguishable from
genuinely no traffic in range. `_fetch_nearest()` in `app.py` retries a
handful of times before giving up and showing "No planes nearby", since a
retried request is a fresh connection and usually lands on a working
backend within a couple of attempts — see `_FEED_EMPTY_RETRIES` if you want
to tune how persistent it is.

## Setup

Copy `.env.example` to `.env` in this directory and fill in your location:

```
cp .env.example .env
```

`.env` is gitignored — your coordinates stay local and are never committed.

### Configuration keys

| Key | Required | Default | Description |
|---|---|---|---|
| `FLIGHT_HOME_LAT` | yes | — | Your latitude, decimal degrees. |
| `FLIGHT_HOME_LON` | yes | — | Your longitude, decimal degrees. |
| `FLIGHT_RADIUS_KM` | no | `50` | Half-width (km) of the square search area around your location. |
| `FLIGHT_REFRESH_SECONDS` | no | `60` | How often to re-poll for the nearest plane. |
| `FLIGHT_FEED_URL` | no | FR24's live-feed URL | Override to point at a relay (see caveat above) if direct requests get blocked. |

Logo images are cached under `logo_cache/` next to `app.py`, one small PNG
(a few KB) per distinct airline ever seen — gitignored, and not currently
size-capped, so on a badge that sees a lot of different airlines over a long
time this will slowly grow. Fine for personal use; delete the directory to
reclaim the space if it ever matters.

If `FLIGHT_HOME_LAT`/`FLIGHT_HOME_LON` aren't set, the app shows "Set
FLIGHT_HOME_LAT/LON in .env" and does nothing.

## Controls

| Button | Action |
|---|---|
| CANCEL | Exit the app. |

## Code walkthrough

### `location.py`

- **`LocationProvider`** — base class; `.get()` returns `(lat, lon)`.
- **`HardcodedLocation`** — the only concrete provider in use today, wrapping
  the coordinates read from `.env`.
- **`GPSLocation`** — unimplemented placeholder for when a GPS sensor exists.
  Takes an optional `fallback` provider (e.g. a `HardcodedLocation`) to use
  until/unless the sensor has a fix. `app.py` only ever calls `.get()` on
  whatever provider it's given, so switching providers is a one-line change
  in `_build_location()`.

### `flight_client.py`

Pure-Python, no network/hardware dependencies — the actual HTTP call lives in
`app.py` so this module stays testable in plain Python.

- **Field indices** (`_LATITUDE`, `_HEADING`, `_AIRLINE_ICAO`, etc.) — FR24's
  feed returns a dict keyed by flight ID, each value a positional array.
  These indices were confirmed against the current
  [`FlightRadarAPI` source](https://github.com/JeanExtreme002/FlightRadarAPI/blob/main/python/FlightRadarAPI/entities/flight.py),
  not guessed.
- **`bounding_box(lat, lon, radius_km)`** — turns a centre point + radius
  into the `"north,south,west,east"` string FR24's `bounds` query param
  expects, using a flat-earth approximation (fine at these radii) with a
  `cos(latitude)` correction for longitude so the box doesn't distort at
  higher latitudes.
- **`feed_url(...)`** — builds the full feed request URL, with `gnd`/
  `vehicles` left off since only airborne traffic is wanted.
- **`haversine_km(...)`** — great-circle distance between two points.
- **`compass_point(degrees)`** — turns a heading in degrees into a 16-point
  compass label (`N`, `NNE`, `NE`, ...).
- **`parse_flight(entry)`** — turns one raw feed array into a plain dict of
  the fields this app displays, falling back from flight number to callsign
  for the on-screen label when a flight number isn't available (common for
  GA/cargo traffic).
- **`find_nearest(feed_json, home_lat, home_lon)`** — iterates the feed
  response (skipping non-flight keys like `full_count`/`version`/`stats`,
  and any grounded aircraft), and returns the closest airborne flight with a
  `distance_km` key added, or `None`.
- **`airline_iata(flight_number)`** — best-effort IATA airline code from the
  first two characters of the flight number (e.g. `BA` from `BA123`), the
  same heuristic the FlightRadarAPI reference client uses since the feed
  doesn't give this directly. Returns `None` if there's no flight number to
  work from (common for GA/cargo).
- **`airline_logo_urls(icao, flight_number)`** — candidate logo image URLs,
  best option first: the CDN URL (needs IATA, so only included if
  `airline_iata` found one) then the ICAO-only fallback URL.
- **`png_dimensions(data)`** / **`is_png(data)`** — read a PNG's width/height
  straight out of its IHDR chunk header, so the app can lay out a bounding
  box for a logo without needing a full image decoder just to ask its size.

### `airlines.py`

Two hand-built offline lookups, both by ICAO airline code, both optional —
gaps just mean draw() falls back to the next thing in the chain described
under Features above:

- **`AIRLINE_NAMES`** / **`airline_name(icao)`** — full airline names.
- **`AIRLINE_COLORS`** / **`airline_color(icao)`** — brand colours for the
  LED ring, as `(r, g, b)` 0-255 tuples. Only covers airlines with a strong,
  recognisable, single signature colour; deliberately doesn't try to invent
  one for the rest.

Neither table is exhaustive or guaranteed accurate (compiled by hand, not
sourced from FR24 or any airline itself) — treat both as decorative rather
than authoritative.

### `app.py`

Structured the same way as `tfl_bus_times`'s `app.py`:

- **`_load_env`** — same hand-rolled `.env` parser (no dotenv library in
  MicroPython).
- **`_build_location(env)`** — constructs the `HardcodedLocation` from
  `.env`, or returns `None` if the coordinates aren't set yet.
- **`_format_speed`/`_format_direction`/`_format_altitude`/`_format_route`**
  — turn the raw parsed fields into the strings shown on screen.
- **`_fetch_nearest(lat, lon)`** — fetches the feed via `async_helpers.unblock`
  (so the blocking HTTP call doesn't stall the event loop) and hands the
  response to `flight_client.find_nearest`, retrying up to
  `_FEED_EMPTY_RETRIES` times if that comes back empty (see the empty-envelope
  caveat above). Raises on a non-200 response instead of retrying, since
  that's a different failure mode.
- **`_fetch_bytes(url, headers, timeout)`** — a plainer GET used for logo
  images: returns the raw body, or `None` on *any* failure (non-200, network
  error, timeout). Unlike `_fetch_nearest`, a miss here is just "no logo",
  not an app-level error.
- **`_ensure_logo(flight)`** — makes sure a cached logo file exists locally
  for the flight's airline. Checks `logo_cache/<icao>.png` first; if that's
  already there (from a previous sighting of this airline), reads just its
  24-byte header back for the dimensions and stops. Otherwise tries each URL
  from `flight_client.airline_logo_urls` in turn, writes the first valid PNG
  response to that cache path, and records it via `_set_logo`. Any failure
  along the way (no ICAO code, both URLs miss, a non-PNG response) just
  returns without setting anything — `draw()`'s fallback chain handles that.
- **`_set_logo(path, icao, width, height)`** — records a resolved logo
  (`logo_path`/`logo_airline_icao`/`logo_size`), pre-scaling the size to fit
  the `_LOGO_MAX_W`×`_LOGO_MAX_H` box while preserving aspect ratio, since
  FR24's logo art varies a lot in shape.
- **`_paint_leds(color)`** / **`_apply_led_color(color)`** — LED control,
  the same shape as `tfl_bus_times`'s urgent-LED handling: emits
  `PatternDisable`/`PatternEnable` on the eventbus so the badge's normal
  pattern generator doesn't fight over the LEDs, and is a no-op if the
  colour hasn't changed. `color=None` means "back to the normal pattern".
- **`_refresh()`** — ensures wifi is connected, calls `_fetch_nearest`, and
  only updates `last_updated` on a clean result — an exception (network
  error, non-200, etc.) leaves the previous "Updated Ns ago" timestamp
  alone rather than resetting it. On a successful result it then calls
  `_ensure_logo` (best-effort — swallows its own exceptions, since a logo
  failure shouldn't blank out flight data that already fetched fine) and
  applies that airline's LED colour, or reverts the LEDs if there's no
  flight to show.
- **`background_task()`** — refreshes on a fixed `refresh_seconds` interval.
  Between refreshes, repaints the current LED colour once a second while a
  colour override is active — same reasoning as `tfl_bus_times`: the pattern
  generator runs asynchronously and can otherwise leave a stale frame on
  screen after a race.
- **`update(delta)`** — handles the CANCEL-to-exit button (also reverting
  the LEDs before minimising) and a 1-second dirty-flag tick so the
  "Updated Ns ago" footer keeps counting up.
- **`_draw_airline(ctx, flight, cy)`** — the airline row: draws the cached
  logo image if one's resolved *and* matches the flight currently on screen
  (the icao check stops a stale logo from a previous flight flashing up
  before this cycle's `_ensure_logo` resolves), otherwise falls back to
  `airlines.airline_name` or, failing that, the raw ICAO code.
- **`draw(ctx)`** — renders the header, then either the current `status`
  message (`Loading…`, `No planes nearby`, an error) or the nearest flight's
  details stacked top-to-bottom: flight number, `_draw_airline`, aircraft
  type + route, distance (large, accent colour), speed/heading, altitude,
  and finally the "Updated Ns ago" footer.
