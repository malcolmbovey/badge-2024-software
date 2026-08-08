# Nearest Plane (flight_tracker)

Shows live info about the nearest aircraft to your location on the badge
screen: flight number, airline, aircraft type, origin/destination, distance,
speed, heading and altitude.

## Features

- Polls FlightRadar24's unofficial live-feed endpoint for aircraft within a
  configurable radius of your location, and picks the closest one.
- Distance, speed and altitude are computed/converted client-side (haversine
  distance in km, knots → km/h, heading → 16-point compass label).
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
- **`_refresh()`** — ensures wifi is connected, calls `_fetch_nearest`, and
  only updates `last_updated` on a clean result — an exception (network
  error, non-200, etc.) leaves the previous "Updated Ns ago" timestamp
  alone rather than resetting it.
- **`background_task()`** — refreshes on a fixed `refresh_seconds` interval.
  No exit-early-on-user-action logic is needed here since (unlike the bus
  app) there's no second stop/location to switch to.
- **`update(delta)`** — handles the CANCEL-to-exit button and a 1-second
  dirty-flag tick so the "Updated Ns ago" footer keeps counting up.
- **`draw(ctx)`** — renders the header, then either the current `status`
  message (`Loading…`, `No planes nearby`, an error) or the nearest flight's
  details stacked top-to-bottom: flight number, airline/aircraft type,
  route, distance (large, accent colour), speed/heading, altitude, and
  finally the "Updated Ns ago" footer.
