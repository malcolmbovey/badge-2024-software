import math
import random
import time

import app
from events.input import BUTTON_TYPES, Buttons
from system.eventbus import eventbus
from system.patterndisplay.events import PatternDisable, PatternEnable
from tildagonos import tildagonos

from . import art

try:
    import imu
except ImportError:
    imu = None

TWO_PI = 2 * math.pi

SCENE_SECONDS = 8
SCARE_SECONDS = 1.6
SHAKE_THRESHOLD = 6  # m/s^2 jump away from the running average
SHAKE_COOLDOWN = 3
OVERLAY_SECONDS = 1.5
LED_INTERVAL_MS = 40
BRIGHTNESS_LEVELS = (0.05, 0.15, 0.3, 0.6, 1.0)
DEFAULT_BRIGHTNESS = 1

# LED colours (0-255)
ORANGE = (255, 90, 0)
PURPLE = (120, 0, 200)
GREEN = (40, 255, 20)
GHOST_GREEN = (120, 255, 140)
RED = (255, 0, 0)
WHITE = (255, 255, 255)


# ---------------------------------------------------------------- LED effects
# Each effect is fn(t, i, n) -> (r, g, b) for LED i of n at time t seconds.


def _scale(c, k):
    return (c[0] * k, c[1] * k, c[2] * k)


def _flicker(t, i):
    # Smooth candle-ish wobble from two incommensurate sines per LED.
    return 0.65 + 0.2 * math.sin(t * 7 + i * 1.3) + 0.15 * math.sin(t * 13.1 + i * 2.7)


def led_candle(t, i, n):
    k = _flicker(t, i)
    return (255 * k, (70 + 50 * k) * k, 0)


def led_ghost(t, i, n):
    k = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 2 + i * TWO_PI / n))
    return _scale(GHOST_GREEN, k)


def led_lightning(t, i, n):
    phase = t % 5
    if phase < 0.08 or 0.18 < phase < 0.26:
        return WHITE
    return _scale(PURPLE, 0.4 + 0.3 * math.sin(t + i))


def _chase(colours, speed):
    def effect(t, i, n):
        pos = (i + t * speed) % n
        band = int(pos * len(colours) / n)
        frac = (pos * len(colours) / n) % 1
        return _scale(colours[band], 0.3 + 0.7 * frac)

    return effect


def _pulse(colour, speed):
    def effect(t, i, n):
        return _scale(colour, 0.2 + 0.8 * (0.5 + 0.5 * math.sin(t * speed)))

    return effect


led_toxic = _chase((GREEN, PURPLE), 6)
led_party = _chase((ORANGE, PURPLE, GREEN), 4)
led_purple_pulse = _pulse(PURPLE, 2.5)


def led_spider(t, i, n):
    # Purple ring with a red "eye" pair scuttling round.
    head = int(t * 5) % n
    if i == head or i == (head + 1) % n:
        return RED
    return _scale(PURPLE, 0.35)


def led_scare(t, i, n):
    return WHITE if int(t * 14) % 2 else RED


# ---------------------------------------------------------------- draw helpers


def _bg(ctx, r, g, b):
    ctx.rgb(r, g, b).rectangle(-120, -120, 240, 240).fill()


def _circle(ctx, x, y, r):
    ctx.arc(x, y, r, 0, TWO_PI, False).fill()


def _ellipse(ctx, x, y, rx, ry):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(1, ry / rx)
    ctx.arc(0, 0, rx, 0, TWO_PI, False).fill()
    ctx.restore()


def _poly(ctx, points):
    ctx.move_to(*points[0])
    for p in points[1:]:
        ctx.line_to(*p)
    ctx.close_path()
    ctx.fill()


def _text(ctx, s, x, y, size):
    ctx.font_size = size
    ctx.move_to(x, y).text(s)


class AsciiArt:
    """ASCII art laid out on a fixed grid.

    The badge only has the proportional EMF Camp font, so each character is
    centred in its own cell to fake a monospace layout.
    """

    def __init__(self, text, max_w=180, max_h=150):
        lines = text.strip("\n").split("\n")
        cols = max(len(line) for line in lines)
        self.size = min(max_w / (cols * 0.6), max_h / (len(lines) * 1.15), 22)
        cw = self.size * 0.6
        lh = self.size * 1.15
        x0 = -cols * cw / 2 + cw / 2
        y0 = -len(lines) * lh / 2 + lh * 0.8
        self.height = len(lines) * lh
        self.cells = [
            (x0 + c * cw, y0 + r * lh, ch)
            for r, line in enumerate(lines)
            for c, ch in enumerate(line)
            if ch != " "
        ]

    def draw(self, ctx, dx=0, dy=0):
        ctx.font_size = self.size
        for x, y, ch in self.cells:
            ctx.move_to(x + dx, y + dy).text(ch)


# ---------------------------------------------------------------- scenes
# Each scene draws itself for time t (seconds since the scene started) and
# names its LED effect. `app` gives access to the IMU tilt.


class AsciiScene:
    def __init__(self, text, fg, bg, led, caption=None, flicker=False, dy=0):
        self.art = AsciiArt(text, max_h=130 if caption else 150)
        self.fg = fg
        self.bg = bg
        self.led = led
        self.caption = caption
        self.flicker = flicker
        self.dy = dy

    def draw(self, ctx, t, app):
        _bg(ctx, *self.bg)
        k = 0.7 + 0.3 * _flicker(t, 0) if self.flicker else 1
        ctx.rgb(self.fg[0] * k, self.fg[1] * k, self.fg[2] * k)
        offset = -12 if self.caption else 0
        self.art.draw(ctx, dy=offset + self.dy)
        if self.caption:
            ctx.rgb(1, 0.45, 0)
            _text(ctx, self.caption, 0, self.art.height / 2 + 8, 18)


class LanternScene:
    led = staticmethod(led_candle)

    def draw(self, ctx, t, app):
        _bg(ctx, 0.08, 0, 0.12)
        # Pumpkin: overlapping ellipses for the ribs.
        ctx.rgb(0.75, 0.3, 0)
        _ellipse(ctx, -35, 10, 45, 60)
        _ellipse(ctx, 35, 10, 45, 60)
        ctx.rgb(0.95, 0.42, 0)
        _ellipse(ctx, 0, 10, 55, 65)
        ctx.rgb(0.2, 0.45, 0.1).rectangle(-6, -68, 12, 20).fill()

        # Candle-lit face.
        k = _flicker(t, 0)
        ctx.rgb(1, 0.6 + 0.35 * k, 0.15 * k)
        _poly(ctx, [(-38, -8), (-14, -8), (-26, -30)])
        _poly(ctx, [(14, -8), (38, -8), (26, -30)])
        _poly(ctx, [(-6, 10), (6, 10), (0, 0)])
        mouth = [(-45, 22)]
        for j in range(7):
            x = -45 + (j + 1) * 90 / 7
            mouth.append((x - 90 / 14, 30 if j % 2 else 36))
            mouth.append((x, 22))
        mouth += [(40, 45), (0, 55), (-40, 45)]
        _poly(ctx, mouth)


class GhostScene:
    led = staticmethod(led_ghost)

    def draw(self, ctx, t, app):
        _bg(ctx, 0, 0.03, 0.1)
        ctx.rgb(0.95, 0.95, 0.75)
        _circle(ctx, 60, -60, 22)
        ctx.rgb(0, 0.03, 0.1)
        _circle(ctx, 70, -66, 20)

        x = max(-40, min(40, app.tilt * 6)) + 8 * math.sin(t * 1.3)
        y = 10 * math.sin(t * 2)
        ctx.rgb(0.9, 1, 0.92)
        ctx.arc(x, y - 20, 45, math.pi, TWO_PI, False)
        ctx.line_to(x + 45, y + 45)
        # Wavy hem.
        waves = 5
        w = 90 / waves
        for j in range(waves):
            bx = x + 45 - j * w
            lift = 10 * math.sin(t * 6 + j)
            ctx.quad_to(bx - w / 2, y + 60 + lift, bx - w, y + 45)
        ctx.close_path()
        ctx.fill()

        ctx.rgb(0, 0, 0)
        _ellipse(ctx, x - 16, y - 25, 8, 12)
        _ellipse(ctx, x + 16, y - 25, 8, 12)
        _ellipse(ctx, x, y + 5, 9, 12 + 4 * math.sin(t * 3))

        if t % 4 > 2:
            ctx.rgb(0.5, 1, 0.5)
            _text(ctx, "BOO!", 0, 95, 30)


class BatScene:
    led = staticmethod(led_lightning)

    def draw(self, ctx, t, app):
        phase = t % 5
        flash = phase < 0.08 or 0.18 < phase < 0.26
        if flash:
            _bg(ctx, 0.85, 0.85, 1)
        else:
            _bg(ctx, 0.1, 0, 0.18)
            ctx.rgb(1, 0.85, 0.4)
            _circle(ctx, 0, 0, 60)

        ctx.rgb(0, 0, 0)
        for j, (speed, y, size) in enumerate(
            ((40, -40, 1.2), (55, 20, 0.9), (32, 55, 0.7))
        ):
            x = ((t * speed + j * 90) % 320) - 160
            self._bat(ctx, x, y + 6 * math.sin(t * 3 + j), size, t * 12 + j)

    def _bat(self, ctx, x, y, s, wing_t):
        flap = 12 * math.sin(wing_t) * s
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(s, s)
        _poly(
            ctx,
            [
                (0, -6),
                (4, -10),
                (6, -4),
                (18, -10 - flap),
                (34, -4 - flap),
                (26, 2),
                (16, 0),
                (8, 6),
                (0, 10),
                (-8, 6),
                (-16, 0),
                (-26, 2),
                (-34, -4 - flap),
                (-18, -10 - flap),
                (-6, -4),
                (-4, -10),
            ],
        )
        ctx.restore()


class SpiderScene:
    led = staticmethod(led_spider)

    def draw(self, ctx, t, app):
        _bg(ctx, 0.04, 0, 0.06)
        # Corner cobweb.
        ctx.rgb(0.5, 0.5, 0.55)
        ctx.line_width = 1
        for a in range(5):
            ang = a * math.pi / 8
            ctx.move_to(-120, -120).line_to(
                -120 + 110 * math.cos(ang), -120 + 110 * math.sin(ang)
            )
        for r in (30, 55, 80):
            ctx.move_to(-120 + r, -120)
            for a in range(1, 5):
                ang = a * math.pi / 8
                ctx.line_to(-120 + r * math.cos(ang), -120 + r * math.sin(ang))
        ctx.stroke()

        sx = 20
        sy = -10 + 45 * math.sin(t * 0.9)
        ctx.move_to(sx, -120).line_to(sx, sy).stroke()

        ctx.line_width = 3
        ctx.rgb(0.15, 0.1, 0.15)
        wiggle = 4 * math.sin(t * 8)
        for side in (-1, 1):
            for j in range(4):
                ky = sy - 6 + j * 7
                ctx.move_to(sx, ky)
                ctx.line_to(
                    sx + side * 24, ky - 12 + j * 4 + wiggle * (1 if j % 2 else -1)
                )
                ctx.line_to(sx + side * 34, ky + 8 + j * 4)
        ctx.stroke()
        ctx.rgb(0.2, 0.12, 0.2)
        _ellipse(ctx, sx, sy + 12, 16, 20)
        _circle(ctx, sx, sy - 8, 10)
        ctx.rgb(1, 0, 0)
        _circle(ctx, sx - 4, sy - 9, 2.5)
        _circle(ctx, sx + 4, sy - 9, 2.5)


class DripTextScene:
    def __init__(self, lines, colour, led):
        self.lines = lines
        self.colour = colour
        self.led = led

    def draw(self, ctx, t, app):
        _bg(ctx, 0.05, 0, 0.08)
        r, g, b = self.colour
        size = 34
        top = -len(self.lines) * size / 2 + size * 0.75
        for j, line in enumerate(self.lines):
            y = top + j * size
            ctx.rgb(r, g, b)
            _text(ctx, line, 0, y, size)
            width = ctx.text_width(line)
            # Drips fall from below each line, staggered and looping.
            for d in range(4):
                dx = -width / 2 + width * (d + 0.5) / 4
                fall = ((t * 0.6 + d * 0.37 + j * 0.21) % 1) * 30
                ctx.rgb(r * 0.8, g * 0.8, b * 0.8)
                _ellipse(ctx, dx, y + 6 + fall, 3.5 - fall / 12, 5 - fall / 10)


class GlowTextScene:
    def __init__(self, lines, colours, led):
        self.lines = lines
        self.colours = colours
        self.led = led

    def draw(self, ctx, t, app):
        _bg(ctx, 0, 0, 0)
        size = 32
        top = -len(self.lines) * size / 2 + size * 0.75
        k = 0.5 + 0.5 * math.sin(t * 3)
        for j, line in enumerate(self.lines):
            c0 = self.colours[j % len(self.colours)]
            c1 = self.colours[(j + 1) % len(self.colours)]
            ctx.rgb(*[a * k + b * (1 - k) for a, b in zip(c0, c1)])
            _text(ctx, line, 0, top + j * size, size)


def build_scenes():
    return [
        AsciiScene(art.PUMPKIN, (1, 0.5, 0), (0.05, 0, 0.05), led_candle, flicker=True),
        LanternScene(),
        GhostScene(),
        AsciiScene(art.GHOST, (0.8, 1, 0.85), (0, 0.03, 0.08), led_ghost, "Boo!"),
        BatScene(),
        AsciiScene(art.SKULL, (0.85, 0.9, 0.8), (0.05, 0, 0.08), led_toxic),
        DripTextScene(["Happy", "Halloween"], (1, 0.4, 0), led_party),
        SpiderScene(),
        AsciiScene(art.BAT, (0.75, 0.5, 1), (0.03, 0, 0.06), led_lightning),
        AsciiScene(art.CAT, (0.6, 1, 0.3), (0.03, 0, 0.05), led_party, "Hiss!"),
        GlowTextScene(
            ["Trick", "or", "Treat?"],
            ((1, 0.45, 0), (0.6, 0.2, 1), (0.3, 1, 0.2)),
            led_party,
        ),
        AsciiScene(
            art.TOMBSTONE,
            (0.7, 0.7, 0.75),
            (0.02, 0.02, 0.05),
            led_purple_pulse,
            "Rest in Pieces",
        ),
    ]


# ---------------------------------------------------------------- app


class HalloweenApp(app.App):
    def __init__(self):
        super().__init__()
        self.buttons = Buttons(self)
        self.scenes = build_scenes()
        self.index = 0
        self.scene_start = time.ticks_ms()
        self.paused = False
        self.brightness = DEFAULT_BRIGHTNESS
        self.overlay_text = None
        self.overlay_until = 0
        self.scare_until = 0
        self.scare_start = 0
        self.last_shake = 0
        self.acc_avg = None
        self.tilt = 0
        self.last_led = 0
        self.leds_owned = False
        self._held = set()

    # -- input

    def _pressed(self, name):
        # Edge-triggered read that works on older firmware without
        # Buttons.pressed().
        down = self.buttons.get(BUTTON_TYPES[name])
        if down and name not in self._held:
            self._held.add(name)
            return True
        if not down:
            self._held.discard(name)
        return False

    def _show(self, text, now):
        self.overlay_text = text
        self.overlay_until = time.ticks_add(now, int(OVERLAY_SECONDS * 1000))

    def _goto(self, step, now):
        self.index = (self.index + step) % len(self.scenes)
        self.scene_start = now

    def _scare(self, now):
        self.scare_start = now
        self.scare_until = time.ticks_add(now, int(SCARE_SECONDS * 1000))

    def _read_imu(self, now):
        if imu is None:
            return
        try:
            x, y, z = imu.acc_read()
        except OSError:
            return
        self.tilt = y
        mag = math.sqrt(x * x + y * y + z * z)
        if self.acc_avg is None:
            self.acc_avg = mag
        jolt = abs(mag - self.acc_avg)
        self.acc_avg = self.acc_avg * 0.9 + mag * 0.1
        if (
            jolt > SHAKE_THRESHOLD
            and time.ticks_diff(now, self.last_shake) > SHAKE_COOLDOWN * 1000
        ):
            self.last_shake = now
            self._scare(now)

    # -- LEDs

    def _take_leds(self):
        if not self.leds_owned:
            self.leds_owned = True
            eventbus.emit(PatternDisable())

    def _release_leds(self):
        if self.leds_owned:
            self.leds_owned = False
            eventbus.emit(PatternEnable())

    def _write_leds(self, effect, t):
        k = BRIGHTNESS_LEVELS[self.brightness]
        n = tildagonos.leds.n
        for i in range(n):
            r, g, b = effect(t, i, n)
            tildagonos.leds[i] = (
                max(0, min(255, int(r * k))),
                max(0, min(255, int(g * k))),
                max(0, min(255, int(b * k))),
            )
        tildagonos.leds.write()

    # -- frame

    def update(self, delta):
        now = time.ticks_ms()

        if self._pressed("CANCEL"):
            self.buttons.clear()
            self._held.clear()
            self._release_leds()
            self.minimise()
            return False

        self._take_leds()

        if self._pressed("RIGHT"):
            self._goto(1, now)
        if self._pressed("LEFT"):
            self._goto(-1, now)
        if self._pressed("CONFIRM"):
            self._scare(now)
        if self._pressed("UP"):
            self.brightness = (self.brightness + 1) % len(BRIGHTNESS_LEVELS)
            self._show(f"Lights {self.brightness + 1}/{len(BRIGHTNESS_LEVELS)}", now)
        if self._pressed("DOWN"):
            self.paused = not self.paused
            if not self.paused:
                self.scene_start = now
            self._show("Paused" if self.paused else "Playing", now)

        self._read_imu(now)

        if (
            not self.paused
            and time.ticks_diff(now, self.scene_start) > SCENE_SECONDS * 1000
        ):
            self._goto(1, now)

        if time.ticks_diff(now, self.last_led) >= LED_INTERVAL_MS:
            self.last_led = now
            if self._scaring(now):
                self._write_leds(
                    led_scare, time.ticks_diff(now, self.scare_start) / 1000
                )
            else:
                self._write_leds(self.scenes[self.index].led, now / 1000)

        return True

    def _scaring(self, now):
        return time.ticks_diff(self.scare_until, now) > 0

    def draw(self, ctx):
        now = time.ticks_ms()
        ctx.save()
        ctx.text_align = ctx.CENTER
        if self._scaring(now):
            self._draw_scare(ctx, time.ticks_diff(now, self.scare_start) / 1000)
        else:
            t = time.ticks_diff(now, self.scene_start) / 1000
            self.scenes[self.index].draw(ctx, t, self)
        ctx.restore()

        if time.ticks_diff(self.overlay_until, now) > 0 and self.overlay_text:
            ctx.save()
            ctx.text_align = ctx.CENTER
            ctx.rgba(0, 0, 0, 0.7).round_rectangle(-60, 78, 120, 26, 8).fill()
            ctx.rgb(1, 0.6, 0.1)
            _text(ctx, self.overlay_text, 0, 97, 18)
            ctx.restore()

        self.draw_overlays(ctx)

    def _draw_scare(self, ctx, t):
        flash = int(t * 14) % 2
        _bg(ctx, 0.6, 0, 0) if flash else _bg(ctx, 0, 0, 0)
        jx = random.randint(-6, 6)
        jy = random.randint(-6, 6)
        grow = min(1, t * 5)
        ctx.rgb(1, 1, 1) if not flash else ctx.rgb(0, 0, 0)
        _ellipse(ctx, -35 + jx, -35 + jy, 22 * grow + 1, 28 * grow + 1)
        _ellipse(ctx, 35 + jx, -35 + jy, 22 * grow + 1, 28 * grow + 1)
        ctx.rgb(1, 0, 0) if not flash else ctx.rgb(1, 1, 1)
        _circle(ctx, -35 + jx, -30 + jy, 8 * grow + 1)
        _circle(ctx, 35 + jx, -30 + jy, 8 * grow + 1)
        ctx.rgb(1, 1, 1) if not flash else ctx.rgb(1, 1, 0)
        _text(ctx, "BOO!", jx, 60 + jy, 30 + 30 * grow)


__app_export__ = HalloweenApp
