import asyncio
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

# os.path isn't available on-device (only in the desktop sim), so derive the
# app's own directory from __file__ with plain string ops instead.
_APP_DIR = __file__.rsplit("/", 1)[0] if "/" in __file__ else "."
_ENV_PATH = _APP_DIR + "/.env"
_URGENT_SECONDS = 8 * 60


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


def _format_eta(seconds):
    minutes = seconds // 60
    return "Due" if minutes <= 0 else f"{minutes} min"


def _format_ago(seconds):
    if seconds < 60:
        return f"Updated {seconds}s ago"
    return f"Updated {seconds // 60}m ago"


def _truncate(ctx, text, font_size, width):
    ctx.font_size = font_size
    lines = utils.wrap_text(ctx, text, font_size, width)
    return lines[0] if lines else text


async def _noop():
    pass


class TflBusTimesApp(app.App):
    def __init__(self):
        super().__init__()
        self.buttons = Buttons(self)

        env = _load_env(_ENV_PATH)
        self.stop_id = env.get("TFL_STOP_ID") or None
        self.app_key = env.get("TFL_APP_KEY") or None
        try:
            self.refresh_seconds = int(env.get("TFL_REFRESH_SECONDS", "30"))
        except ValueError:
            self.refresh_seconds = 30

        self.departures = []
        self.stop_name = None
        self.status = "Set TFL_STOP_ID in .env" if not self.stop_id else "Loading…"
        self.dirty = True
        self._leds_red = False
        self.last_updated = None
        self._tick_accum = 0

    def _arrivals_url(self):
        url = f"https://api.tfl.gov.uk/StopPoint/{self.stop_id}/Arrivals"
        if self.app_key:
            url += f"?app_key={self.app_key}"
        return url

    def _set_leds_urgent(self, urgent):
        if urgent == self._leds_red:
            return
        self._leds_red = urgent
        if urgent:
            eventbus.emit(PatternDisable())
            for i in range(tildagonos.leds.n):
                tildagonos.leds[i] = (255, 0, 0)
            tildagonos.leds.write()
        else:
            eventbus.emit(PatternEnable())

    async def background_task(self):
        if not self.stop_id:
            return

        while True:
            try:
                if not wifi.status():
                    self.status = "Connecting to WiFi…"
                    self.dirty = True
                    wifi.connect()
                    await wifi.async_wait()

                self.status = "Fetching…"
                self.dirty = True
                response = await async_helpers.unblock(
                    requests.get, _noop, self._arrivals_url(), timeout=10
                )
                try:
                    if response.status_code == 200:
                        predictions = response.json()
                        predictions.sort(key=lambda p: p.get("timeToStation", 0))
                        self.departures = predictions[:3]
                        self.last_updated = time.ticks_ms()
                        if predictions:
                            self.stop_name = predictions[0].get("stationName")
                        self.status = None if predictions else "No buses due"
                        self._set_leds_urgent(
                            bool(predictions)
                            and predictions[0].get("timeToStation", 9999) < _URGENT_SECONDS
                        )
                    else:
                        self.status = f"TfL API error {response.status_code}"
                        self._set_leds_urgent(False)
                finally:
                    response.close()
            except Exception as e:
                self.status = f"Error: {e}"
                self._set_leds_urgent(False)

            self.dirty = True
            await asyncio.sleep(self.refresh_seconds)

    def update(self, delta):
        if self.buttons.get(BUTTON_TYPES["CANCEL"]):
            self.buttons.clear()
            self._set_leds_urgent(False)
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
        ctx.rgb(0, 0, 0.15).rectangle(-120, -120, 240, 240).fill()
        ctx.text_align = ctx.CENTER

        header = _truncate(ctx, self.stop_name, 18, 190) if self.stop_name else "Next buses"
        ctx.rgb(0.6, 0.8, 1).font_size = 18
        ctx.move_to(0, -95).text(header)

        if self.status:
            ctx.rgb(1, 1, 1).font_size = 20
            ctx.move_to(0, 0).text(self.status)
        else:
            y = -55
            for departure in self.departures:
                line_name = departure.get("lineName", "?")
                eta = _format_eta(departure.get("timeToStation", 0))
                destination = _truncate(
                    ctx, departure.get("destinationName", ""), 16, 190
                )

                ctx.rgb(1, 1, 1).font_size = 22
                ctx.move_to(0, y).text(f"{line_name} — {eta}")
                ctx.rgb(0.8, 0.8, 0.8).font_size = 16
                ctx.move_to(0, y + 20).text(destination)
                y += 52

        if self.last_updated is not None:
            elapsed = time.ticks_diff(time.ticks_ms(), self.last_updated) // 1000
            ctx.rgb(0.5, 0.5, 0.5).font_size = 13
            ctx.move_to(0, 100).text(_format_ago(elapsed))

        ctx.restore()
