#!/usr/bin/env python3
"""
Checks that need no terminal.

    $ python3 selftest.py

Things worth guarding: every map on disk traces into a clean route, the ground
under it behaves, the layout finds a sane arrangement at any plausible window
size, the campaign holds together, and the rules produce a game that can
actually be lost — a tower defense you cannot lose is a screensaver.
"""

from __future__ import annotations

import array
import math
import os
import random
import sys
import tempfile
from types import SimpleNamespace

import audio
import editor as ED
import render
import story
import terrain as TR
import theme as T
from content import (BUILDINGS, ENEMIES, MODES, SPEEDS, build_wave,
                     is_boss_wave, menace)
from game import WAVE, Game
from terrain import MAPS, PATH_CHARS

failures: list[str] = []


def check(ok: bool, label: str, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(label)


# ---------------------------------------------------------------------------
print("maps")
check(not TR.LOAD_ERRORS, "every map file on disk loads",
      "; ".join(TR.LOAD_ERRORS) or f"{len(MAPS)} found in " +
      ", ".join(TR.map_dirs()))
check(len(MAPS) >= 10, "there are at least ten battlefields", str(len(MAPS)))
for m in MAPS:
    marked = sum(row.count(c) for row in m.grid for c in PATH_CHARS)
    ragged = len({len(r) for r in m.art.strip("\n").split("\n")}) > 1
    check(len(m.path) == marked and not ragged and m.open_ground > 60,
          f"{m.name:14s} {m.w}x{m.h}",
          f"road {len(m.path)} cells, {m.open_ground} buildable, "
          f"{len(m.census())} kinds of ground")


# ---------------------------------------------------------------------------
print("\nground")

# Every letter of the map alphabet has to survive the round trip from the file
# to a colour on the screen, or a hand-edited map paints holes.
missing = [t.ink for t in TR.TERRAIN.values()
           if t.ink not in T.RICH_TERRAIN or t.ink not in T.BASIC_TERRAIN
           or t.ink not in T.UNICODE_GROUND or t.ink not in T.ASCII_GROUND]
missing += [f"road_{r}" for r in TR.ROADS
            if f"road_{r}" not in T.RICH_TERRAIN
            or f"road_{r}" not in T.UNICODE_GROUND
            or f"road_{r}" not in T.ASCII_GROUND]
check(not missing, "every terrain and road has glyphs and a colour ramp",
      ", ".join(missing) or f"{len(TR.TERRAIN)} terrains, {len(TR.ROADS)} roads")
check(all(len(v[1]) == 3 for v in T.RICH_TERRAIN.values())
      and all(len(T.UNICODE_GROUND[k]) == len(T.ASCII_GROUND[k])
              for k in T.UNICODE_GROUND),
      "each ramp has three rungs and both glyph sets agree on length")

# Relief is the whole 2.5D illusion: a cliff must put the ground below and to
# the right of it into shadow, and take the light on its own near edge.
cliff = TR.relief(["....", ".^^.", "....", "...."])
check(cliff[1][1] == 2 and cliff[2][1] == 0 and cliff[1][3] == 0,
      "high ground catches the light and throws a shadow down-right",
      f"peak {cliff[1][1]}, below it {cliff[2][1]}, beside it {cliff[1][3]}")
flat = TR.relief(["." * 24] * 6)
tones = {v for row in flat for v in row}
check(tones == {0, 1, 2} and sum(row.count(1) for row in flat) > 24 * 6 * 0.6,
      "flat ground is mottled, not striped",
      f"{sum(row.count(1) for row in flat)} of {24 * 6} cells left plain")

# A map with no road at all, a forked one, and one with no base: all three are
# complaints with a location in them, not tracebacks.
broken = {
    "forked": "S##\n.#.\n..E",
    "no base": "S##\n..#\n...",
    "stranded": "S#E\n...\n#..",
}
told = {}
for label, art in broken.items():
    try:
        TR.MapDef(name=label, art=art)
        told[label] = ""
    except TR.MapError as exc:
        told[label] = str(exc)
check(all(told.values()), "a broken map is refused with a reason",
      "  ·  ".join(f"{k}: {v}" for k, v in told.items()))

# The file format has to survive a round trip, or the editor eats headers.
one = MAPS[3]
again = TR.parse(one.to_text(), source="round-trip")
check(again.name == one.name and again.grid == one.grid
      and again.road == one.road and again.brief == one.brief,
      "a map written back out reads in identically", one.name)

# Terrain decides where you can build, and the high ground pays for the walk.
gterr = Game(MODES[0], next(m for m in MAPS if m.name == "Hastings"))
wet = [(y, x) for y in range(gterr.h) for x in range(gterr.w)
       if gterr.ground(y, x).name == "marsh"]
high = [(y, x) for y in range(gterr.h) for x in range(gterr.w)
        if gterr.ground(y, x).name == "hill"]
gun = BUILDINGS[0]
check(wet and high and not any(gterr.can_place(y, x, gun) for y, x in wet),
      "nothing is built in a marsh", f"{len(wet)} marsh cells refused")
flatspot = next((y, x) for y in range(gterr.h) for x in range(gterr.w)
                if gterr.can_place(y, x, gun) and not gterr.high_ground(y, x, gun))
ridge = next((y, x) for y, x in high if gterr.can_place(y, x, gun))
gterr.gold, gterr.selected = 9999, 0
gterr.cy, gterr.cx = ridge
gterr.build()
gterr.cy, gterr.cx = flatspot
gterr.build()
up, down = gterr.at(*ridge), gterr.at(*flatspot)
check(gterr.reach(up) > gterr.reach(down),
      "a gun on the ridge outranges the same gun on the flat",
      f"{gterr.reach(up):.2f} vs {gterr.reach(down):.2f}")

# ...and a footprint half on the hill gets nothing, because half a battery on
# the high ground is a battery in the valley.
cannon = BUILDINGS[2]
edge = next(((y, x) for y in range(gterr.h - 1) for x in range(gterr.w - 1)
             if gterr.can_place(y, x, cannon)
             and any(gterr.ground(y + dy, x + dx).high
                     for dy in range(2) for dx in range(2))
             and any(not gterr.ground(y + dy, x + dx).high
                     for dy in range(2) for dx in range(2))), None)
check(edge is None or gterr.high_ground(*edge, cannon) == 0,
      "a footprint straddling the crest gets no bonus",
      f"anchor {edge}" if edge else "no straddling 2x2 on this map")


# ---------------------------------------------------------------------------
print("\nthe campaign")

chaps = story.chapters()
check(len(chaps) == len(story.CHAPTERS) and len(chaps) >= 10,
      "every chapter has its battlefield installed",
      f"{len(chaps)} battles")
check([c.order for c in chaps[:5]] == ["I", "II", "III", "IV", "V"]
      and chaps[-1].order == story.numeral(len(chaps)),
      "chapters are numbered by where they sit, not by hand",
      f"last is {chaps[-1].order}")
check(all(c.mode.target for c in chaps),
      "every chapter ends — a campaign of endless waves is a treadmill")
check(len({c.map_name for c in chaps}) == len(chaps),
      "no battle is fought twice")

# The one thing a campaign must not do is lock the player out of it.
prog = story.Progress(os.path.join(tempfile.gettempdir(), "ttd-selftest.json"))
prog.cleared, prog.best = set(), {}
check(prog.unlocked(chaps[0]) and not prog.unlocked(chaps[1])
      and prog.next_chapter() is chaps[0],
      "a fresh campaign opens on its first battle and no further")
prog.record(chaps[0], won=True, score=1234)
check(prog.unlocked(chaps[1]) and prog.is_cleared(chaps[0])
      and prog.best[chaps[0].map_name] == 1234
      and prog.next_chapter() is chaps[1],
      "winning one opens the next and remembers the score")
prog.record(chaps[1], won=False, score=99)
check(not prog.is_cleared(chaps[1]) and prog.unlocked(chaps[1]),
      "losing takes nothing away")
for c in chaps:
    prog.record(c, won=True, score=1)
check(prog.complete and all(prog.unlocked(c) for c in chaps),
      "and the whole campaign can be finished", f"{prog.done} battles")
os.remove(prog.path)


# ---------------------------------------------------------------------------
print("\nthe editor")

sheet = ED.Sheet("Scratch")
check(sheet.check() and sheet.w == ED.NEW_W,
      "a blank sheet has no road yet, and says so", sheet.check())
sheet.paint(0, 0, "S")
for x in range(1, sheet.w):
    sheet.paint(0, x, "#")
sheet.paint(0, sheet.w - 1, "E")
check(not sheet.check(), "a road drawn from edge to edge validates",
      sheet.check() or f"{sheet.w} cells")

# Painting a second entrance moves the first rather than leaving two behind —
# which is also how you drag either end of the road somewhere else.
sheet.paint(0, 5, "S")
counts = (sum(r.count("S") for r in sheet.rows()),
          sum(r.count("E") for r in sheet.rows()))
sheet.paint(0, 0, "S")
check(counts == (1, 1) and not sheet.check(),
      "there is only ever one entrance and one base",
      f"S x{counts[0]}, E x{counts[1]} after moving the entrance")

before = sheet.rows()
sheet.paint(4, 4, "T")
check(sheet.restore() and sheet.rows() == before, "undo puts it back")
check(sheet.resize(2, 1) and sheet.w == ED.NEW_W + 2
      and sheet.h == ED.NEW_H + 1 and len(set(map(len, sheet.rows()))) == 1,
      "resizing keeps every row the same length",
      f"{sheet.w}x{sheet.h}")
check(not sheet.resize(-500, 0) and sheet.w == ED.NEW_W + 2,
      "and refuses to shrink a map out of existence")
check(sheet.filename() == "scratch.map",
      "the file it would write is named after the battle", sheet.filename())
round_trip = TR.parse(ED.Sheet.load(MAPS[2]).to_text())
check(round_trip.grid == MAPS[2].grid and round_trip.name == MAPS[2].name,
      "opening a shipped map in the editor and writing it back changes nothing",
      MAPS[2].name)


# ---------------------------------------------------------------------------
print("\nlayout")
sizes = [(m.h, m.w) for m in MAPS]
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


def simulate(mode, field_, towers_max, seed=1, cap_waves=40, upgrade=False):
    """Play a whole run headlessly with a crude auto-builder.

    It buys a generator whenever the grid is short and a gun otherwise — the
    dumbest strategy that still respects the power system, which makes it a
    useful floor for balance rather than a ceiling.
    """
    random.seed(seed)
    g = Game(mode, field_)
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
g = simulate(classic, MAPS[2], towers_max=0)
check(g.state == "LOST" and g.wave <= 4, "an undefended base falls quickly",
      f"wave {g.wave}")

reached = []
for cap in (4, 10, 24):
    g = simulate(classic, MAPS[2], towers_max=cap)
    reached.append(g.wave)
check(reached == sorted(reached) and reached[0] < reached[-1],
      "more towers survive longer", " < ".join(map(str, reached)))

# Path length varies four-fold across the map sizes; creep speed is scaled to
# compensate, so a given defense should fare roughly alike everywhere.
spread = []
for m in MAPS:
    spread.append(simulate(classic, m, towers_max=12, seed=5).wave)
check(max(spread) - min(spread) <= 10, "difficulty is comparable across maps",
      " ".join(f"{m.name.split()[0][:6]}:{w}" for m, w in zip(MAPS, spread)))

for mode in MODES:
    g = simulate(mode, MAPS[2], towers_max=14, seed=3)
    ended = "won" if g.state == "WON" else f"lost on wave {g.wave}"
    check(g.over, f"{mode.name:11s} reaches an ending", ended)

# The speed dial must only buy the player time, never an advantage: the same
# defense should reach roughly the same wave however fast the battle is run.
def at_speed(step):
    random.seed(9)
    g = Game(classic, MAPS[4])
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
g = simulate(gauntlet, MAPS[3], towers_max=200, seed=2, upgrade=True)
check(g.state == "WON", "Gauntlet is winnable with a serious defense",
      f"{len(g.buildings)} buildings, wave {g.wave}, {g.lives} lives left")


# ---------------------------------------------------------------------------
print("\npower, footprints and marks")

g = Game(classic, MAPS[4])
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
base = Game(classic, MAPS[4])
rescued = refused = 0
for y in range(base.h):
    for x in range(base.w):
        spot = base.site(y, x, cannon)
        if spot is None:
            refused += 1
            continue
        if not base.can_place(y, x, cannon):
            rescued += 1                     # only fits by sliding up or left
        probe = Game(classic, MAPS[4])
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
gfit = Game(classic, MAPS[4])
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
gtight = Game(classic, MAPS[4])
gtight.gold, gtight.selected = 9999, 2
onpath = next((y, x) for y in range(gtight.h) for x in range(gtight.w)
              if gtight.is_path(y, x))
gtight.cy, gtight.cx = onpath
check(gtight.build() == "deny" and gtight.site(*onpath, cannon) is None,
      "a Cannon still refuses ground with no clear 2x2 touching it",
      f"road cell {onpath}")

# Power: drawing more than the grid supplies browns the defense out.
g2 = Game(classic, MAPS[4])
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
gboxed = Game(classic, MAPS[4])
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
g3 = Game(classic, MAPS[4])
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
gr = Game(MODES[0], MAPS[4])
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
gidx = Game(MODES[0], MAPS[4])
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
gsay = Game(MODES[0], MAPS[4])
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

gp = Game(MODES[0], MAPS[4])
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
