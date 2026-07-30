"""
Everything the player sees.

Two responsibilities, kept apart:

    Layout   works out how to fit the battlefield, the sidebar and the footer
             into whatever terminal it is handed, at whatever size, at any
             moment (terminals get resized mid-battle).

    Drawing  paints the board, the panels and the between-battle scenes.

Nothing here mutates game state; nothing in `game.py` knows this file exists.
"""

from __future__ import annotations

import curses
import math
import textwrap
import time
from dataclasses import dataclass

import game as G
from content import BUILDINGS, ENEMIES, Quote
from terrain import TERRAIN
from theme import STRIDE, Theme

# Which colour each kind of shot and its impact is painted in.
SHOT_COLOUR = {"bullet": "shot", "shell": "cannon"}

# A creep that takes this many lives is big enough to need two cells to say so.
BIG_LEAK = 6

# What the enemy index calls the wave that is forming up, by menace.
MENACE_TITLES = ("THE ENEMY", "THE ENEMY · VETERANS", "THE ENEMY · ELITES")

TOPBAR = 1          # rows above the battlefield
FOOT = 2            # message line + key hints
SIDEBAR_W = 26      # width of the right-hand panel column
SIDEBAR_H = 28      # rows the four panels want, when the window can spare them
COMPACT_H = 3       # rows of HUD when the sidebar does not fit
MIN_COMPACT_W = 46  # the compact HUD is unreadable narrower than this


# ---------------------------------------------------------------------------
# Low-level drawing helpers
# ---------------------------------------------------------------------------


def put(scr, y: int, x: int, text: str, attr: int = 0) -> None:
    """addstr that clips instead of raising — the bottom-right cell included."""
    rows, cols = scr.getmaxyx()
    if y < 0 or y >= rows or x >= cols:
        return
    if x < 0:
        text, x = text[-x:], 0
    text = text[:cols - x]
    if not text:
        return
    try:
        scr.addstr(y, x, text, attr)
    except curses.error:
        pass                       # writing the last cell always "fails"


def frags(scr, y: int, x: int, pieces, width: int) -> None:
    """Draw a row of (text, attr) fragments, truncating at `width`."""
    for text, attr in pieces:
        if width <= 0:
            return
        clipped = text[:width]
        put(scr, y, x, clipped, attr)
        x += len(clipped)
        width -= len(clipped)


def center(scr, y: int, text: str, attr: int = 0, span: int | None = None) -> None:
    cols = span if span is not None else scr.getmaxyx()[1]
    put(scr, y, max(0, (cols - len(text)) // 2), text, attr)


def bar(theme: Theme, value: float, width: int) -> str:
    """A proportional block bar, e.g. '████████░░░░'."""
    full, empty = theme.g["bar"]
    n = max(0, min(width, round(value * width)))
    return full * n + empty * (width - n)


def panel(scr, theme: Theme, y: int, x: int, w: int, title: str, rows) -> int:
    """Draw a titled box and return the row just below it."""
    tl, tr, bl, br, h, v = theme.box()
    edge = theme.ink("frame", dim=True)
    label = f" {title} " if title else ""
    top = tl + h + label + h * max(0, w - 3 - len(label)) + tr
    put(scr, y, x, top[:w], edge)
    for i, row in enumerate(rows):
        put(scr, y + 1 + i, x, v, edge)
        put(scr, y + 1 + i, x + w - 1, v, edge)
        frags(scr, y + 1 + i, x + 2, row, w - 4)   # stop clear of the right border
    put(scr, y + 1 + len(rows), x, bl + h * (w - 2) + br, edge)
    return y + len(rows) + 2


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    cell_w: int          # screen columns per board cell (2 looks square)
    wide: bool           # True when the sidebar sits beside the board
    board_y: int         # first row of the board interior
    board_x: int         # first column of the board interior
    side_x: int          # left edge of the sidebar (wide) or of the HUD
    side_y: int
    side_h: int          # rows available to the sidebar
    foot_y: int          # first of the two footer rows
    rows: int
    cols: int


def plan(rows: int, cols: int, bh: int, bw: int) -> Layout | None:
    """Best layout for a board of `bh` x `bw` cells, or None if it cannot fit.

    Preference order: a double-width board with the sidebar beside it, then a
    double-width board with the HUD underneath, then the same two at
    single-width cells. Spare vertical room is split above and below so the
    battlefield sits in the middle of a tall window rather than clinging to
    the top.
    """
    avail_h = rows - TOPBAR - FOOT
    for cell_w in (2, 1):
        board_px = bw * cell_w
        frame_h = bh + 2

        # Sidebar beside the board. The block that gets centred is whichever
        # of the two columns is taller, so their tops stay roughly level.
        if cols >= board_px + 3 + SIDEBAR_W and avail_h >= frame_h:
            block = max(frame_h, min(SIDEBAR_H, avail_h))
            top = TOPBAR + (avail_h - block) // 2
            fx = max(0, (cols - SIDEBAR_W - board_px - 2) // 2)
            return Layout(cell_w, True, top + 1 + (block - frame_h) // 2, fx + 1,
                          cols - SIDEBAR_W, top, rows - FOOT - top,
                          rows - FOOT, rows, cols)

        # HUD underneath the board.
        block_h = frame_h + COMPACT_H
        if cols >= max(board_px + 2, MIN_COMPACT_W) and avail_h >= block_h:
            top = TOPBAR + (avail_h - block_h) // 2
            fx = max(0, (cols - board_px - 2) // 2)
            return Layout(cell_w, False, top + 1, fx + 1,
                          0, top + frame_h, COMPACT_H,
                          rows - FOOT, rows, cols)
    return None


def fits(rows: int, cols: int, bh: int, bw: int) -> bool:
    return plan(rows, cols, bh, bw) is not None


def smallest_need(bh: int, bw: int) -> tuple[int, int]:
    """Minimum (cols, rows) that can display a board of this size."""
    return max(bw + 2, MIN_COMPACT_W), TOPBAR + bh + 2 + COMPACT_H + FOOT


# ---------------------------------------------------------------------------
# The battlefield
# ---------------------------------------------------------------------------


def draw_game(scr, theme: Theme, g: G.Game, lay: Layout, now: float) -> None:
    """Paint one frame. `now` is wall time — used only for things that should
    keep breathing while the game is paused, like the cursor."""
    pulse = (now * 2.5) % 1.0 < 0.5
    scr.erase()
    _topbar(scr, theme, g, lay)
    _terrain(scr, theme, g, lay)
    _cast_shadows(scr, theme, g, lay)
    _preview(scr, theme, g, lay)
    _buildings(scr, theme, g, lay)
    _creeps(scr, theme, g, lay)
    _effects(scr, theme, g, lay)
    _flight(scr, theme, g, lay)
    _cursor(scr, theme, g, lay, pulse)
    if lay.wide:
        _sidebar(scr, theme, g, lay)
    else:
        _compact(scr, theme, g, lay)
    _footer(scr, theme, g, lay)


def _topbar(scr, theme: Theme, g: G.Game, lay: Layout) -> None:
    sep = f"  {theme.g['sep']}  "
    frags(scr, 0, 1, [
        ("TTD", theme.ink("title", bold=True)),
        (sep, theme.ink("frame", dim=True)),
        (g.mode.name, theme.ink("accent")),
        (sep, theme.ink("frame", dim=True)),
        (g.map_name, theme.ink("text")),
        (f"  {g.map.when}" if g.map.when else "", theme.ink("panel", dim=True)),
    ], lay.cols - 2)

    chevrons = theme.g["arrow"] * (g.speed_step + 1)
    right = f"x{g.speed:g} {chevrons}"
    put(scr, 0, max(0, lay.cols - len(right) - 1), right,
        theme.ink("gold" if g.speed_step else "panel", bold=g.speed_step > 0))
    if g.paused:
        put(scr, 0, max(0, lay.cols - len(right) - 11), " PAUSED ",
            theme.ink("warn", bold=True))


def _screen(lay: Layout, y: int, x: int) -> tuple[int, int]:
    """Board cell -> screen coordinates of the cell's first column."""
    return lay.board_y + y, lay.board_x + x * lay.cell_w


def _ground(g: G.Game, y: int, x: int) -> str:
    """Which ground a cell sits on, so overlays don't punch holes in it."""
    if 0 <= y < g.h and 0 <= x < g.w:
        return g.map.ink(y, x)
    return "grass"


def _ring_cells(g: G.Game, cy: float, cx: float, radius: float, band: float):
    """Board cells lying on a circle — the workhorse for blasts and ranges."""
    y0, y1 = max(0, int(cy - radius - 1)), min(g.h - 1, int(cy + radius + 1))
    x0, x1 = max(0, int(cx - radius - 1)), min(g.w - 1, int(cx + radius + 1))
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if abs(math.hypot(y - cy, x - cx) - radius) <= band:
                yield y, x


def _terrain(scr, theme: Theme, g: G.Game, lay: Layout) -> None:
    """Frame plus lit ground, emitted in runs of matching colour.

    Every cell knows two things: what kind of ground it is, which picks the
    colour ramp, and which way its light falls, which picks a rung on that
    ramp. The second one is the whole illusion — the board is lit from the
    top left and never anything else, so the eye reads the differences as
    height and a flat grid of characters becomes a landscape with a wood on
    it and a river through it.

    Cells inside a frost field are painted in ice instead, whatever they are
    made of, which is the clearest possible statement of where creeps slow
    down.
    """
    tl, tr, bl, br, h, v = theme.box(heavy=True)
    edge = theme.ink("frame")
    fy, fx = lay.board_y - 1, lay.board_x - 1
    width = g.w * lay.cell_w
    put(scr, fy, fx, tl + h * width + tr, edge)
    put(scr, fy + g.h + 1, fx, bl + h * width + br, edge)

    ice = [theme.ink("chill_fg", f"chill{i}") for i in (1, 2, 3)]
    shimmer = int(g.clock * 3)
    drift = int(g.clock * 2.2)          # water and reeds, never quite still
    flake = theme.g["flake"]
    field_ = g.map

    for y in range(g.h):
        sy, sx = _screen(lay, y, 0)
        put(scr, sy, fx, v, edge)
        put(scr, sy, fx + width + 1, v, edge)

        run, run_attr, run_x = [], None, 0
        for x in range(g.w):
            mark, _ = g.chill_at(y, x)
            ink = field_.ink(y, x)
            attr = ice[mark - 1] if mark else theme.land(ink, field_.relief[y][x])
            tile = "".join(theme.tile(ink, y, x * lay.cell_w + i, drift)
                           for i in range(lay.cell_w))
            if mark:
                # A few crystals drift through the field so it looks cold
                # rather than merely blue.
                tile = "".join(
                    flake if (hash((y, x * lay.cell_w + i, shimmer)) & 15) < mark
                    else c for i, c in enumerate(tile))
            if attr != run_attr:
                if run:
                    put(scr, sy, sx + run_x, "".join(run), run_attr)
                run, run_attr, run_x = [], attr, x * lay.cell_w
            run.append(tile)
        if run:
            put(scr, sy, sx + run_x, "".join(run), run_attr)

    # The two ends of the road, so the direction of travel is never in doubt.
    for (cy, cx), glyph, fg, bg in ((g.path[0], theme.g["start"], "start_fg", "start_bg"),
                                    (g.path[-1], theme.g["base"], "base_fg", "base_bg")):
        sy, sx = _screen(lay, cy, cx)
        put(scr, sy, sx, glyph.ljust(lay.cell_w), theme.ink(fg, bg, bold=True))


def _cast_shadows(scr, theme: Theme, g: G.Game, lay: Layout) -> None:
    """Throw each building's shadow onto the ground beside it.

    Terrain gets its depth from the relief map, which is worked out once when
    the map loads and cannot know about anything the player builds later. So
    buildings cast their own, in the same direction as everything else: down
    and to the right, one cell of ground redrawn in its darkest shade. It is
    two dozen character cells a frame and it is the single thing that most
    makes a tower look like it is standing on the field rather than printed
    on it.
    """
    for b in g.buildings.values():
        fh, fw = b.spec.foot
        below = [(b.y + fh, b.x + dx + 1) for dx in range(fw)]
        beside = [(b.y + dy + 1, b.x + fw) for dy in range(fh)]
        for n, (y, x) in enumerate(below + beside):
            if not (0 <= y < g.h and 0 <= x < g.w) or (y, x) in g.plots:
                continue
            if g.chill_at(y, x)[0]:
                continue                       # ice already owns this cell
            ink = g.map.ink(y, x)
            attr = theme.land(ink, 0) | curses.A_DIM
            sy, sx = _screen(lay, y, x)
            # The shadow along the flank is a single column wide, so it reads
            # as an offset rather than as a second building.
            span = lay.cell_w if n < len(below) else 1
            put(scr, sy, sx, "".join(theme.tile(ink, y, x * lay.cell_w + i)
                                     for i in range(span)), attr)


def _preview(scr, theme: Theme, g: G.Game, lay: Layout) -> None:
    """What the selected building would do from here.

    Weapons show their reach as a ring with a sparse fill — a solid disc of
    dots buries the board, while the outline says the same thing and leaves
    the covered ground legible. A Frost tower shows its field instead, which
    is a filled area because that is literally what it paints on the map.
    """
    spot = None if g.over else g.site(g.cy, g.cx, g.spec)
    if spot is None:
        return
    tier = g.spec.tiers[0]
    fh, fw = g.spec.foot
    cy, cx = spot[0] + (fh - 1) / 2, spot[1] + (fw - 1) / 2
    dot = theme.g["dot"]

    if tier.aura > 0:
        attr = theme.ink("chill_fg", dim=True)
        for y, x in _disc(g, cy, cx, tier.aura):
            sy, sx = _screen(lay, y, x)
            put(scr, sy, sx + lay.cell_w - 1, dot, attr)
        return
    if tier.range <= 0:
        return

    # The ring drawn is the ring you get, high ground included — otherwise
    # the one place on the map where reach matters most is the one place the
    # preview lies about it.
    reach = tier.range + g.high_ground(spot[0], spot[1], g.spec)
    edge = theme.ink("range")
    inner = theme.ink("range", dim=True)
    for y, x in _disc(g, cy, cx, reach + 0.25):
        d = math.hypot(y - cy, x - cx)
        on_edge = d >= reach - 0.7
        if not on_edge and (y + x) % 2:
            continue
        sy, sx = _screen(lay, y, x)
        put(scr, sy, sx + lay.cell_w - 1, dot, edge if on_edge else inner)


def _disc(g: G.Game, cy: float, cx: float, radius: float):
    """Board cells inside a circle."""
    y0, y1 = max(0, int(cy - radius)), min(g.h - 1, int(cy + radius) + 1)
    x0, x1 = max(0, int(cx - radius)), min(g.w - 1, int(cx + radius) + 1)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            if math.hypot(y - cy, x - cx) <= radius:
                yield y, x


def _flight(scr, theme: Theme, g: G.Game, lay: Layout) -> None:
    """Shots in the air: a fading tail behind a bright head."""
    tail = theme.g["trail"]
    heads = {"bullet": theme.g["bullet"], "shell": theme.g["shell"]}
    for p in g.shots:
        colour = SHOT_COLOUR[p.kind]
        for i, (ty, tx) in enumerate(p.trail):
            y, x = round(ty), round(tx)
            sy, sx = _screen(lay, y, x)
            put(scr, sy, sx, tail[min(i, len(tail) - 1)],
                theme.over(colour, _ground(g, y, x), dim=i > 0))
        y, x = round(p.y), round(p.x)
        sy, sx = _screen(lay, y, x)
        put(scr, sy, sx, heads[p.kind],
            theme.over(colour, _ground(g, y, x), bold=True))


def _effects(scr, theme: Theme, g: G.Game, lay: Layout) -> None:
    """Impacts: a spark, a puff of frost, or a cannon blast opening outwards."""
    shades = theme.g["ring"]
    for f in g.effects:
        age = max(0.0, min(1.0, f.age(g.clock)))
        if f.kind == "spark":
            y, x = round(f.y), round(f.x)
            sy, sx = _screen(lay, y, x)
            put(scr, sy, sx, theme.g["burst"],
                theme.over("shot", _ground(g, y, x), bold=age < 0.5))
            continue

        blast = f.kind == "blast"
        # Ease out: the shockwave leaps away and then slows as it thins.
        radius = f.radius * (age ** 0.55)
        glyph = shades[min(len(shades) - 1, int(age * len(shades)))] if blast \
            else theme.g["flake"]
        colour = "cannon" if blast else "frost"
        for y, x in _ring_cells(g, f.y, f.x, radius, 0.6 if blast else 0.5):
            sy, sx = _screen(lay, y, x)
            put(scr, sy, sx, glyph,
                theme.over(colour, _ground(g, y, x), bold=age < 0.35, dim=age > 0.7))


def _slab(scr, theme: Theme, lay: Layout, b, colour: str, bg: str,
          bright: bool, ghost: bool = False) -> None:
    """Draw a building as a solid block the exact size of its footprint.

    The glyph sits on the block's lowest row and the mark number in its last
    cell, so a mk3 Cannon is unmistakably four times the Gun beside it. A
    block tall enough to have a top gets a lit lip along it: with the light
    coming from the top left, that one row of eighth-block is the difference
    between a coloured rectangle and something standing up out of the ground.
    """
    fh, fw = b.spec.foot
    span = fw * lay.cell_w
    body = theme.ink(colour, bg, dim=True)
    for dy in range(fh):
        sy, sx = _screen(lay, b.y + dy, b.x)
        put(scr, sy, sx, " " * span, body)

    lip = theme.g["lip"]
    if fh > 1 and lip:
        sy, sx = _screen(lay, b.y, b.x)
        put(scr, sy, sx, lip * span, theme.ink(colour, bg, bold=True))

    sy, sx = _screen(lay, b.y + fh - 1, b.x)
    put(scr, sy, sx + (span - 1) // 2, theme.g[b.spec.glyph],
        theme.ink(colour, bg, bold=bright))
    if b.level > 1 and not ghost:
        sy, sx = _screen(lay, b.y + fh - 1, b.x + fw - 1)
        put(scr, sy, sx + lay.cell_w - 1, str(b.level),
            theme.ink("text", bg, bold=True))


def _buildings(scr, theme: Theme, g: G.Game, lay: Layout) -> None:
    starved = g.short_of_power
    for b in g.buildings.values():
        firing = g.clock < b.flash_until
        colour = "shot" if firing else b.spec.glyph
        # Anything that draws power dims when the grid cannot feed it.
        if starved and b.tier.power > 0 and not firing:
            colour = "ghost"
        _slab(scr, theme, lay, b, colour, b.spec.glyph + "_bg", firing)


def _creep_ink(theme: Theme, g: G.Game, y: int, x: int, rank: int):
    """The background a creep is drawn on, and how to paint onto it.

    Three claims on one cell, settled in order of how much the player needs
    them: ice beats rank, rank beats the road. Frost and menace are flat
    colours from the palette; the road is terrain, and terrain is shaded, so
    the two need different doors into the theme. The caller gets back
    something it can hand a foreground colour to and stop caring which.
    """
    mark, _ = g.chill_at(y, x)
    if mark:
        return lambda fg, **kw: theme.ink(fg, f"chill{mark}", **kw)
    if rank:
        return lambda fg, **kw: theme.ink(fg, f"menace{rank}", **kw)
    ink = _ground(g, y, x)
    return lambda fg, **kw: theme.over(fg, ink, **kw)


def _hulk(scr, theme: Theme, g: G.Game, lay: Layout, e, colour: str, paint) -> None:
    """Draw the body a big creep drags along behind its head.

    A Warlord is one cell as far as the rules are concerned — she walks the
    same road as everything else — but one cell does not look like a boss.
    So the cell behind her on the road is painted as her bulk, which makes
    her two cells of presence without touching a single rule.
    """
    i = int(e.dist)
    behind = g.path[max(0, i - 1)]
    if behind == g.path[min(i, len(g.path) - 1)]:
        return                                   # still on the entrance cell
    sy, sx = _screen(lay, *behind)
    body = theme.g["hulk"]
    put(scr, sy, sx, body[int(e.dist / STRIDE) % len(body)],
        paint(colour, bold=True))


def _creeps(scr, theme: Theme, g: G.Game, lay: Layout) -> None:
    """Draw the enemy, with its rank showing.

    Three things stack up on one cell, in order of how much the player needs
    them: frost wins over rank, and being shot wins over both. What is left
    over says which wave this is — veterans and elites darken the road they
    walk on, and an elite's silhouette pulses.
    """
    blocks = theme.g["hp"]
    now = g.clock
    for e in g.enemies:
        y, x = e.pos(g.path)
        cy, cx = round(y), round(x)
        sy, sx = _screen(lay, cy, cx)
        hurt = now < e.hurt_until
        chilled = e.chill < 0.999
        paint = _creep_ink(theme, g, cy, cx, e.rank)
        colour = "warn" if hurt else ("chill_fg" if chilled else e.spec.glyph)
        if e.spec.leak >= BIG_LEAK:
            _hulk(scr, theme, g, lay, e, colour, paint)
        # A creep wading through a frost field flickers into a crystal.
        glyph = theme.g["flake"] if chilled and int(now * 7) % 2 \
            else theme.creep(e.spec.glyph, e.rank, e.dist)
        bold = e.rank < 2 or int(now * 4) % 2 == 0
        put(scr, sy, sx, glyph, paint(colour, bold=bold))
        if lay.cell_w > 1:
            tick = blocks[min(len(blocks) - 1, int(e.health * len(blocks)))]
            shade = "good" if e.health > 0.6 else "gold" if e.health > 0.3 else "warn"
            put(scr, sy, sx + 1, tick, paint(shade))


def _cursor(scr, theme: Theme, g: G.Game, lay: Layout, pulse: bool) -> None:
    """The build cursor shows what would go there, not just where you are.

    On clear ground it is a ghost of the selected building at full footprint,
    drawn exactly where SPACE would put it — which is not always down-and-right
    of the cursor, since a big footprint slides up and left to fit. Over
    something already standing it highlights that building whole, which is
    what X and U act on.
    """
    standing = g.at(g.cy, g.cx)
    if standing is not None:
        fh, fw = standing.spec.foot
        for dy in range(fh):
            sy, sx = _screen(lay, standing.y + dy, standing.x)
            _reverse(scr, sy, sx, fw * lay.cell_w)
        return

    spec = g.spec
    fh, fw = spec.foot
    spot = g.site(g.cy, g.cx, spec)
    if spot is not None:
        colour = spec.glyph if g.gold >= spec.cost else "ghost"
        ghost = G.Building(spec, *spot)
        _slab(scr, theme, lay, ghost, colour, spec.glyph + "_bg", pulse, ghost=True)
        for dy in range(fh):
            sy, sx = _screen(lay, spot[0] + dy, spot[1])
            _reverse(scr, sy, sx, fw * lay.cell_w)
        return

    # Does not fit: mark every cell it wanted, so the obstruction is obvious.
    cross = theme.g["cross"]
    attr = theme.ink("warn", bold=pulse) | curses.A_REVERSE
    for dy in range(fh):
        for dx in range(fw):
            y, x = g.cy + dy, g.cx + dx
            if 0 <= y < g.h and 0 <= x < g.w:
                sy, sx = _screen(lay, y, x)
                put(scr, sy, sx, (cross + " ")[:lay.cell_w], attr)


def _reverse(scr, y: int, x: int, span: int) -> None:
    try:
        scr.chgat(y, x, span, curses.A_REVERSE)
    except curses.error:
        pass


# -- HUD --------------------------------------------------------------------


def _phase(g: G.Game) -> tuple[str, str, float]:
    """Phase label, its detail, and a 0..1 progress value for the bar."""
    if g.state == G.BUILD:
        span = g.mode.build_time if g.wave == 1 else g.mode.break_time
        return "BUILD", f"{g.timer:.1f}s", 1 - min(1.0, g.timer / max(span, 0.01))
    if g.state == G.WAVE:
        left = len(g.queue) + len(g.enemies)
        return "WAVE", f"{left} left", g.wave_progress
    return ("VICTORY", "", 1.0) if g.state == G.WON else ("DEFEATED", "", 1.0)


def _power_rows(theme: Theme, g: G.Game, w: int):
    """Supply against draw, plus a bar that fills up and then turns red."""
    dim = theme.ink("panel", dim=True)
    short = g.short_of_power
    load = g.draw / g.supply if g.supply else (1.0 if g.draw else 0.0)
    tone = "warn" if short else ("gold" if load > 0.8 else "good")
    return [
        [(theme.g["bolt"] + " ", theme.ink(tone, bold=True)),
         (f"{g.draw}", theme.ink(tone, bold=True)),
         (" / ", dim), (f"{g.supply}", theme.ink("text")),
         ("  BROWNOUT" if short else "", theme.ink("warn", bold=True))],
        [(bar(theme, min(1.0, load), w - 4), theme.ink(tone, dim=True))],
    ]


def _sidebar(scr, theme: Theme, g: G.Game, lay: Layout) -> None:
    x, w = lay.side_x, SIDEBAR_W
    y, bottom = lay.side_y, lay.side_y + lay.side_h
    dim = theme.ink("panel", dim=True)
    text = theme.ink("text")
    label, detail, progress = _phase(g)

    target = f" / {g.mode.target}" if g.mode.target else ""
    shown = min(g.lives, 10)
    hearts = theme.g["heart"] * shown + theme.g["bar"][1] * (min(g.max_lives, 10) - shown)
    life_attr = theme.ink("warn" if g.lives <= 3 else "life", bold=True)
    left = g.waves_left

    rows = [
        [("Wave  ", dim), (f"{g.wave}{target}", theme.ink("text", bold=True))],
        [("Left  ", dim),
         (f"{left} to hold" if left is not None else "endless",
          theme.ink("good" if left else "text"))],
        [("Lives ", dim), (hearts, life_attr), (f"  {g.lives}", text)],
        [("Gold  ", dim), (theme.g["coin"] + f" {g.gold}", theme.ink("gold", bold=True))],
        [("Score ", dim), (f"{g.score:,}", text)],
        [],
    ] + _power_rows(theme, g, w) + [[]]
    run = g.run_progress
    if run is not None:
        rows += [
            [("LEVEL", theme.ink("good", bold=True)), (f"   {run * 100:.0f}%", text)],
            [(bar(theme, run, w - 4), theme.ink("good", dim=True))],
        ]
    rows += [
        [(label, theme.ink("accent", bold=True)), (f"   {detail}", theme.ink("text"))],
        [(bar(theme, progress, w - 4), theme.ink("accent", dim=True))],
    ]
    y = panel(scr, theme, y, x, w, "STATUS", rows)
    if y + 8 > bottom:
        return

    rows = []
    for i, spec in enumerate(BUILDINGS):
        chosen = i == g.selected
        afford = g.gold >= spec.cost
        fh, fw = spec.foot
        rows.append([
            (theme.g["sel"] if chosen else " ", theme.ink("accent", bold=True)),
            (spec.key + " ", theme.ink("text" if chosen else "panel", dim=not chosen)),
            (theme.g[spec.glyph] + " ",
             theme.ink(spec.glyph if afford else "ghost", bold=chosen)),
            (spec.name.ljust(10), theme.ink("text" if chosen else "panel", bold=chosen)),
            (f"${spec.cost}".ljust(4), theme.ink("gold" if afford else "ghost")),
            (f"{fh}x{fw}", dim),
        ])
    sel = BUILDINGS[g.selected]
    watt = sel.tiers[0].power
    rows.append([(sel.blurb, dim)])
    rows.append([
        (theme.g["bolt"] + " ", theme.ink("gold")),
        (f"{-watt} supplied" if watt < 0 else f"{watt} drawn", dim),
    ])
    y = panel(scr, theme, y, x, w, "BUILD", rows)
    if y + 4 > bottom:
        return

    # The index: every kind of trouble in the game, always in the same order
    # and the same place, so a glyph on the road can be looked up rather than
    # remembered. What is walking right now is the part that lights up.
    rows = _enemy_rows(theme, g, dim, text, budget=bottom - y - 2)
    if rows:
        y = panel(scr, theme, y, x, w, MENACE_TITLES[g.menace], rows)

    room = bottom - y - 2
    if room >= 2:
        panel(scr, theme, y, x, w, "SITE", _site_rows(theme, g, dim, text)[:room])


def _enemy_strip(theme: Theme, g: G.Game):
    """The index on one line, for the compact HUD: a face and a number each."""
    coming = {spec.name: n for spec, n in g.wave_census()}
    out = []
    for spec in ENEMIES.values():
        met = g.wave >= spec.from_wave
        n = coming.get(spec.name, 0)
        out.append((theme.creep(spec.glyph, g.menace if met else 0),
                    theme.ink(spec.glyph if met else "ghost", bold=bool(n))))
        out.append((f"{n} " if n else f"{theme.g['sep']} ",
                    theme.ink("text" if n else "ghost", dim=not n)))
    return out


def _enemy_rows(theme: Theme, g: G.Game, dim: int, text: int, budget: int = 99):
    """The bestiary, with this wave's numbers written against it.

    Three states per creep, and they are worth telling apart at a glance:
    walking right now (its face and its count), met before but not in this
    wave (dim), and not yet unlocked (the wave it starts at, in ghost). One
    that has not turned up yet keeps its recruit face — the elite silhouette
    is a surprise worth saving.

    In a window with no room for the whole roster the least urgent entries
    drop out first: the creeps furthest from turning up. The ones that
    survive keep their places, so a glyph on the road is always looked up in
    the same order.
    """
    coming = {spec.name: n for spec, n in g.wave_census()}
    ranked = []
    for slot, spec in enumerate(ENEMIES.values()):
        met = g.wave >= spec.from_wave
        n = coming.get(spec.name, 0)
        urgency = 0 if n else (1 if met else 2 + spec.from_wave)
        ranked.append((urgency, slot, spec, met, n))

    keep = sorted(sorted(ranked)[:max(0, budget)], key=lambda r: r[1])
    return [[
        (theme.creep(spec.glyph, g.menace if met else 0) + " ",
         theme.ink(spec.glyph if met else "ghost", bold=bool(n))),
        (spec.name.ljust(9), text if n else dim),
        (f"x{n}" if n else (theme.g["sep"] if met else f"w{spec.from_wave}+"),
         theme.ink("panel") if n else theme.ink("ghost", dim=True)),
    ] for _, _, spec, met, n in keep]


def _site_rows(theme: Theme, g: G.Game, dim: int, text: int):
    """What is under the cursor — a building's record and what the next mark buys."""
    b = g.at(g.cy, g.cx)
    if b is not None:
        rows = [[
            (theme.g[b.spec.glyph] + " ", theme.ink(b.spec.glyph, bold=True)),
            (b.spec.name, theme.ink("text", bold=True)),
            (f"  mk{b.level}", theme.ink("gold", bold=True)),
        ]]
        if b.spec.role == "generator":
            rows.append([("supplies ", dim), (f"{-b.tier.power}", text)])
        else:
            rows.append([("kills ", dim), (f"{b.kills}".ljust(6), text),
                         (theme.g["bolt"], theme.ink("gold")),
                         (f" {b.tier.power}", text)])
        nxt = b.next_tier
        if nxt is None:
            rows.append([("fully upgraded", theme.ink("good"))])
        else:
            afford = g.gold >= nxt.cost
            rows.append([("U ", theme.ink("accent", bold=True)),
                         (f"mk{b.level + 1} ", text),
                         (f"${nxt.cost}", theme.ink("gold" if afford else "ghost"))])
            rows.append([(nxt.note, dim)])
        return rows

    if g.is_path(g.cy, g.cx):
        return [[("the road", theme.ink("text"))], [("creeps walk here", dim)]]

    # Nothing under the cursor, so the panel talks about the ground itself —
    # what it is, whether it will take a building, and whether standing up
    # there is worth the walk.
    here = g.ground(g.cy, g.cx)
    fh, fw = g.spec.foot
    spot = g.site(g.cy, g.cx, g.spec)
    rows = [[(here.name, theme.ink("text" if here.build else "warn", bold=True))],
            [(here.blurb[:20], dim)]]
    if spot is not None:
        gain = g.high_ground(spot[0], spot[1], g.spec)
        rows.append([(f"{g.spec.name} {fh}x{fw} ", dim),
                     ("fits", theme.ink("good"))])
        if gain and g.spec.tiers[0].range:
            rows.append([(theme.g["star"] + " ", theme.ink("gold", bold=True)),
                         (f"reach +{gain:g}", theme.ink("gold"))])
    else:
        rows.append([(f"{g.spec.name} {fh}x{fw} ", dim),
                     ("blocked", theme.ink("warn"))])
    return rows


def _compact(scr, theme: Theme, g: G.Game, lay: Layout) -> None:
    """The narrow fallback: the same information in three dense rows."""
    y, w = lay.side_y, lay.cols
    dim = theme.ink("panel", dim=True)
    label, detail, progress = _phase(g)
    target = f"/{g.mode.target}" if g.mode.target else ""
    left = g.waves_left
    endless = "\u221e" if theme.unicode else "-"

    frags(scr, y, 1, [
        ("wave ", dim), (f"{g.wave}{target}".ljust(7), theme.ink("text", bold=True)),
        ("left ", dim),
        ((f"{left}" if left is not None else endless).ljust(5),
         theme.ink("good" if left else "text")),
        (theme.g["heart"] + " ", theme.ink("life", bold=True)),
        (f"{g.lives}".ljust(5), theme.ink("text")),
        (theme.g["coin"] + " ", theme.ink("gold", bold=True)),
        (f"{g.gold}".ljust(7), theme.ink("gold")),
        ("score ", dim), (f"{g.score:,}".ljust(7), theme.ink("text")),
        (theme.g["bolt"] + " ", theme.ink("warn" if g.short_of_power else "good",
                                          bold=True)),
        (f"{g.draw}/{g.supply}".ljust(8),
         theme.ink("warn" if g.short_of_power else "text")),
        (f"x{g.speed:g}", theme.ink("gold" if g.speed_step else "panel")),
    ], w - 2)

    # One row of bars: the phase always, the whole run when there is an end.
    span = max(6, min(20, (w - 30) // 2))
    pieces = [(label.ljust(6), theme.ink("accent", bold=True)),
              (bar(theme, progress, span), theme.ink("accent", dim=True)),
              (f" {detail:<9}", theme.ink("text"))]
    run = g.run_progress
    if run is not None and w > 60:
        pieces += [("  LEVEL ", theme.ink("good", bold=True)),
                   (bar(theme, run, span), theme.ink("good", dim=True)),
                   (f" {run * 100:.0f}%", theme.ink("text"))]

    # The index rides on the end of this row: every creep in the game, with
    # its count if it is walking. Truncation eats the far end first, which is
    # the end that matters least.
    pieces += [("  ", dim)] + _enemy_strip(theme, g)
    frags(scr, y + 1, 1, pieces, w - 2)

    pieces = []
    for i, spec in enumerate(BUILDINGS):
        chosen = i == g.selected
        afford = g.gold >= spec.cost
        pieces += [
            (theme.g["sel"] if chosen else " ", theme.ink("accent", bold=True)),
            (spec.key, theme.ink("text" if chosen else "panel", dim=not chosen)),
            (theme.g[spec.glyph],
             theme.ink(spec.glyph if afford else "ghost", bold=chosen)),
            (f" {spec.name} ", theme.ink("text" if chosen else "panel", bold=chosen)),
            (f"${spec.cost} ", theme.ink("gold" if afford else "ghost")),
        ]
    frags(scr, y + 2, 1, pieces, w - 2)


def _footer(scr, theme: Theme, g: G.Game, lay: Layout) -> None:
    put(scr, lay.foot_y, 1, g.message[:lay.cols - 2], theme.ink("accent"))
    # Longest hint line that fits; the terminal decides how much we can say.
    tiers = [
        f"{theme.g['move']} move   1-4 pick   SPACE build   U upgrade   X sell   "
        "N wave   +/- speed   P pause",
        f"{theme.g['move']} move  1-4  SPACE build  U upgrade  X sell  N wave  P",
        "1-4 SPACE U X N +/- P",
    ]
    keys = next((t for t in tiers if len(t) <= lay.cols - 2), tiers[-1])
    put(scr, lay.foot_y + 1, 1, keys[:lay.cols - 2], theme.ink("ghost", dim=True))


def pause_overlay(scr, theme: Theme, g: G.Game, lay: Layout,
                  items, selected: int) -> None:
    """A menu over the frozen battlefield.

    Centred on the battlefield rather than on the window, so it lands where
    the player is already looking and leaves the sidebar readable. The board
    stays visible around it on purpose: half of pausing is standing back and
    looking at the line you have built before deciding what to do about it.
    """
    span = max(len(s) for s in items)
    w = min(lay.cols - 2, span + 10)
    body = len(items) + 2
    y = max(0, min(lay.rows - body - 2, lay.board_y + (g.h - body - 2) // 2))
    x = max(0, min(lay.cols - w,
                   lay.board_x + (g.w * lay.cell_w - w) // 2))

    blank = theme.ink("text")
    for row in range(body + 2):
        put(scr, y + row, x, " " * w, blank)

    rows = [[(f" {theme.g['arrow']} " if i == selected else "   ",
              theme.ink("accent", bold=True)),
             (label.ljust(span),
              theme.ink("text", bold=True) if i == selected
              else theme.ink("panel"))]
            for i, label in enumerate(items)]
    rows.append([])
    rows.append([("   " + "P or ESC resumes".ljust(span),
                  theme.ink("ghost", dim=True))])
    panel(scr, theme, y, x, w, "PAUSED", rows)


def draw_too_small(scr, theme: Theme, need_w: int, need_h: int) -> None:
    scr.erase()
    rows, cols = scr.getmaxyx()
    center(scr, rows // 2 - 1, "the field is too narrow to hold a battle",
           theme.ink("warn", bold=True))
    center(scr, rows // 2 + 1,
           f"resize to at least {need_w} x {need_h}  (now {cols} x {rows})",
           theme.ink("panel"))
    center(scr, rows // 2 + 3, "Q to quit", theme.ink("ghost", dim=True))


# ---------------------------------------------------------------------------
# Between the battles: menus and quotes
# ---------------------------------------------------------------------------

LOGO = [
    "████████  ████████  ███████  ",
    "   ██        ██     ██    ██ ",
    "   ██        ██     ██     ██",
    "   ██        ██     ██     ██",
    "   ██        ██     ██    ██ ",
    "   ██        ██     ███████  ",
]


def _logo(theme: Theme) -> list[str]:
    return LOGO if theme.unicode else [r.replace("█", "#") for r in LOGO]


def _menu_rows(scr, theme: Theme, y: int, items, selected: int, width: int) -> None:
    """Left-align the labels at a shared column so the list does not jitter
    as the selection marker moves down it."""
    span = max(len(s) for s in items)
    left = max(0, (width - (span + 4)) // 2)
    for i, label in enumerate(items):
        chosen = i == selected
        frags(scr, y + i, left, [
            (f" {theme.g['arrow']} " if chosen else "   ",
             theme.ink("accent", bold=True)),
            (label.ljust(span),
             theme.ink("text", bold=True) if chosen else theme.ink("panel")),
        ], width - left)


def title_screen(scr, theme: Theme) -> str:
    """The front door. Returns 'story', 'play', 'scores', 'editor', 'help'
    or 'quit'."""
    items = ["THE CAMPAIGN", "SKIRMISH", "HIGH SCORES", "MAP EDITOR",
             "HOW TO PLAY", "QUIT"]
    actions = ["story", "play", "scores", "editor", "help", "quit"]
    sel = 0
    scr.timeout(120)
    tick = 0
    while True:
        rows, cols = scr.getmaxyx()
        scr.erase()
        art = _logo(theme)
        top = max(0, rows // 2 - (len(art) + len(items) + 6) // 2)

        if cols >= len(art[0]) + 4:
            for i, line in enumerate(art):
                # A slow shimmer across the letters, purely for the drama.
                hot = (tick // 2 + i) % 6 < 3
                center(scr, top + i, line,
                       theme.ink("title" if hot else "accent", bold=True), cols)
            y = top + len(art) + 1
        else:
            center(scr, top, "T T D", theme.ink("title", bold=True), cols)
            y = top + 2

        center(scr, y, "T E R M I N A L   T O W E R   D E F E N S E",
               theme.ink("panel"), cols)
        center(scr, y + 1, theme.g["rule"] * min(cols - 4, 46),
               theme.ink("frame", dim=True), cols)
        _menu_rows(scr, theme, y + 3, items, sel, cols)
        center(scr, y + 4 + len(items), "arrows to choose   ENTER to confirm",
               theme.ink("ghost", dim=True), cols)
        scr.refresh()

        key = scr.getch()
        tick += 1
        if key in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(items)
        elif key in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(items)
        elif key in (curses.KEY_ENTER, 10, 13, ord(" ")):
            return actions[sel]
        elif key in (ord("q"), ord("Q")):
            return "quit"


def mode_screen(scr, theme: Theme, modes) -> int | None:
    """Pick a game mode. Returns an index into `modes`, or None to go back."""
    sel = 0
    scr.timeout(-1)
    while True:
        rows, cols = scr.getmaxyx()
        scr.erase()
        width = min(cols - 4, 60)
        left = max(1, (cols - width) // 2)
        top = max(1, rows // 2 - (len(modes) + 8) // 2)

        center(scr, top, "CHOOSE YOUR WAR", theme.ink("title", bold=True), cols)
        center(scr, top + 1, theme.g["rule"] * width, theme.ink("frame", dim=True), cols)

        for i, m in enumerate(modes):
            chosen = i == sel
            y = top + 3 + i
            mark = theme.g["arrow"] if chosen else " "
            frags(scr, y, left, [
                (f" {mark} ", theme.ink("accent", bold=True)),
                (m.name.ljust(12), theme.ink("text", bold=True) if chosen
                 else theme.ink("panel")),
                (m.tagline, theme.ink("ghost", dim=not chosen)),
            ], width)

        m = modes[sel]
        y = top + 4 + len(modes)
        dim = theme.ink("panel", dim=True)
        stats = [
            [("lives   ", dim), (str(m.lives), theme.ink("life", bold=True)),
             ("    gold   ", dim), (str(m.gold), theme.ink("gold", bold=True))],
            [("speed   ", dim), (f"x{m.speed:g}", theme.ink("text")),
             ("    payout ", dim), (f"x{m.bounty:g}", theme.ink("text"))],
            [("waves   ", dim),
             (str(m.target) if m.target else "endless", theme.ink("text"))],
            [],
            [(m.detail[:width - 4], theme.ink("quote"))],
        ]
        panel(scr, theme, y, left, width, m.name.upper(), stats)
        center(scr, rows - 2, "ENTER to march   ESC to go back",
               theme.ink("ghost", dim=True), cols)
        scr.refresh()

        key = scr.getch()
        if key in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(modes)
        elif key in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(modes)
        elif key in (curses.KEY_ENTER, 10, 13, ord(" ")):
            return sel
        elif key in (27, ord("q"), ord("Q")):
            return None


def _help_pages(theme: Theme):
    """The help content as (title, rows) panels, ready to be paged."""
    dim = theme.ink("panel", dim=True)
    text = theme.ink("text")

    idea = [
        [("Creeps walk the road from ", dim),
         (theme.g["start"], theme.ink("start_fg", "start_bg", bold=True)),
         (" to your base ", dim),
         (theme.g["base"], theme.ink("base_fg", "base_bg", bold=True))],
        [("Build on the grass beside it. Anything that gets", dim)],
        [("through costs you lives; at zero the run ends.", dim)],
        [],
        [("Three things are scarce, not one: gold, power off", dim)],
        [("the grid, and ground. Weapons draw power and", dim)],
        [("generators supply it — run short and everything", dim)],
        [("you own slows down together. A Cannon stands on", dim)],
        [("four cells, a Gun on one.", dim)],
        [],
        [("Every map is a real battlefield, and most of it is", dim)],
        [("wood, bog, water or rock you cannot build on. The", dim)],
        [("high ground is worth walking up: a weapon standing", dim)],
        [("wholly on a hill sees further than the same weapon", dim)],
        [("on the flat.", dim)],
    ]

    ground = []
    for t in TERRAIN.values():
        ground.append([
            (theme.tile(t.ink, 1, 1) if theme.tile(t.ink, 1, 1).strip()
             else theme.g["dot"], theme.land(t.ink, 1)),
            (f"  {t.key}  ", theme.ink("accent")),
            (t.name.ljust(10), text if t.build else theme.ink("ghost")),
            (t.blurb, dim),
        ])
    ground.append([])
    ground.append([("maps are text files in maps/ — edit one in anything,", dim)])
    ground.append([("or press MAP EDITOR on the title screen", dim)])

    controls = [
        [("arrows / hjkl / wasd ", text), ("move the cursor", dim)],
        [("1  2  3  4           ", text), ("choose what to build — its", dim)],
        [("                     ", text), ("reach is shown at the cursor", dim)],
        [("SPACE or ENTER       ", text), ("put it down — a big footprint", dim)],
        [("                     ", text), ("slides to fit around the cursor", dim)],
        [("U                    ", text), ("upgrade a mark, up to mk3 — costs", dim)],
        [("                     ", text), ("gold and power, never more ground", dim)],
        [("X                    ", text), ("sell it back at 60%", dim)],
        [("N                    ", text), ("call the next wave early for gold", dim)],
        [("+  and  -            ", text), ("run the battle faster or slower", dim)],
        [("S  and  M            ", text), ("mute the lot, or just the music", dim)],
        [("P    ESC    Q        ", text), ("the pause menu — nothing moves", dim)],
        [("                     ", text), ("while it is up", dim)],
    ]

    pieces = []
    for spec in BUILDINGS:
        t = spec.tiers[0]
        fh, fw = spec.foot
        pieces.append([
            (theme.g[spec.glyph] + "  ", theme.ink(spec.glyph, bold=True)),
            (spec.name.ljust(10), text),
            (f"${t.cost}".ljust(5), theme.ink("gold")),
            (f"{fh}x{fw}".ljust(4), dim),
            ((f"+{-t.power}" if t.power < 0 else f"-{t.power}").ljust(5),
             theme.ink("accent")),
            (spec.blurb, dim),
        ])
    pieces.append([])
    pieces.append([("each creep has three faces — recruit, veteran, elite —",
                    dim)])
    pieces.append([("and walks in the one its wave has earned:", dim)])
    for spec in ENEMIES.values():
        pieces.append([
            # dict.fromkeys keeps the order and drops repeats, so a creep with
            # only one face (the Warlord) shows one, not the same one thrice.
            ("".join(dict.fromkeys(theme.creep(spec.glyph, r)
                                   for r in range(3))).ljust(3) + "  ",
             theme.ink(spec.glyph, bold=True)),
            (spec.name.ljust(9), text),
            (f"w{spec.from_wave}+".ljust(5), theme.ink("panel")),
            (f"{spec.hp:.0f}hp".ljust(7), dim),
            (f"-{spec.leak}".ljust(4), theme.ink("life")),
            (spec.blurb, dim),
        ])

    return [("THE IDEA", idea), ("CONTROLS", controls),
            ("PIECES", pieces), ("THE GROUND", ground)]


def help_screen(scr, theme: Theme) -> None:
    """Paged so it fits any window — a short terminal simply gets more pages."""
    page = 0
    scr.timeout(-1)
    while True:
        rows, cols = scr.getmaxyx()
        width = min(cols - 4, 62)
        left = max(1, (cols - width) // 2)
        room = rows - 5                       # title, footer and a little air

        # Pack panels into pages, never splitting one across a break.
        panels = _help_pages(theme)
        pages, current, used = [], [], 0
        for title, body in panels:
            need = len(body) + 2
            if current and used + need > room:
                pages.append(current)
                current, used = [], 0
            current.append((title, body))
            used += need
        if current:
            pages.append(current)
        page = min(page, len(pages) - 1)

        scr.erase()
        tall = sum(len(b) + 2 for _, b in pages[page])
        y = max(1, (rows - tall - 4) // 2)
        center(scr, y, "HOW TO HOLD A LINE", theme.ink("title", bold=True), cols)
        y += 2
        for title, body in pages[page]:
            y = panel(scr, theme, y, left, width, title, body)

        tail = (f"page {page + 1} of {len(pages)}   ·   any key for more"
                if len(pages) > 1 else "any key to go back")
        center(scr, min(rows - 2, y + 1), tail, theme.ink("ghost", dim=True), cols)
        scr.refresh()

        key = scr.getch()
        if key == curses.KEY_RESIZE:
            continue
        if key == 27 or page + 1 >= len(pages):
            return
        page += 1


# ---------------------------------------------------------------------------
# Choosing where to fight
# ---------------------------------------------------------------------------


def thumbnail(scr, theme: Theme, field_, y: int, x: int,
              max_h: int, max_w: int) -> tuple[int, int]:
    """A small picture of a battlefield. Returns the (rows, cols) it used.

    Drawn from exactly the same three things the real board is — the ground,
    its ramp, its relief — at one column per cell and, when the map is bigger
    than the space, sampled every nth cell. Coarse, but a coastline still
    looks like a coastline and a wood still looks like a wood, which is the
    entire question the player is asking at this screen.
    """
    step = max(1, -(-field_.w // max(1, max_w)), -(-field_.h // max(1, max_h)))
    rows = cols = 0
    for ry in range(0, field_.h, step):
        sy = y + ry // step
        run, run_attr, run_x = [], None, 0
        cols = 0
        for rx in range(0, field_.w, step):
            ink = field_.ink(ry, rx)
            attr = theme.land(ink, field_.relief[ry][rx])
            if attr != run_attr:
                if run:
                    put(scr, sy, x + run_x, "".join(run), run_attr)
                run, run_attr, run_x = [], attr, cols
            run.append(theme.tile(ink, ry, rx))
            cols += 1
        if run:
            put(scr, sy, x + run_x, "".join(run), run_attr)
        rows += 1

    for (cy, cx), glyph, fg, bg in ((field_.path[0], theme.g["start"],
                                     "start_fg", "start_bg"),
                                    (field_.path[-1], theme.g["base"],
                                     "base_fg", "base_bg")):
        put(scr, y + cy // step, x + cx // step, glyph,
            theme.ink(fg, bg, bold=True))
    return rows, cols


def _terrain_strip(theme: Theme, field_):
    """What a map is made of, as coloured fragments — 'grass, wood, marsh'."""
    out = []
    for t, _ in field_.census()[:4]:
        out.append((theme.tile(t.ink, 0, 3) if theme.tile(t.ink, 0, 3).strip()
                    else theme.g["dot"], theme.land(t.ink, 1)))
        out.append((" " + t.name + "  ", theme.ink("panel", dim=True)))
    return out


def _scroll(count: int, selected: int, room: int) -> tuple[int, int]:
    """A window of `room` rows over `count` items that keeps `selected` in it."""
    room = max(1, min(room, count))
    top = max(0, min(selected - room // 2, count - room))
    return top, top + room


def map_screen(scr, theme: Theme, maps, title: str = "CHOOSE A BATTLEFIELD"):
    """Pick a map. Returns a MapDef, None to go back, or "random"."""
    sel = 0
    scr.timeout(-1)
    while True:
        rows_n, cols = scr.getmaxyx()
        width = min(cols - 4, 66)
        left = max(1, (cols - width) // 2)
        listing = ["a battlefield at random"] + [m.name for m in maps]
        room = max(3, rows_n - 16)
        top, end = _scroll(len(listing), sel, room)

        scr.erase()
        center(scr, 1, title, theme.ink("title", bold=True), cols)
        center(scr, 2, theme.g["rule"] * width, theme.ink("frame", dim=True), cols)

        y = 4
        for i in range(top, end):
            chosen = i == sel
            m = None if i == 0 else maps[i - 1]
            frags(scr, y, left, [
                (f" {theme.g['arrow']} " if chosen else "   ",
                 theme.ink("accent", bold=True)),
                (listing[i].ljust(16),
                 theme.ink("text", bold=True) if chosen else theme.ink("panel")),
                ((m.when if m else "").ljust(9), theme.ink("panel", dim=True)),
                ((f"{m.w}x{m.h}" if m else ""), theme.ink("ghost", dim=True)),
            ], width)
            y += 1
        if end < len(listing) or top:
            center(scr, y, f"{sel + 1} / {len(listing)}",
                   theme.ink("ghost", dim=True), cols)
        y += 2

        m = None if sel == 0 else maps[sel - 1]
        if m is not None:
            body = [[(m.subtitle, theme.ink("accent"))],
                    [(m.who[:width - 6], theme.ink("panel", dim=True))],
                    []]
            body += [[(line, theme.ink("quote"))]
                     for line in textwrap.wrap(m.brief, width - 6)
                     [:max(2, rows_n - y - 12)]]
            body += [[], _terrain_strip(theme, m)]
            y = panel(scr, theme, y, left, width, m.name.upper(), body)
            thumb_h = max(0, rows_n - y - 3)
            if thumb_h >= 4:
                thumbnail(scr, theme, m, y + 1,
                          left + max(0, (width - min(m.w, width)) // 2),
                          thumb_h, width)
        else:
            panel(scr, theme, y, left, width, "RANDOM", [
                [("The largest map your window can hold, chosen fresh",
                  theme.ink("quote"))],
                [("for every run.", theme.ink("quote"))]])

        center(scr, rows_n - 2, "ENTER to march   ·   ESC to go back",
               theme.ink("ghost", dim=True), cols)
        scr.refresh()

        key = scr.getch()
        if key in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(listing)
        elif key in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(listing)
        elif key in (curses.KEY_ENTER, 10, 13, ord(" ")):
            return "random" if sel == 0 else maps[sel - 1]
        elif key in (27, ord("q"), ord("Q")):
            return None


def story_screen(scr, theme: Theme, chapters, progress):
    """The campaign menu. Returns a chapter index, or None to go back.

    A locked chapter is still listed — the point of a campaign is that you
    can see how far it goes — but it will not open, and it keeps its briefing
    to itself.
    """
    sel = min(range(len(chapters)),
              key=lambda i: (progress.is_cleared(chapters[i]), i)) \
        if chapters else 0
    scr.timeout(-1)
    while True:
        rows_n, cols = scr.getmaxyx()
        width = min(cols - 4, 66)
        left = max(1, (cols - width) // 2)
        scr.erase()

        if not chapters:
            center(scr, rows_n // 2, "no battlefields installed",
                   theme.ink("warn", bold=True), cols)
            center(scr, rows_n // 2 + 2, "any key to go back",
                   theme.ink("ghost", dim=True), cols)
            scr.refresh()
            scr.getch()
            return None

        done = progress.done
        center(scr, 1, "THE CAMPAIGN", theme.ink("title", bold=True), cols)
        center(scr, 2, f"{done} of {len(chapters)} battles won",
               theme.ink("panel"), cols)

        room = max(4, rows_n - 17)
        top, end = _scroll(len(chapters), sel, room)
        y = 4
        for i in range(top, end):
            ch = chapters[i]
            cleared = progress.is_cleared(ch)
            open_ = progress.unlocked(ch)
            chosen = i == sel
            best = progress.best.get(ch.map_name, 0)
            frags(scr, y, left, [
                (f" {theme.g['arrow']} " if chosen else "   ",
                 theme.ink("accent", bold=True)),
                (ch.order.rjust(4) + "  ",
                 theme.ink("gold" if cleared else "ghost", dim=not open_)),
                (ch.map_name.ljust(15),
                 theme.ink("text", bold=True) if chosen
                 else theme.ink("panel" if open_ else "ghost", dim=not open_)),
                ((ch.field.when if ch.field else "").ljust(8),
                 theme.ink("ghost", dim=True)),
                (theme.g["tick"] + " " if cleared
                 else ("  " if open_ else theme.g["cross"] + " "),
                 theme.ink("good" if cleared else "ghost", dim=True)),
                (f"{best:,}" if best else "", theme.ink("gold", dim=True)),
            ], width)
            y += 1
        if end < len(chapters) or top:
            center(scr, y, f"{sel + 1} / {len(chapters)}",
                   theme.ink("ghost", dim=True), cols)
        y += 2

        ch = chapters[sel]
        m, dim = ch.field, theme.ink("panel", dim=True)
        if not progress.unlocked(ch):
            body = [[("win the battle before it to open this one", dim)]]
        else:
            body = [[(ch.title, theme.ink("accent", bold=True)),
                     (f"   {m.subtitle}" if m else "", dim)]]
            # However many lines of briefing the window can spare, and never
            # a sentence cut off halfway because the panel was a fixed size.
            body += [[(line, theme.ink("quote"))]
                     for line in textwrap.wrap(ch.brief, width - 6)
                     [:max(2, rows_n - y - 9)]]
            body += [[], [("hold ", dim),
                          (f"{ch.mode.target} waves", theme.ink("text")),
                          ("   lives ", dim),
                          (str(ch.mode.lives), theme.ink("life")),
                          ("   gold ", dim),
                          (str(ch.mode.gold), theme.ink("gold"))]]
        y = panel(scr, theme, y, left, width, ch.map_name.upper(), body)
        if m is not None and rows_n - y - 3 >= 4:
            thumbnail(scr, theme, m, y + 1, left, rows_n - y - 3, width)

        center(scr, rows_n - 2, "ENTER to take the field   ·   ESC to go back",
               theme.ink("ghost", dim=True), cols)
        scr.refresh()

        key = scr.getch()
        if key in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(chapters)
        elif key in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(chapters)
        elif key in (curses.KEY_ENTER, 10, 13, ord(" ")):
            if progress.unlocked(chapters[sel]):
                return sel
        elif key in (27, ord("q"), ord("Q")):
            return None


def brief_screen(scr, theme: Theme, header: str, header_attr: int,
                 field_, title: str, text: str, footer: str) -> int:
    """The page between the campaign menu and the fighting.

    The map is drawn full size here, because this is the last moment before
    the shooting starts at which anybody has time to look at the ground.
    """
    scr.timeout(-1)
    while True:
        rows_n, cols = scr.getmaxyx()
        width = min(cols - 4, 66)
        left = max(1, (cols - width) // 2)
        scr.erase()

        center(scr, 1, header, header_attr, cols)
        if field_ is not None:
            center(scr, 2, f"{field_.name}  ·  {field_.subtitle}",
                   theme.ink("panel"), cols)
        center(scr, 3, theme.g["rule"] * width, theme.ink("frame", dim=True), cols)

        y = 5
        lines = textwrap.wrap(text, width - 6)
        room = max(2, rows_n - 12)
        y = panel(scr, theme, y, left, width, title.upper(),
                  [[(line, theme.ink("quote"))] for line in lines[:room]]
                  + ([[], [(field_.who, theme.ink("panel", dim=True))]]
                     if field_ is not None and field_.who else []))

        if field_ is not None and rows_n - y - 3 >= 4:
            thumbnail(scr, theme, field_, y + 1, left,
                      rows_n - y - 3, width)
        center(scr, rows_n - 2, footer, theme.ink("ghost", dim=True), cols)
        scr.refresh()

        key = scr.getch()
        if key != curses.KEY_RESIZE:
            return key


# ---------------------------------------------------------------------------
# The typewriter
# ---------------------------------------------------------------------------

# Beats to hold on after certain characters, so the line breathes.
PUNCTUATION = {",": 0.10, ";": 0.14, ":": 0.14, "—": 0.16,
               ".": 0.26, "!": 0.30, "?": 0.30}


def _year(v: int, approx: bool) -> str:
    prefix = "c. " if approx else ""
    if v < 0:
        return f"{prefix}{-v} BC"
    if v < 1000:
        return f"{prefix}AD {v}"
    return f"{prefix}{v}"


def _credit(q: Quote) -> list[str]:
    return [
        f"— {q.author.upper()}",
        q.role,
        f"born {_year(q.born, q.approx)}    "
        f"died {_year(q.died, q.approx)}    "
        f"aged {q.epitaph()}",
    ]


def quote_scene(scr, theme: Theme, header: str, header_attr: int,
                quote: Quote, subtitle: str, footer: str, sound=None) -> int:
    """Type a quote out, one character at a time, then wait for a key.

    Returns the key that dismissed it. Any keypress while typing skips to the
    end — nobody should be held hostage by a typewriter.

    `sound`, if given, gets the typewriter running under the letters and reads
    the name out when they stop. It is the one place the renderer touches the
    sound card, because it is the one place the timing is only known here.
    """
    def clatter(on: bool) -> None:
        if sound is not None:
            sound.typing(on)
    scr.timeout(0)
    cursor = "█" if theme.unicode else "_"

    def compose(cols: int):
        """(lines, attr, seconds-per-char, indent) blocks, sized to the window."""
        width = max(20, min(58, cols - 8))
        body = textwrap.wrap(f"“{quote.text}”", width)
        return [(body, theme.ink("quote", bold=True), 0.030, 0),
                (_credit(quote), theme.ink("ink"), 0.042, 4)]

    def render(revealed: int, blink: bool) -> int:
        rows, cols = scr.getmaxyx()
        blocks = compose(cols)
        width = max(20, min(58, cols - 8))
        left = max(1, (cols - width) // 2)
        total = sum(len(l) for lines, _, _, _ in blocks for l in lines)
        height = sum(len(lines) for lines, _, _, _ in blocks) + 9
        y = max(0, (rows - height) // 2)
        scr.erase()

        center(scr, y, header, header_attr, cols)
        if subtitle:
            center(scr, y + 1, subtitle, theme.ink("panel"), cols)
        rule = theme.g["rule"] * width
        put(scr, y + 3, left, rule, theme.ink("frame", dim=True))

        row, remaining, cursor_at = y + 5, revealed, None
        for i, (lines, attr, _, indent) in enumerate(blocks):
            if i:
                row += 1                       # a beat between quote and credit
            for line in lines:
                shown = line[:max(0, remaining)]
                put(scr, row, left + indent, shown, attr)
                if remaining < len(line):
                    if cursor_at is None:
                        cursor_at = (row, left + indent + len(shown))
                    remaining = 0
                else:
                    remaining -= len(line)
                    if remaining == 0 and cursor_at is None:
                        cursor_at = (row, left + indent + len(line))
                row += 1
        if blink and cursor_at:
            put(scr, *cursor_at, cursor, theme.ink("accent", bold=True))

        put(scr, row + 1, left, rule, theme.ink("frame", dim=True))
        center(scr, row + 3, footer, theme.ink("ghost", dim=True), cols)
        scr.refresh()
        return total

    # -- type it out --------------------------------------------------------
    revealed, skipped = 0, False
    total = render(0, True)
    blocks = compose(scr.getmaxyx()[1])
    flat = [(ch, delay) for lines, _, delay, _ in blocks
            for line in lines for ch in line]
    clatter(True)
    while revealed < len(flat) and not skipped:
        ch, delay = flat[revealed]
        revealed += 1
        total = render(revealed, True)
        time.sleep(delay + PUNCTUATION.get(ch, 0.0))
        if scr.getch() != -1:
            skipped = True
    clatter(False)

    # The machine stops, and the name it just typed is read out.
    if sound is not None:
        sound.say(quote.author)

    # -- hold, with a blinking cursor, until dismissed ----------------------
    while True:
        render(total if skipped else revealed, (time.monotonic() * 2) % 2 < 1.2)
        time.sleep(0.08)
        key = scr.getch()
        if key not in (-1, curses.KEY_RESIZE):
            return key


# ---------------------------------------------------------------------------
# The leaderboard
# ---------------------------------------------------------------------------


def _score_rows(theme: Theme, rows, highlight=None, width: int = 56):
    """Format a run of leaderboard entries into panel rows."""
    dim = theme.ink("panel", dim=True)
    text = theme.ink("text")
    out = []
    for i, e in enumerate(rows, start=1):
        mine = e is highlight
        tone = theme.ink("gold", bold=True) if mine else text
        out.append([
            (f"{i:2d} ", theme.ink("accent" if mine else "panel", bold=mine)),
            (e.name[:12].ljust(13), tone),
            (f"{e.score:>7,}", tone),
            (f"   wave {e.wave:<4}", dim),
            (("won  " if e.won else "     "), theme.ink("good")),
            (e.dated(), dim),
        ])
    if not out:
        out = [[("no runs recorded yet", dim)]]
    return out


def scores_screen(scr, theme: Theme, board, modes, start_mode: int = 0) -> None:
    """Browse the tables, one mode at a time, with left/right."""
    sel = start_mode
    scr.timeout(-1)
    while True:
        rows_n, cols = scr.getmaxyx()
        width = min(cols - 4, 58)
        left = max(1, (cols - width) // 2)
        entries = board.top(modes[sel].name)
        scr.erase()
        y = max(1, (rows_n - (10 + max(1, len(entries)))) // 2)

        center(scr, y, "ROLL OF HONOUR", theme.ink("title", bold=True), cols)
        chips = []
        for i, m in enumerate(modes):
            chosen = i == sel
            chips += [(f" {m.name} ",
                       theme.ink("accent", bold=True) | curses.A_REVERSE if chosen
                       else theme.ink("panel", dim=True)), ("  ", 0)]
        total = sum(len(t) for t, _ in chips)
        frags(scr, y + 2, max(1, (cols - total) // 2), chips, cols - 2)

        panel(scr, theme, y + 4, left, width, modes[sel].name.upper(),
              _score_rows(theme, entries, width=width))
        if not board.writable:
            center(scr, rows_n - 3, "(scores cannot be saved on this machine)",
                   theme.ink("warn", dim=True), cols)
        arrows = "← →" if theme.unicode else "left/right"
        center(scr, rows_n - 2, f"{arrows} to switch mode   ·   "
               "any other key to go back", theme.ink("ghost", dim=True), cols)
        scr.refresh()

        key = scr.getch()
        if key in (curses.KEY_LEFT, ord("h")):
            sel = (sel - 1) % len(modes)
        elif key in (curses.KEY_RIGHT, ord("l")):
            sel = (sel + 1) % len(modes)
        elif key != curses.KEY_RESIZE:
            return


def ask_name(scr, theme: Theme, default: str, place: int) -> str | None:
    """A one-line text field for a run that made the table. ESC declines."""
    name = default[:12]
    scr.timeout(300)
    while True:
        rows, cols = scr.getmaxyx()
        scr.erase()
        y = rows // 2 - 3
        center(scr, y, f"A PLACE AT NUMBER {place}", theme.ink("gold", bold=True), cols)
        center(scr, y + 2, "who held the line?", theme.ink("panel"), cols)

        blink = (time.monotonic() * 2) % 2 < 1.2
        cursor = ("█" if theme.unicode else "_") if blink else " "
        field = f"  {name}{cursor}  "
        center(scr, y + 4, field, theme.ink("text", bold=True) | curses.A_REVERSE, cols)
        center(scr, y + 6, "ENTER to sign   ·   ESC to stay anonymous",
               theme.ink("ghost", dim=True), cols)
        scr.refresh()

        key = scr.getch()
        if key in (curses.KEY_ENTER, 10, 13):
            return name.strip() or default
        if key == 27:
            return None
        if key in (curses.KEY_BACKSPACE, 127, 8):
            name = name[:-1]
        elif 32 <= key < 127 and len(name) < 12:
            name += chr(key)

