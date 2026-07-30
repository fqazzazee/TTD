#!/usr/bin/env python3
"""
Checks that need no terminal.

    $ python3 selftest.py

Three things worth guarding: every map traces into a clean route, the layout
finds a sane arrangement at any plausible window size, and the rules produce a
game that can actually be lost — a tower defense you cannot lose is a screensaver.
"""

from __future__ import annotations

import array
import math
import random
import sys
from types import SimpleNamespace

import audio
import render
import theme as T
from content import (BUILDINGS, ENEMIES, MAPS, MODES, SPEEDS, build_wave,
                     is_boss_wave, menace)
from game import PATH_CHARS, WAVE, Game, load_map

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


# ---------------------------------------------------------------------------
print("maps")
for name, art in MAPS:
    grid, path = load_map(art)
    h, w = len(grid), len(grid[0])
    marked = sum(row.count(c) for row in grid for c in PATH_CHARS)
    ragged = len({len(r) for r in art.strip("\n").split("\n")}) > 1
    check(len(path) == marked and not ragged, f"{name:11s} {w}x{h}",
          f"path {len(path)} cells, {sum(r.count('.') for r in grid)} buildable")


# ---------------------------------------------------------------------------
print("\nlayout")
sizes = [(len(load_map(a)[0]), len(load_map(a)[0][0])) for _, a in MAPS]
smallest = min(sizes)
need_w, need_h = render.smallest_need(*smallest)
check(render.plan(need_h, need_w, *smallest) is not None,
      "smallest map fits its own stated minimum", f"{need_w}x{need_h}")
check(render.plan(need_h - 1, need_w, *smallest) is None,
      "one row short is correctly refused")
for rows, cols in ((24, 80), (30, 120), (50, 200), (16, 60)):
    lay = render.plan(rows, cols, *smallest)
    check(lay is not None, f"{cols}x{rows} playable",
          f"cell_w={lay.cell_w} {'sidebar' if lay.wide else 'compact'}" if lay else "")
big = max(sizes)
lay = render.plan(40, 160, *big)
check(lay is not None and lay.wide and lay.cell_w == 2,
      "a roomy window gets the full-width board with a sidebar")


# ---------------------------------------------------------------------------
print("\nrules")


GUN, GEN = 0, 3


def simulate(mode, art, name, towers_max, seed=1, cap_waves=40, upgrade=False):
    """Play a whole run headlessly with a crude auto-builder.

    It buys a generator whenever the grid is short and a gun otherwise — the
    dumbest strategy that still respects the power system, which makes it a
    useful floor for balance rather than a ceiling.
    """
    random.seed(seed)
    g = Game(mode, name, art)
    dt = 1 / 30
    adjacent = [(y, x) for y in range(g.h) for x in range(g.w)
                if not g.is_path(y, x) and any(
                    0 <= p < g.h and 0 <= q < g.w and g.is_path(p, q)
                    for p, q in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)))]
    ground = [(y, x) for y in range(g.h) for x in range(g.w) if not g.is_path(y, x)]
    guns = 0
    while not g.over and g.wave <= cap_waves:
        if g.state == "BUILD":
            gun, gen = BUILDINGS[GUN], BUILDINGS[GEN]
            if g.supply - g.draw < gun.tiers[0].power and g.gold >= gen.cost:
                g.selected = GEN
                for _ in range(60):                 # a 2x2 needs a real gap
                    g.cy, g.cx = random.choice(ground)
                    if g.can_place(g.cy, g.cx, gen):
                        g.build()
                        break
            elif upgrade and guns >= towers_max and g.gold >= 150 and g.buildings:
                g.cy, g.cx = random.choice(list(g.buildings))
                g.upgrade()
            elif guns < towers_max and g.gold >= gun.cost:
                g.cy, g.cx = random.choice(adjacent)
                g.selected = GUN
                if g.build() == "build":
                    guns += 1
            g.timer = min(g.timer, 0.4)             # fast-forward the quiet phases
        g.update(dt)
    return g


classic = MODES[0]
name, art = MAPS[2]
g = simulate(classic, art, name, towers_max=0)
check(g.state == "LOST" and g.wave <= 4, "an undefended base falls quickly",
      f"wave {g.wave}")

reached = []
for cap in (4, 10, 24):
    g = simulate(classic, art, name, towers_max=cap)
    reached.append(g.wave)
check(reached == sorted(reached) and reached[0] < reached[-1],
      "more towers survive longer", " < ".join(map(str, reached)))

# Path length varies four-fold across the map sizes; creep speed is scaled to
# compensate, so a given defense should fare roughly alike everywhere.
spread = []
for name, art in MAPS:
    spread.append(simulate(classic, art, name, towers_max=12, seed=5).wave)
check(max(spread) - min(spread) <= 8, "difficulty is comparable across maps",
      " ".join(f"{n}:{w}" for (n, _), w in zip(MAPS, spread)))

for mode in MODES:
    name, art = MAPS[2]
    g = simulate(mode, art, name, towers_max=14, seed=3)
    ended = "won" if g.state == "WON" else f"lost on wave {g.wave}"
    check(g.over, f"{mode.name:11s} reaches an ending", ended)

# The speed dial must only buy the player time, never an advantage: the same
# defense should reach roughly the same wave however fast the battle is run.
def at_speed(step):
    random.seed(9)
    g = Game(classic, MAPS[4][0], MAPS[4][1])
    g.speed_step = step
    g.gold = 5000
    for y, x in ((1, 6), (5, 20), (8, 30), (1, 26), (5, 8), (8, 14)):
        g.cy, g.cx, g.selected = y, x, 0
        g.build()
    for y, x in ((1, 14), (5, 34)):        # keep the grid fed
        g.cy, g.cx, g.selected = y, x, 3
        g.build()
    while not g.over and g.wave <= 12:
        g.timer = min(g.timer, 0.4)
        g.update(1 / 30)
    return g.wave, g.lives


slow, fast = at_speed(0), at_speed(len(SPEEDS) - 1)
check(abs(slow[0] - fast[0]) <= 1 and abs(slow[1] - fast[1]) <= 3,
      "speed dial does not change the outcome",
      f"x1 -> wave {slow[0]}, {slow[1]} lives   "
      f"x{SPEEDS[-1]:g} -> wave {fast[0]}, {fast[1]} lives")


# Gauntlet is the only mode you can finish, so the victory branch needs a win
# to be reachable at all — otherwise nobody ever sees the triumph screen.
gauntlet = next(m for m in MODES if m.target)
g = simulate(gauntlet, MAPS[5][1], MAPS[5][0], towers_max=200, seed=2, upgrade=True)
check(g.state == "WON", "Gauntlet is winnable with a serious defense",
      f"{len(g.buildings)} buildings, wave {g.wave}, {g.lives} lives left")


# ---------------------------------------------------------------------------
print("\npower, footprints and marks")

g = Game(classic, MAPS[4][0], MAPS[4][1])
gun, frost, cannon, gen = BUILDINGS
check(g.supply == classic.power and g.draw == 0,
      "a run starts on its mode's grid capacity", f"{g.supply} units")

# Footprints: a Cannon needs 2x2 of clear grass, a Gun a single cell.
spot = next((y, x) for y in range(g.h) for x in range(g.w)
            if g.can_place(y, x, cannon))
g.gold, g.selected = 9999, 2
g.cy, g.cx = spot
check(g.build() == "build" and len(g.plots) == 4,
      "a Cannon stands on four cells", f"anchor {spot}")
check(not g.can_place(spot[0], spot[1], gun) and g.at(spot[0], spot[1] + 1) is not None,
      "its whole footprint is occupied, not just the anchor")
g.selected = 0
g.cy, g.cx = spot
check(g.build() == "deny", "nothing else fits inside it")

# A big footprint slides to fit. Reading the cursor as the footprint's
# top-left corner refuses good ground the moment you stand at the bottom or
# right edge of a clearing, which is the "no room even though there is room"
# complaint. Every cell that some clear 2x2 can cover must be buildable, and
# the block that lands must actually cover the cell you were standing on.
base = Game(classic, MAPS[4][0], MAPS[4][1])
rescued = refused = 0
for y in range(base.h):
    for x in range(base.w):
        spot = base.site(y, x, cannon)
        if spot is None:
            refused += 1
            continue
        if not base.can_place(y, x, cannon):
            rescued += 1                     # only fits by sliding up or left
        probe = Game(classic, MAPS[4][0], MAPS[4][1])
        probe.gold, probe.selected = 9999, 2
        probe.cy, probe.cx = y, x
        if probe.build() != "build" or (y, x) not in probe.plots:
            refused = -1
            break
check(refused >= 0 and rescued > 0,
      "a Cannon builds from any cell a clear 2x2 can cover",
      f"{rescued} cells only reachable by sliding the block")

# ...and the ghost you see is the ground you get: site() is what both the
# renderer and build() ask, so the preview can never lie about where it lands.
gfit = Game(classic, MAPS[4][0], MAPS[4][1])
gfit.gold, gfit.selected = 9999, 2
slid = next((y, x) for y in range(gfit.h) for x in range(gfit.w)
            if gfit.site(y, x, cannon) and not gfit.can_place(y, x, cannon))
gfit.cy, gfit.cx = slid
seen = gfit.site(*slid, cannon)
gfit.build()
check(gfit.at(*slid) is not None and (gfit.at(*slid).y, gfit.at(*slid).x) == seen,
      "the previewed anchor and the built anchor agree",
      f"cursor {slid} -> anchor {seen}")

# Refusal is still real when the ground genuinely is not there.
gtight = Game(classic, MAPS[4][0], MAPS[4][1])
gtight.gold, gtight.selected = 9999, 2
onpath = next((y, x) for y in range(gtight.h) for x in range(gtight.w)
              if gtight.is_path(y, x))
gtight.cy, gtight.cx = onpath
check(gtight.build() == "deny" and gtight.site(*onpath, cannon) is None,
      "a Cannon still refuses ground with no clear 2x2 touching it",
      f"road cell {onpath}")

# Power: drawing more than the grid supplies browns the defense out.
g2 = Game(classic, MAPS[4][0], MAPS[4][1])
g2.gold = 9999
placed = 0
for y in range(g2.h):
    for x in range(g2.w):
        if placed < 12 and g2.can_place(y, x, gun):
            g2.cy, g2.cx, g2.selected = y, x, 0
            g2.build()
            placed += 1
check(g2.short_of_power and g2.power_ratio < 1.0,
      "twelve guns on a ten-unit grid brown out",
      f"draw {g2.draw} vs supply {g2.supply}, ratio {g2.power_ratio:.2f}")
spot = next((y, x) for y in range(g2.h) for x in range(g2.w)
            if g2.can_place(y, x, gen))
g2.cy, g2.cx, g2.selected = spot[0], spot[1], 3
g2.build()
check(not g2.short_of_power and g2.power_ratio == 1.0,
      "one generator clears it", f"supply now {g2.supply}")

# Marks: three of them, each dearer and hungrier than the last.
for spec in BUILDINGS:
    costs = [t.cost for t in spec.tiers]
    powers = [abs(t.power) for t in spec.tiers]
    check(len(spec.tiers) == 3 and costs == sorted(costs) and powers == sorted(powers),
          f"{spec.name:10s} has three rising marks",
          f"${costs} power {powers}")

# Upgrades buy power and reach, never more ground: a building walled in on
# every side must still be able to reach mk3.
gboxed = Game(classic, MAPS[4][0], MAPS[4][1])
gboxed.gold = 100000
for spec, idx in ((gun, 0), (frost, 1), (cannon, 2), (gen, 3)):
    spot = next((y, x) for y in range(gboxed.h) for x in range(gboxed.w)
                if gboxed.can_place(y, x, spec))
    gboxed.cy, gboxed.cx, gboxed.selected = spot[0], spot[1], idx
    gboxed.build()
    b = gboxed.at(*spot)
    before = sorted(b.cells())
    for y in range(gboxed.h):                    # leave it no free grass at all
        for x in range(gboxed.w):
            if gboxed.can_place(y, x, gun) and any(
                    abs(y - cy) <= 1 and abs(x - cx) <= 1 for cy, cx in before):
                gboxed.cy, gboxed.cx, gboxed.selected = y, x, 0
                gboxed.build()
    gboxed.cy, gboxed.cx = spot
    steps = [gboxed.upgrade(), gboxed.upgrade()]
    check(steps == ["upgrade", "upgrade"] and b.level == 3
          and sorted(b.cells()) == before,
          f"{spec.name:10s} reaches mk3 boxed in, on the same ground",
          f"{spec.foot} and {len(before)} cells at every mark")

# Frost paints the ground it slows, and a bigger mark paints more of it.
g3 = Game(classic, MAPS[4][0], MAPS[4][1])
g3.gold = 9999
spot = next((y, x) for y in range(g3.h) for x in range(g3.w)
            if g3.can_place(y, x, frost))
g3.cy, g3.cx, g3.selected = spot[0], spot[1], 1
g3.build()
area1, slow1 = len(g3.chill), min(s for _, s in g3.chill.values())
g3.upgrade()
area2, slow2 = len(g3.chill), min(s for _, s in g3.chill.values())
g3.upgrade()
area3, slow3 = len(g3.chill), min(s for _, s in g3.chill.values())
check(area1 < area2 < area3 and slow1 > slow2 > slow3,
      "each Frost mark chills more ground, harder",
      f"cells {area1}/{area2}/{area3}  slow {slow1}/{slow2}/{slow3}")
check(g3.buildings[spot].tier.power == frost.tiers[2].power,
      "and the upgrades really took",
      f"drawing {g3.buildings[spot].tier.power} at mk{g3.buildings[spot].level}")

# A creep standing in the field is actually slowed.
g3.state = "WAVE"
g3.queue, g3.wave_total = ["grunt"], 1
g3.update(0.01)
creep = g3.enemies[0]
while creep.dist < len(g3.path) - 2 and creep.chill >= 1.0:
    g3.update(1 / 30)
    if not g3.enemies:
        break
check(creep.chill < 1.0, "and a creep crossing it slows down",
      f"speed multiplier {creep.chill:.2f}")


# ---------------------------------------------------------------------------
print("\nthe enemy")

# Every creep has a face at every rank, in both glyph sets, and the faces are
# distinct — a rank that looks identical to the one below it says nothing.
# Each face is a gait, and no frame of it may be blank or double-width.
for key in ENEMIES:
    uni, asc = T.UNICODE_MENACE.get(key), T.ASCII_MENACE.get(key)
    boss = key == "warlord"
    frames = [f for gait in (uni or ()) + (asc or ()) for f in gait]
    check(uni is not None and asc is not None and len(uni) == len(asc) == 3
          and all(len(f) == 1 and f.strip() for f in frames)
          and (boss or (len({g[0] for g in uni} | {g[0] for g in asc}) == 6)),
          f"{ENEMIES[key].name:8s} has three faces in both glyph sets",
          f"{' '.join('/'.join(g) for g in uni or ())}   "
          f"{' '.join('/'.join(g) for g in asc or ())}")

# The gait advances with distance covered, not with wall time: a creep held in
# a frost field must visibly slow its step, and a paused game must stand still.
# Theme.creep only ever reads self.m, so a stub stands in for a real terminal.
faces = SimpleNamespace(m=T.UNICODE_MENACE)
walked = [T.Theme.creep(faces, "grunt", 0, d / 10) for d in range(40)]
steps = [a for a, b in zip(walked, walked[1:]) if a != b]
check(len(set(walked)) == 2 and len(steps) == int(4 / T.STRIDE) - 1
      and T.Theme.creep(faces, "grunt", 0, 0.0)
      == T.Theme.creep(faces, "grunt", 0, 0.0),
      "a creep's step follows the ground it covers, not the clock",
      f"{T.STRIDE} cells per frame, {len(steps) + 1} frames across 4 cells")

# Ranks and gaits are clamped, so no creep can ever be drawn as an exception.
check(T.Theme.creep(faces, "grunt", 9, 0.0) == T.UNICODE_MENACE["grunt"][2][0]
      and T.Theme.creep(faces, "grunt", -3, 0.0) == T.UNICODE_MENACE["grunt"][0][0],
      "a rank outside the three clamps to the nearest one")

# Menace is read off the health a wave carries, so it escalates in every mode
# and never goes backwards.
for mode in MODES:
    ranks = [menace(mode.hp_growth ** (w - 1)) for w in range(1, 26)]
    first = {r: next((w + 1 for w, v in enumerate(ranks) if v == r), None)
             for r in (1, 2)}
    check(ranks[0] == 0 and ranks == sorted(ranks) and ranks[-1] == 2,
          f"{mode.name:10s} escalates from recruits to elites",
          f"veterans at wave {first[1]}, elites at wave {first[2]}")

# The roster actually turns up: every type appears by the wave it promises,
# and Warlords keep to their cadence rather than arriving every wave.
seen: dict[str, int] = {}
bosses = []
for w in range(1, 31):
    for key in build_wave(MODES[0], w)[0]:
        seen.setdefault(key, w)
    if is_boss_wave(w):
        bosses.append(w)
check(all(seen.get(k) == spec.from_wave for k, spec in ENEMIES.items()),
      "every creep first appears on the wave it advertises",
      "  ".join(f"{ENEMIES[k].name} w{v}" for k, v in sorted(seen.items())))
check(bosses == [12, 17, 22, 27] and
      build_wave(MODES[0], 12)[0].index("warlord") == 0,
      "Warlords come every fifth wave, and walk in last",
      f"waves {bosses}")

# What spawns wears the wave's rank.
gr = Game(MODES[0], MAPS[4][0], MAPS[4][1])
gr.wave = 14
gr.queue, gr.hp_mult = build_wave(gr.mode, gr.wave)
gr.wave_total, gr.state, gr.spawn_at = len(gr.queue), WAVE, gr.clock
gr.update(0.1)
check(gr.menace == 2 and gr.enemies and all(e.rank == 2 for e in gr.enemies),
      "creeps spawn wearing the rank of their wave",
      f"wave {gr.wave} carries hp x{gr.hp_mult:.1f}, so its ranks walk in elite")


# The index on the game screen: every creep, always in roster order, and in a
# window with no room the entries furthest from turning up drop out first.
# Theme.creep and the glyph tables are all the row builder really needs.
class StubTheme:
    m, g = T.UNICODE_MENACE, T.UNICODE_GLYPHS
    creep = T.Theme.creep

    def ink(self, *a, **k):
        return 0


stub = StubTheme()
gidx = Game(MODES[0], MAPS[4][0], MAPS[4][1])
gidx.state, gidx.queue, gidx.wave_total = WAVE, ["grunt"] * 4 + ["runner"], 5
full = render._enemy_rows(stub, gidx, 0, 0)
names = [r[1][0].strip() for r in full]
check(names == [s.name for s in ENEMIES.values()],
      "the index lists every creep in the game, in one fixed order",
      "  ".join(names))
check(full[0][2][0] == "x4" and full[1][2][0] == "x1"
      and full[3][2][0] == "w9+" and full[4][2][0] == "w12+",
      "and marks each one coming, met or still to come",
      " ".join(r[2][0] for r in full))

tight = render._enemy_rows(stub, gidx, 0, 0, budget=3)
kept = [r[1][0].strip() for r in tight]
check(len(tight) == 3 and kept == [n for n in names if n in kept]
      and {"Grunt", "Runner"} <= set(kept),
      "a short window keeps what is walking and drops the distant ones",
      "  ".join(kept))
check(render._enemy_rows(stub, gidx, 0, 0, budget=0) == [],
      "and no room at all drops the panel rather than overflowing it")
check(len(render._enemy_strip(stub, gidx)) == 2 * len(ENEMIES),
      "the compact HUD gets the same index on one line")


# ---------------------------------------------------------------------------
print("\nsound")

# Every tune parses, makes a noise, and leaves headroom. A tune that clips is
# worse than no music at all through a laptop speaker.
for name, tune in audio.TUNES.items():
    pcm = array.array("h")
    pcm.frombytes(audio.render_tune(tune))
    peak = max(abs(v) for v in pcm)
    secs = len(pcm) / audio.RATE
    check(3.0 < secs < 20.0 and 3000 < peak < 30000,
          f"{name:7s} bakes into a loop that plays and does not clip",
          f"{secs:.1f}s, peak {peak / 32767:.0%} of full scale")

check(audio.note_hz("A4") == 440.0 and abs(audio.note_hz("A3") - 220.0) < 1e-9
      and abs(audio.note_hz("C5") - 523.25) < 0.01,
      "the tracker's notes land on the right frequencies")

# The typewriter is one baked loop, not one process per keystroke. A quote is
# a few hundred characters; a few hundred processes is a fork bomb.
clicks = array.array("h")
clicks.frombytes(audio.render_clicks())
peak = max(abs(v) for v in clicks)
strikes, since = 0, -audio.RATE            # a hit after 40ms of quiet is a strike
for i, v in enumerate(clicks):
    if abs(v) > peak * 0.25 and i - since > 0.04 * audio.RATE:
        strikes, since = strikes + 1, i
rate = strikes / (len(clicks) / audio.RATE)
check(abs(len(clicks) / audio.RATE - audio.TYPE_SECONDS) < 0.1
      and 5000 < peak < 25000 and abs(rate - audio.TYPE_RATE) < 3.0,
      "the typewriter bakes into one loop of clatter",
      f"{audio.TYPE_SECONDS:.0f}s, {strikes} strikes = {rate:.1f} a second, "
      f"peak {peak / 32767:.0%} of full scale")

# Every channel the game asks for must resolve to something bakeable, or a
# screen quietly plays nothing and nobody finds out until they hear it.
wanted = {"menu", "build", "battle", "siege", "typewriter"}
check(wanted <= set(audio.TUNES) | {"typewriter"},
      "every loop the game asks for has something behind it",
      " ".join(sorted(wanted)))

# Silence is a complete stand-in: anything the game asks of Audio it can ask
# of Silence, or a machine with no player crashes at the first cue.
# The voice: whatever the system says, dragged down into the cellar. A steady
# tone in makes the effect measurable — the pitch must fall by the stated
# amount, the line must get correspondingly longer, and it must not clip.
tone = array.array("h", [int(12000 * math.sin(2 * math.pi * 200 * i / 16000))
                         for i in range(16000)])
deep = array.array("h")
deep.frombytes(audio.demonise(tone, 16000))


def crossings(samples):
    return sum(1 for i in range(1, len(samples))
               if (samples[i - 1] < 0) != (samples[i] < 0))


ratio = (crossings(deep) / len(deep)) / (crossings(tone) / len(tone))
peak = max(abs(v) for v in deep)
check(abs(len(deep) / len(tone) - 1 / audio.VOICE_DROP) < 0.02
      and abs(ratio - audio.VOICE_DROP) < 0.06
      and abs(peak / 32767 - audio.VOICE_PEAK) < 0.03,
      "the announcer's voice drops into the cellar without clipping",
      f"{12 * math.log2(audio.VOICE_DROP):.1f} semitones, "
      f"{len(deep) / len(tone):.2f}x as long, peak {peak / 32767:.0%}")

check(audio.demonise(array.array("h"), 16000) == b"",
      "and an empty line is not a crash")

quiet = audio.Silence()
check(all(hasattr(quiet, m) for m in
          ("play", "music", "typing", "say", "toggle", "toggle_music",
           "close", "on", "music_on", "speaker")),
      "Silence answers everything Audio does")

# Announcements: two of them, and neither is a shout into an empty room.
import ttd                                            # noqa: E402
gsay = Game(MODES[0], MAPS[4][0], MAPS[4][1])
gsay.wave = 12
lines = {cue: ttd.announce(gsay, cue) for cue in
         ("wave", "boss", "build", "leak", "boom", "cleared")}
check(lines["wave"].startswith("Wave 12") and "Warlord" in lines["wave"]
      and lines["boss"] == "Warlord."
      and not any(lines[c] for c in ("build", "leak", "boom", "cleared")),
      "only the wave and the Warlord are ever announced",
      f"wave 12 -> {lines['wave']!r}")
gsay.wave = 7
check(ttd.announce(gsay, "wave") == "Wave 7." ,
      "an ordinary wave is announced without the drama")


# ---------------------------------------------------------------------------
print("\npausing")

gp = Game(MODES[0], MAPS[4][0], MAPS[4][1])
gp.state, gp.queue, gp.wave_total, gp.hp_mult = WAVE, ["grunt"] * 5, 5, 1.0
for _ in range(30):
    gp.update(1 / 30)
before = (gp.clock, [e.dist for e in gp.enemies], len(gp.queue))
gp.paused = True
for _ in range(90):                                  # three seconds of nothing
    gp.update(1 / 30)
after = (gp.clock, [e.dist for e in gp.enemies], len(gp.queue))
check(before == after, "a paused battle does not move",
      f"{len(gp.enemies)} creeps frozen mid-road, clock at {gp.clock:.2f}s")
gp.paused = False
gp.update(1 / 30)
check(gp.clock > before[0], "and starts again when you let it")


# ---------------------------------------------------------------------------
print()
if failures:
    print(f"{len(failures)} failed: " + ", ".join(failures))
    sys.exit(1)
print("all good")
