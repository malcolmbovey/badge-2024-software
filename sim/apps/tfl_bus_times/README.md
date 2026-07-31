# Bus Times (tfl_bus_times)

Shows live TfL bus arrivals for one or more bus stops on the badge screen,
and turns the outer LEDs red when a bus is due to leave soon so you know to
head out without having to check the screen.

## Features

- Polls the [TfL Unified API](https://api.tfl.gov.uk/) `StopPoint/Arrivals`
  endpoint for the next departures at a bus stop.
- Supports multiple stops — cycle between them with the **LEFT**/**RIGHT**
  buttons. Only the stop currently on screen is polled; switching stops
  fetches immediately rather than waiting for the next refresh.
- Lights the outer LEDs red when a bus for the *currently displayed* stop is
  due within a configurable time window (e.g. "leave now to catch it"),
  overriding the normal LED pattern until the window passes.
- Specific routes can be excluded from the red-LED check (e.g. a route you
  don't actually want to catch from that stop).
- **CANCEL** exits the app.

## Setup

Copy `.env.example` to `.env` in this directory and fill in your stop(s):

```
cp .env.example .env
```

`.env` is gitignored — your stop IDs and API key stay local and are never
committed.

### Configuration keys

| Key | Required | Default | Description |
|---|---|---|---|
| `TFL_STOP_IDS` | yes* | — | Comma-separated list of TfL StopPoint IDs to monitor, each optionally followed by `:Label` to override the displayed name, e.g. `490013474N:Home,490013474S:Work`. |
| `TFL_STOP_ID` | yes* | — | Legacy single-stop key. Used only if `TFL_STOP_IDS` is unset. |
| `TFL_APP_KEY` | no | *(none)* | TfL API key from the [API portal](https://api-portal.tfl.gov.uk/). Not required for light use of the public endpoint, but avoids rate-limiting. |
| `TFL_REFRESH_SECONDS` | no | `30` | How often to re-poll the currently displayed stop. |
| `TFL_URGENT_MIN_MINUTES` | no | `7` | Lower bound of the "leave now" window, in minutes until departure. |
| `TFL_URGENT_MAX_MINUTES` | no | `10` | Upper bound of the "leave now" window, in minutes until departure. |
| `TFL_EXCLUDED_ROUTES` | no | *(none)* | Comma-separated route/line names to ignore when deciding whether to light the LEDs red. |

*At least one of `TFL_STOP_IDS` or `TFL_STOP_ID` must be set, or the app
shows "Set TFL_STOP_IDS in .env" and does nothing.

Find a stop's ID by searching
`https://api.tfl.gov.uk/StopPoint/Search/<stop name>`, or from a stop's page
on [tfl.gov.uk/plan-a-journey](https://tfl.gov.uk/plan-a-journey/). A
physical stop (e.g. "The North Star") is a group with one StopPoint ID per
direction/bay — the group response's `children` list gives each one's
`naptanId` and `stopLetter`.

## Controls

On the TwentyTwentySix frontboard, the two top buttons cycle between stops
and the bottom-left button exits — deliberately not the badge-wide default
of "top-left button exits", since that would put cycling and quitting right
next to each other.

| Button | Frontboard position | Action |
|---|---|---|
| RIGHT | Top-right | Cycle to the next configured stop (wraps around). |
| CANCEL | Top-left | Cycle to the previous configured stop (wraps around). |
| LEFT | Bottom-left | Exit the app. |

Cycling is a no-op with only one stop configured.

## Code walkthrough (`app.py`)

### Module-level helpers

- **`_load_env(path)`** — hand-rolled `.env` parser (`KEY=value` lines,
  `#` comments, quote-stripping). There's no dotenv library available in
  MicroPython, hence a few lines instead of a dependency.
- **`_parse_stops(env)`** — turns `TFL_STOP_IDS` (or the legacy
  `TFL_STOP_ID`) into a list of `{"id": ..., "label": ...}` dicts, one per
  configured stop, preserving list order.
- **`_format_eta(seconds)`** / **`_format_ago(seconds)`** — turn raw second
  counts from the API/clock into the "5 min" / "Due" and "Updated 12s ago"
  strings shown on screen.
- **`_truncate(ctx, text, font_size, width)`** — wraps text at the given
  width and keeps only the first line, so long stop/destination names don't
  overflow the round display.
- **`_noop()`** — passed to `async_helpers.unblock` as the "cancel" callback
  for in-flight HTTP requests; this app never needs to cancel a fetch early.

### `TflBusTimesApp`

State is centred on "whichever stop is currently displayed" — there's no
per-stop cache; switching stops resets `departures`/`status`/`last_updated`
and triggers a fresh fetch for the new stop.

- **`__init__`** — loads `.env`, parses the stop list and numeric/set
  config (each numeric field falls back to its default on a bad value
  rather than crashing), and sets up initial "Loading…" state for the first
  configured stop.
- **`_arrivals_url(stop_id)`** — builds the TfL Arrivals endpoint URL for a
  given stop, appending `app_key` if configured.
- **`_switch_stop(direction)`** — advances `stop_index` by `direction`
  (`+1`/`-1`), wrapping via `%`. No-ops if fewer than two stops are
  configured. Resets the on-screen state to "Loading…" for the new stop,
  clears the urgent LEDs (so they don't show red for the *old* stop while
  the new one hasn't been checked yet), and sets `_fetch_requested` so the
  background loop wakes up and fetches immediately instead of waiting out
  the rest of `refresh_seconds`.
- **`_paint_leds_red()`** / **`_set_leds_urgent(urgent)`** — LED control.
  `_set_leds_urgent` emits `PatternDisable`/`PatternEnable` on the eventbus
  so this app's red LEDs aren't fought over by the badge's normal pattern
  generator, and is a no-op if the urgent state hasn't changed.
- **`_refresh()`** — the actual network fetch for the current stop, run
  from `background_task`. Ensures wifi is connected, fetches arrivals,
  keeps the soonest 3 departures, and recomputes the urgent-LED state from
  them. Captures `target_index`/`stop_id` *before* the `await` and checks
  `self.stop_index != target_index` after it: since a fetch can take a
  while and the user can switch stops mid-fetch (`_switch_stop` runs
  synchronously from `update()`), this guards against a slow response for
  a stop the user has since navigated away from overwriting the new stop's
  display or LEDs.
- **`background_task()`** — runs for the lifetime of the app (started by
  the app framework regardless of focus). Loops: refresh, then sleep out
  `refresh_seconds` in 1-second steps, repainting the LEDs red on every
  step while urgent (the pattern generator's enable/disable is handled
  asynchronously elsewhere and can otherwise race with this app's LED
  writes, leaving stale frames — repainting each second self-corrects any
  such race), and breaking out of the wait early if `_fetch_requested` was
  set by a stop switch. Exits immediately if no stops are configured.
- **`update(delta)`** — per-frame input/redraw-decision handling. Button
  roles are intentionally swapped from the badge-wide default (see
  Controls above): LEFT (physically bottom-left) clears urgent LEDs and
  minimises the app, while RIGHT and CANCEL (physically the two top
  buttons, edge-triggered via `Buttons.pressed` so holding one doesn't
  repeat-cycle) call `_switch_stop` forward/backward. A 1-second
  accumulator marks the display dirty periodically so the "Updated Ns ago"
  text keeps ticking over even with no new data. Returns whether a redraw
  is needed.
- **`draw(ctx)`** — renders the header (stop label/name, or "Next buses" if
  neither is known yet), then either the current `status` message (e.g.
  "Loading…", "No buses due", an error) or up to 3 departures as
  `line — eta` plus destination, and finally the "Updated Ns ago" footer.
