# Halloween

A party slideshow for the Tildagon: spooky ASCII art, animated vector scenes
and dripping/glowing text, with the LED ring lit in Halloween colours to match
each scene. Wave the badge (or press the confirm button) for a jump scare.

## Scenes

Each scene shows for 8 seconds, then the app moves on to the next one.

| Scene | LEDs |
|---|---|
| ASCII pumpkin | candle flicker |
| Jack-o'-lantern (flickering face) | candle flicker |
| Floating ghost (follows the badge's tilt) | ghostly green breathing |
| ASCII ghost | ghostly green breathing |
| Bats across the moon | purple with lightning flashes |
| ASCII skull | green/purple chase |
| "Happy Halloween" with drips | orange/purple/green chase |
| Spider on a thread | purple with red eyes running round the ring |
| ASCII bat | purple with lightning flashes |
| ASCII cat | orange/purple/green chase |
| "Trick or Treat?" glow | orange/purple/green chase |
| ASCII tombstone | purple pulse |

## Controls

| Button | Action |
|---|---|
| RIGHT / LEFT | next / previous scene |
| CONFIRM | jump scare ("BOO!" plus a red/white strobe) |
| UP | cycle LED brightness through 5 levels (starts at level 2 to save battery) |
| DOWN | pause or resume the slideshow |
| CANCEL | exit (gives the LEDs back to the badge's pattern) |

**Shake:** a sharp jolt (more than about 6 m/s² away from the running average)
also triggers the jump scare. There is a 3-second cooldown so that one shake
only triggers one scare.

## Notes

- The badge only has the proportional EMF Camp font, so `AsciiArt` centres each
  character in a fixed-width cell to fake a monospace layout. Art lives in
  `art.py`. Keep each piece within about 12 lines x 24 columns.
- To add a scene, add an entry to `build_scenes()` in `app.py`. A scene needs
  `draw(ctx, t, app)` and an `led(t, i, n)` effect that returns `(r, g, b)` in
  0–255. Brightness scaling is applied afterwards.
- Simulator: the `ctx.text()` fake in `sim/fakes/ctx.py` now escapes `\` and `"`.
  Before this fix, backslashes were silently dropped from the ASCII art. The
  real badge was not affected.
