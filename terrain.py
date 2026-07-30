"""
Ground, and the battlefields drawn on it.

A TTD map is a text file. Anyone with an editor can open one, move a wood,
flood a plain, or draw a road from scratch; the game reads the directory
fresh every time it starts. This module owns that format end to end —

    TERRAIN     the alphabet a map is written in, and what each letter means
    ROADS       the handful of looks a road can wear
    MapDef      one parsed battlefield: header, grid, traced route, relief
    load_maps() everything found on disk, in order, with the broken ones
                set aside rather than allowed to take the game down with them

Nothing here knows about curses, and nothing here knows the rules of the
game. `theme.py` decides what a marsh looks like; `game.py` decides what
standing in one costs you.

Run it directly to check your handiwork without starting the game:

    python3 terrain.py            list every map, and say what is wrong with
                                  the ones that will not load
    python3 terrain.py Cannae     print one, with its header
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# The three characters that make a road. Everything else is scenery you
# either build on or you don't.
ROAD, START, BASE = "#", "S", "E"
PATH_CHARS = START + ROAD + BASE


class MapError(ValueError):
    """A map that cannot be played, with a reason a human can act on."""


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Terrain:
    """One letter of the map alphabet.

    `elev` is the only thing here the renderer really leans on: the board is
    lit from the top left, and every slope, cliff and shoreline you see is
    derived from the differences between neighbouring elevations. It costs
    nothing at runtime — the relief is worked out once, when the map loads.
    """
    key: str                 # the character you type in the file
    name: str
    build: bool              # can a tower stand here
    elev: float              # height, for shading and shadows
    ink: str                 # palette key, resolved by theme.py
    high: float = 0.0        # extra reach for a weapon standing on it
    blurb: str = ""


TERRAIN: dict[str, Terrain] = {t.key: t for t in (
    Terrain(".", "grass",    build=True,  elev=1.0, ink="grass",
            blurb="open ground — build here"),
    Terrain(",", "sand",     build=True,  elev=1.0, ink="sand",
            blurb="desert sand — open, and hot"),
    Terrain('"', "scrub",    build=True,  elev=1.0, ink="scrub",
            blurb="dry steppe grass"),
    Terrain("*", "snow",     build=True,  elev=1.0, ink="snow",
            blurb="snowfield"),
    Terrain(":", "rubble",   build=True,  elev=1.1, ink="rubble",
            blurb="broken stone — still firm enough to build on"),
    Terrain("h", "hill",     build=True,  elev=2.1, ink="hill", high=0.75,
            blurb="high ground — weapons here see further"),
    Terrain("T", "forest",   build=False, elev=2.3, ink="forest",
            blurb="woods — too thick to emplace anything"),
    Terrain("^", "mountain", build=False, elev=3.6, ink="mountain",
            blurb="mountain — nothing goes up there"),
    Terrain("~", "water",    build=False, elev=0.0, ink="water",
            blurb="water"),
    Terrain("%", "marsh",    build=False, elev=0.25, ink="marsh",
            blurb="marsh — it will not take the weight"),
    Terrain("=", "ruins",    build=False, elev=2.5, ink="ruins",
            blurb="rubble walls, too broken to hold a gun"),
)}

GRASS = TERRAIN["."]

# Roads look different in a desert, a city and a sea lane. A map picks one
# with `road:` in its header; the choice is cosmetic, and every road plays
# exactly the same.
ROADS = ("dust", "mud", "stone", "snow", "sand", "water", "grass")
DEFAULT_ROAD = "dust"

# Road cells sit a touch below the ground beside them, so a track through
# open country reads as worn in rather than painted on.
ROAD_ELEV = 0.9


def terrain_at(ch: str) -> Terrain:
    """The terrain a character means. Unknown letters read as grass, so a
    typo in a hand-edited map costs you a texture, not the run."""
    return TERRAIN.get(ch, GRASS)


def legend() -> list[tuple[str, Terrain]]:
    return list(TERRAIN.items())


# ---------------------------------------------------------------------------
# Tracing a road
# ---------------------------------------------------------------------------


def trace(grid: list[str]) -> list[tuple[int, int]]:
    """Walk the road from S to E and return every cell of it, in order.

    This is the whole of TTD's pathfinding. Creeps are positioned by how far
    along this list they are, so the route only has to be worked out once,
    when the map is loaded.

    The rule the art has to obey is simply that the road is one cell wide and
    never touches itself: from any cell there must be exactly one road
    neighbour you have not already walked. Anything else is a fork, and a
    fork has no single answer to "where does this creep go next".
    """
    h, w = len(grid), len(grid[0])

    def find(ch: str) -> tuple[int, int]:
        for y, row in enumerate(grid):
            x = row.find(ch)
            if x >= 0:
                if grid[y].count(ch) > 1 or any(r.count(ch) for r in grid[y + 1:]):
                    raise MapError(f"more than one {ch!r} marker")
                return y, x
        raise MapError(f"no {ch!r} marker — a map needs an entrance S and a base E")

    start, end = find(START), find(BASE)

    def road_neighbours(y: int, x: int):
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and grid[ny][nx] in PATH_CHARS:
                yield ny, nx

    path, seen, cur = [start], {start}, start
    while cur != end:
        ahead = [n for n in road_neighbours(*cur) if n not in seen]
        if len(ahead) != 1:
            raise MapError(
                f"the road {'forks' if ahead else 'stops'} at row {cur[0] + 1}, "
                f"column {cur[1] + 1}"
                + (f" ({len(ahead)} ways on)" if ahead else ""))
        cur = ahead[0]
        seen.add(cur)
        path.append(cur)

    stranded = sum(row.count(c) for row in grid for c in PATH_CHARS) - len(path)
    if stranded:
        raise MapError(f"{stranded} road cells are not joined to the route")
    return path


# ---------------------------------------------------------------------------
# Relief
# ---------------------------------------------------------------------------

# How much higher a neighbour has to be before the light changes. Below this
# the two cells are the same slope and get the same shade.
STEP = 0.15

# A cliff this much taller throws its shadow onto the diagonal as well, which
# is what makes a mountain range look like it has depth rather than edges.
CAST = 0.9


def _mottle(y: int, x: int) -> int:
    """A stable dab of light or shade on flat ground, from its coordinates.

    Without it an open plain is one flat wash of colour. The bit-mixing is
    the same trick `theme.texture` uses, and for the same reason: a plain
    multiply leaves the low bits marching in step with x and the ground comes
    out visibly striped.
    """
    v = (y * 0x9E3779B1) ^ (x * 0x85EBCA77)
    v &= 0xFFFFFFFF
    v ^= v >> 13
    v = (v * 0xC2B2AE35) & 0xFFFFFFFF
    v ^= v >> 16
    v %= 12
    return 0 if v == 0 else (2 if v == 1 else 1)


def relief(grid: list[str]) -> list[list[int]]:
    """A shade per cell — 0 in shadow, 1 flat, 2 catching the light.

    The board is lit from the top left, so a cell below or to the right of
    something taller sits in its shadow, and a cell that rises above its
    neighbours takes the light on its near edge. Two integers of difference
    is all it takes: the eye reads a consistent light source as height, and
    a terminal has no other way to say "this is a ridge".
    """
    h, w = len(grid), len(grid[0])
    elev = [[ROAD_ELEV if ch in PATH_CHARS else terrain_at(ch).elev
             for ch in row] for row in grid]

    out = []
    for y in range(h):
        row = []
        for x in range(w):
            e = elev[y][x]
            up = elev[y - 1][x] if y else e
            left = elev[y][x - 1] if x else e
            diag = elev[y - 1][x - 1] if y and x else e
            behind = max(up, left)
            if behind > e + STEP or diag > e + CAST:
                row.append(0)
            elif e > behind + STEP:
                row.append(2)
            else:
                row.append(_mottle(y, x))
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# A battlefield
# ---------------------------------------------------------------------------

# Header fields a map may declare. Everything else in the header is kept but
# ignored, so notes to yourself survive a round trip through the editor.
HEADER_KEYS = ("name", "battle", "when", "where", "who", "road", "brief")

SEPARATOR = "---"


@dataclass
class MapDef:
    """One battlefield: what it is called, what it looked like, and the art.

    Built from a file on disk (or from the editor, which writes the same
    format). Everything derived — the padded grid, the traced route, the
    relief — is worked out once here, because none of it can change while a
    battle is running.
    """
    name: str
    art: str
    meta: dict[str, str] = field(default_factory=dict)
    source: str = ""

    def __post_init__(self) -> None:
        rows = self.art.strip("\n").split("\n")
        rows = [r.rstrip("\r") for r in rows]
        if not rows or not any(rows):
            raise MapError("the map is empty")
        width = max(len(r) for r in rows)
        # Short rows are padded with the map's own ground, so the art only
        # has to be exact where the road and the scenery are.
        self.grid = [r.ljust(width, self.fill) for r in rows]
        self.h, self.w = len(self.grid), width
        self.path = trace(self.grid)
        self.relief = relief(self.grid)

    # -- header ------------------------------------------------------------

    @property
    def fill(self) -> str:
        ch = self.meta.get("fill", ".")[:1] or "."
        return ch if ch in TERRAIN else "."

    @property
    def road(self) -> str:
        want = self.meta.get("road", DEFAULT_ROAD).strip().lower()
        return want if want in ROADS else DEFAULT_ROAD

    @property
    def when(self) -> str:
        return self.meta.get("when", "")

    @property
    def where(self) -> str:
        return self.meta.get("where", "")

    @property
    def who(self) -> str:
        return self.meta.get("who", "")

    @property
    def brief(self) -> str:
        return self.meta.get("brief", "")

    @property
    def subtitle(self) -> str:
        """'480 BC · the Hot Gates' — whichever halves of that exist."""
        return "  ·  ".join(p for p in (self.when, self.where) if p)

    # -- the ground --------------------------------------------------------

    def at(self, y: int, x: int) -> str:
        return self.grid[y][x]

    def ground(self, y: int, x: int) -> Terrain:
        return terrain_at(self.grid[y][x])

    def is_path(self, y: int, x: int) -> bool:
        return self.grid[y][x] in PATH_CHARS

    def buildable(self, y: int, x: int) -> bool:
        return not self.is_path(y, x) and self.ground(y, x).build

    def ink(self, y: int, x: int) -> str:
        """The palette key for a cell: its terrain, or this map's road."""
        return ("road_" + self.road) if self.is_path(y, x) \
            else self.ground(y, x).ink

    @property
    def open_ground(self) -> int:
        return sum(1 for y in range(self.h) for x in range(self.w)
                   if self.buildable(y, x))

    def census(self) -> list[tuple[Terrain, int]]:
        """What this battlefield is made of, commonest first — for the
        map-select panel, which is trying to say 'this one is a swamp'."""
        tally: dict[str, int] = {}
        for y in range(self.h):
            for x in range(self.w):
                if not self.is_path(y, x):
                    t = self.ground(y, x)
                    tally[t.key] = tally.get(t.key, 0) + 1
        return sorted(((TERRAIN[k], n) for k, n in tally.items()),
                      key=lambda p: -p[1])

    # -- writing it back out -----------------------------------------------

    def to_text(self) -> str:
        """The file this map would be saved as, header and all."""
        lines = [f"name: {self.name}"]
        for key in HEADER_KEYS:
            if key == "name":
                continue
            value = self.meta.get(key)
            if value:
                lines.append(f"{key}: {value}")
        for key, value in self.meta.items():
            if key not in HEADER_KEYS and value:
                lines.append(f"{key}: {value}")
        return "\n".join(lines + [SEPARATOR] + self.grid) + "\n"


def parse(text: str, name: str = "", source: str = "") -> MapDef:
    """Read one map file.

    The format is a few `key: value` lines, a line of `---`, and then the
    art. A file with no `---` is all art, which makes the quickest possible
    map: draw a road from S to E and save it.
    """
    lines = text.replace("\t", "    ").split("\n")
    meta: dict[str, str] = {}
    body = lines
    for i, line in enumerate(lines):
        if line.strip() == SEPARATOR:
            body = lines[i + 1:]
            for header in lines[:i]:
                header = header.strip()
                if not header or header.startswith("#"):
                    continue
                key, sep, value = header.partition(":")
                if sep:
                    meta[key.strip().lower()] = value.strip()
            break
    return MapDef(name=meta.get("name") or name or "unnamed",
                  art="\n".join(body), meta=meta, source=source)


# ---------------------------------------------------------------------------
# Finding maps on disk
# ---------------------------------------------------------------------------

SUFFIX = ".map"

# Anything drawn this small stops being a battlefield.
MIN_W, MIN_H = 10, 5
MAX_W, MAX_H = 220, 90


def user_dir() -> str:
    """Where the editor saves, and where your own maps live."""
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(home, "ttd", "maps")


def map_dirs() -> list[str]:
    """Every directory searched, in the order they are read.

    Later directories win a name clash, so dropping `Cannae.map` in your own
    map folder quietly replaces the one that ships with the game — and
    deleting it puts the original back.
    """
    override = os.environ.get("TTD_MAPS")
    if override:
        return [os.path.expanduser(d) for d in override.split(os.pathsep) if d]
    return [os.path.join(os.path.dirname(os.path.abspath(__file__)), "maps"),
            user_dir()]


def load_maps(dirs: list[str] | None = None) -> tuple[list[MapDef], list[str]]:
    """Read every map we can find. Returns (maps, complaints).

    A map that will not parse is set aside with a note rather than allowed to
    stop the game: someone editing a file by hand should lose that map and
    nothing else, and be told which line to look at.
    """
    found: dict[str, MapDef] = {}
    order: dict[str, tuple] = {}
    problems: list[str] = []
    for folder in (dirs if dirs is not None else map_dirs()):
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for filename in names:
            if not filename.endswith(SUFFIX):
                continue
            full = os.path.join(folder, filename)
            try:
                with open(full, encoding="utf8") as fh:
                    text = fh.read()
                m = parse(text, name=filename[:-len(SUFFIX)], source=full)
                if not (MIN_W <= m.w <= MAX_W and MIN_H <= m.h <= MAX_H):
                    raise MapError(f"{m.w}x{m.h} is outside the playable range")
            except (OSError, MapError) as exc:
                problems.append(f"{filename}: {exc}")
                continue
            found[m.name] = m
            order[m.name] = (m.meta.get("chapter", "zz"), filename)
    maps = sorted(found.values(), key=lambda m: order[m.name])
    return maps, problems


MAPS, LOAD_ERRORS = load_maps()


def by_name(name: str) -> MapDef | None:
    return next((m for m in MAPS if m.name == name), None)


def reload() -> None:
    """Re-read the map directories — the editor calls this after saving."""
    global MAPS, LOAD_ERRORS
    MAPS, LOAD_ERRORS = load_maps()


# ---------------------------------------------------------------------------
# Checking your work from a shell
# ---------------------------------------------------------------------------


def _report() -> int:
    print(f"{len(MAPS)} maps")
    for m in MAPS:
        biggest = ", ".join(f"{t.name} {n}" for t, n in m.census()[:3])
        print(f"  {m.name:<16} {m.w:>3}x{m.h:<3} road {len(m.path):>3} cells  "
              f"build {m.open_ground:>4}   {biggest}")
    for line in LOAD_ERRORS:
        print(f"  BROKEN  {line}")
    if not MAPS:
        print("  (no maps found — looked in " + ", ".join(map_dirs()) + ")")
    return 1 if LOAD_ERRORS else 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        one = by_name(sys.argv[1])
        if one is None:
            print(f"no map called {sys.argv[1]!r}")
            raise SystemExit(1)
        print(one.to_text(), end="")
        raise SystemExit(0)
    raise SystemExit(_report())
