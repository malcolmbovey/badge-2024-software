import asyncio
import os
import time

import app
import async_helpers
import requests
import wifi
from app_components import utils
from events.input import BUTTON_TYPES, Buttons
from system.eventbus import eventbus
from system.patterndisplay.events import PatternDisable, PatternEnable
from tildagonos import tildagonos

from . import airlines, flight_client
from .location import HardcodedLocation

# os.path isn't available on-device (only in the desktop sim), so derive the
# app's own directory from __file__ with plain string ops instead.
_APP_DIR = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
_ENV_PATH = _APP_DIR + "/.env"
_LOGO_CACHE_DIR = _APP_DIR + "/logo_cache"

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

# Airline logo images are drawn into a box of at most this size (pixels),
# preserving aspect ratio -- FR24's logo assets are wordmarks and vary a lot
# in shape (e.g. 150x18 vs 112x45), so a fixed box would either crop or
# leave odd gaps.
_LOGO_MAX_W = 140
_LOGO_MAX_H = 26

# Same idea as tfl_bus_times' LED handling: the pattern generator app runs
# asynchronously and can race with our LED writes, leaving a stale pattern
# frame on screen. Repainting on this cadence while a colour override is
# active self-corrects any such race within a second.
_LED_REASSERT_SECONDS = 1


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


def _ensure_dir(path):
    try:
        os.mkdir(path)
    except OSError:
        pass  # already exists


def _scaled_logo_size(width, height):
    scale = min(_LOGO_MAX_W / width, _LOGO_MAX_H / height)
    return width * scale, height * scale


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

        # Set once a logo is confirmed cached for the *currently shown*
        # airline (see _ensure_logo) -- logo_airline_icao guards against
        # briefly showing a stale logo left over from the previous flight.
        self.logo_path = None
        self.logo_airline_icao = None
        self.logo_size = (None, None)

        self._led_color = None

    async def _fetch_bytes(self, url, headers, timeout):
        """GET a URL and return its raw body, or None on any failure (non-200,
        network error, timeout). Used for logo images, where a miss should
        just fall back to text rather than surface as an app-level error."""
        try:
            response = await async_helpers.unblock(
                requests.get, _noop, url, headers=headers, timeout=timeout,
            )
        except Exception:
            return None
        try:
            if response.status_code != 200:
                return None
            return response.content
        finally:
            response.close()

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

    def _set_logo(self, path, icao, width, height):
        if not width or not height:
            return
        self.logo_path = path
        self.logo_airline_icao = icao
        self.logo_size = _scaled_logo_size(width, height)
        self.dirty = True

    async def _ensure_logo(self, flight):
        """Best-effort: make sure a cached logo image exists locally for this
        flight's airline, downloading and caching it if not already present.
        Failures of any kind (no ICAO code, no network, a 404 from both
        candidate URLs, a non-PNG response) are silently swallowed -- draw()
        falls back to the airline name/code text when there's no logo.
        """
        icao = flight["airline_icao"]
        if not icao:
            return

        path = _LOGO_CACHE_DIR + "/" + icao + ".png"
        if utils.path_isfile(path):
            with open(path, "rb") as f:
                header = f.read(24)
            self._set_logo(path, icao, *flight_client.png_dimensions(header))
            return

        for url in flight_client.airline_logo_urls(icao, flight["flight_number"]):
            data = await self._fetch_bytes(url, flight_client.LOGO_HEADERS, 8)
            if data is None or not flight_client.is_png(data):
                continue

            width, height = flight_client.png_dimensions(data)
            if not width:
                continue

            _ensure_dir(_LOGO_CACHE_DIR)
            with open(path, "wb") as f:
                f.write(data)
            self._set_logo(path, icao, width, height)
            return

    def _paint_leds(self, color):
        for i in range(tildagonos.leds.n):
            tildagonos.leds[i] = color
        tildagonos.leds.write()

    def _apply_led_color(self, color):
        if color == self._led_color:
            return
        self._led_color = color
        if color is not None:
            eventbus.emit(PatternDisable())
            self._paint_leds(color)
        else:
            eventbus.emit(PatternEnable())

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
            self.flight = None

        if self.flight is not None:
            try:
                await self._ensure_logo(self.flight)
            except Exception:
                pass  # best-effort -- draw() falls back to name/code text
            self._apply_led_color(airlines.airline_color(self.flight["airline_icao"]))
        else:
            self._apply_led_color(None)

        self.dirty = True

    async def background_task(self):
        if self.location is None:
            return

        while True:
            await self._refresh()
            remaining = self.refresh_seconds
            while remaining > 0:
                if self._led_color is not None:
                    self._paint_leds(self._led_color)
                step = min(_LED_REASSERT_SECONDS, remaining)
                await asyncio.sleep(step)
                remaining -= step

    def update(self, delta):
        # No per-stop cycling like tfl_bus_times (there's only ever one
        # "nearest plane"), so CANCEL keeps the badge-wide default of
        # exiting the app rather than being repurposed.
        if self.buttons.pressed(BUTTON_TYPES["CANCEL"]):
            self.buttons.clear()
            self._apply_led_color(None)
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

    def _draw_airline(self, ctx, flight, cy):
        icao = flight["airline_icao"]
        width, height = self.logo_size
        if self.logo_path and self.logo_airline_icao == icao and width:
            ctx.image(self.logo_path, -width / 2, cy - height / 2, width, height)
            return

        name = airlines.airline_name(icao) or icao or "—"
        ctx.rgb(0.85, 0.85, 0.85).font_size = 14
        ctx.move_to(0, cy).text(name)

    def draw(self, ctx):
        ctx.save()
        ctx.rgb(0.02, 0.05, 0.08).rectangle(-120, -120, 240, 240).fill()
        ctx.text_align = ctx.CENTER

        ctx.rgb(0.4, 0.75, 1).font_size = 16
        ctx.move_to(0, -98).text("Nearest Plane")

        if self.status:
            ctx.rgb(1, 1, 1).font_size = 20
            ctx.move_to(0, 0).text(self.status)
        else:
            flight = self.flight

            ctx.rgb(1, 1, 1).font_size = 24
            ctx.move_to(0, -70).text(flight["label"])

            self._draw_airline(ctx, flight, cy=-44)

            route = _format_route(flight["origin"], flight["destination"])
            ctx.rgb(1, 1, 1).font_size = 22
            ctx.move_to(0, -10).text(route)

            ctx.rgb(0.24, 0.88, 0.54).font_size = 22
            ctx.move_to(0, 16).text(f"{flight['distance_km']:.1f} km")

            speed = _format_speed(flight["ground_speed_kt"])
            direction = _format_direction(flight["heading"])
            ctx.rgb(1, 1, 1).font_size = 15
            ctx.move_to(0, 40).text(f"{speed} · {direction}")

            aircraft = flight["aircraft_type"]
            altitude = _format_altitude(flight["altitude_ft"])
            ctx.rgb(0.6, 0.6, 0.6).font_size = 13
            ctx.move_to(0, 62).text(f"{aircraft} · {altitude}" if aircraft else altitude)

        if self.last_updated is not None:
            elapsed = time.ticks_diff(time.ticks_ms(), self.last_updated) // 1000
            ctx.rgb(0.5, 0.5, 0.5).font_size = 13
            ctx.move_to(0, 100).text(_format_ago(elapsed))

        ctx.restore()
