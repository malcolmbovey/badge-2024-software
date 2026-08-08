import asyncio
import time

import app
import async_helpers
import requests
import wifi
from app_components import utils
from events.input import BUTTON_TYPES, Buttons

from . import flight_client
from .location import HardcodedLocation

# os.path isn't available on-device (only in the desktop sim), so derive the
# app's own directory from __file__ with plain string ops instead.
_APP_DIR = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
_ENV_PATH = _APP_DIR + "/.env"

# FR24's feed endpoint sits behind a load balancer that can occasionally
# route a request to a backend that answers 200 with a well-formed but empty
# envelope (no flight entries at all, regardless of bounds) -- observed
# directly while building this app, and indistinguishable from "genuinely no
# traffic nearby" without retrying. Each request already sends
# "Connection: close" (see the requests library), so a retry is a fresh
# connection and usually lands on a working backend within a couple of
# attempts.
_FEED_EMPTY_RETRIES = 3
_FEED_RETRY_DELAY_SECONDS = 1.5


def _load_env(path):
    config = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return config


def _build_location(env):
    try:
        lat = float(env["FLIGHT_HOME_LAT"])
        lon = float(env["FLIGHT_HOME_LON"])
    except (KeyError, ValueError):
        return None
    # Swap this for a GPSLocation(fallback=HardcodedLocation(lat, lon)) once
    # a GPS sensor is wired up -- nothing below this point needs to change,
    # since it only ever calls .get() on whatever LocationProvider it's given.
    return HardcodedLocation(lat, lon)


def _format_ago(seconds):
    if seconds < 60:
        return f"Updated {seconds}s ago"
    return f"Updated {seconds // 60}m ago"


def _format_speed(knots):
    if knots is None:
        return "—"
    return f"{round(knots * flight_client.KNOTS_TO_KMH)} km/h"


def _format_direction(heading):
    return flight_client.compass_point(heading) or "—"


def _format_altitude(feet):
    if feet is None:
        return "—"
    return f"{int(feet)} ft"


def _format_route(origin, destination):
    origin = origin or "—"
    destination = destination or "—"
    return f"{origin} → {destination}"


def _truncate(ctx, text, font_size, width):
    ctx.font_size = font_size
    lines = utils.wrap_text(ctx, text, font_size, width)
    return lines[0] if lines else text


async def _noop():
    pass


class FlightTrackerApp(app.App):
    def __init__(self):
        super().__init__()
        self.buttons = Buttons(self)

        env = _load_env(_ENV_PATH)
        self.location = _build_location(env)

        try:
            self.radius_km = float(env.get("FLIGHT_RADIUS_KM", "50"))
        except ValueError:
            self.radius_km = 50.0

        try:
            self.refresh_seconds = int(env.get("FLIGHT_REFRESH_SECONDS", "60"))
        except ValueError:
            self.refresh_seconds = 60

        self.feed_base_url = env.get("FLIGHT_FEED_URL") or flight_client.DEFAULT_FEED_URL

        self.flight = None
        self.status = (
            "Set FLIGHT_HOME_LAT/LON in .env" if self.location is None else "Loading…"
        )
        self.dirty = True
        self.last_updated = None
        self._tick_accum = 0

    async def _fetch_nearest(self, lat, lon):
        """Fetch the feed and return the nearest flight (or None), retrying
        a few times if a response comes back with no usable flight entries.
        See _FEED_EMPTY_RETRIES above for why that's not necessarily "no
        planes nearby". Raises on a non-200 response or a request error --
        the caller (_refresh) treats that as distinct from a clean empty
        result, since it shouldn't bump last_updated.
        """
        url = flight_client.feed_url(lat, lon, self.radius_km, self.feed_base_url)

        for attempt in range(_FEED_EMPTY_RETRIES + 1):
            response = await async_helpers.unblock(
                requests.get, _noop, url,
                headers=flight_client.FEED_HEADERS, timeout=10,
            )
            try:
                if response.status_code != 200:
                    raise RuntimeError(f"FR24 error {response.status_code}")
                feed = response.json()
            finally:
                response.close()

            flight = flight_client.find_nearest(feed, lat, lon)
            if flight is not None or attempt == _FEED_EMPTY_RETRIES:
                return flight

            self.status = f"Fetching… (retry {attempt + 1})"
            self.dirty = True
            await asyncio.sleep(_FEED_RETRY_DELAY_SECONDS)

    async def _refresh(self):
        lat, lon = self.location.get()

        try:
            if not wifi.status():
                self.status = "Connecting to WiFi…"
                self.dirty = True
                wifi.connect()
                await wifi.async_wait()

            self.status = "Fetching…"
            self.dirty = True
            self.flight = await self._fetch_nearest(lat, lon)
            self.last_updated = time.ticks_ms()
            self.status = None if self.flight else "No planes nearby"
        except Exception as e:
            self.status = f"Error: {e}"

        self.dirty = True

    async def background_task(self):
        if self.location is None:
            return

        while True:
            await self._refresh()
            await asyncio.sleep(self.refresh_seconds)

    def update(self, delta):
        # No per-stop cycling like tfl_bus_times (there's only ever one
        # "nearest plane"), so CANCEL keeps the badge-wide default of
        # exiting the app rather than being repurposed.
        if self.buttons.pressed(BUTTON_TYPES["CANCEL"]):
            self.buttons.clear()
            self.minimise()
            return False
        if self.last_updated is not None:
            self._tick_accum += delta
            if self._tick_accum >= 1000:
                self._tick_accum = 0
                self.dirty = True
        if self.dirty:
            self.dirty = False
            return True
        return False

    def draw(self, ctx):
        ctx.save()
        ctx.rgb(0.02, 0.05, 0.08).rectangle(-120, -120, 240, 240).fill()
        ctx.text_align = ctx.CENTER

        ctx.rgb(0.4, 0.75, 1).font_size = 16
        ctx.move_to(0, -95).text("Nearest Plane")

        if self.status:
            ctx.rgb(1, 1, 1).font_size = 20
            ctx.move_to(0, 0).text(self.status)
        else:
            flight = self.flight

            ctx.rgb(1, 1, 1).font_size = 24
            ctx.move_to(0, -68).text(flight["label"])

            airline = flight["airline_icao"] or "—"
            aircraft = flight["aircraft_type"] or "—"
            ctx.rgb(0.8, 0.8, 0.8).font_size = 14
            ctx.move_to(0, -48).text(f"{airline} · {aircraft}")

            ctx.rgb(0.9, 0.9, 0.9).font_size = 20
            ctx.move_to(0, -22).text(_format_route(flight["origin"], flight["destination"]))

            ctx.rgb(0.24, 0.88, 0.54).font_size = 22
            ctx.move_to(0, 8).text(f"{flight['distance_km']:.1f} km")

            speed = _format_speed(flight["ground_speed_kt"])
            direction = _format_direction(flight["heading"])
            ctx.rgb(1, 1, 1).font_size = 15
            ctx.move_to(0, 32).text(f"{speed} · {direction}")

            ctx.rgb(0.6, 0.6, 0.6).font_size = 13
            ctx.move_to(0, 54).text(_format_altitude(flight["altitude_ft"]))

        if self.last_updated is not None:
            elapsed = time.ticks_diff(time.ticks_ms(), self.last_updated) // 1000
            ctx.rgb(0.5, 0.5, 0.5).font_size = 13
            ctx.move_to(0, 100).text(_format_ago(elapsed))

        ctx.restore()
