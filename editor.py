"""
The map editor.

    python3 editor.py            on its own
    MAP EDITOR                   from the title screen

Maps are text files, so this is a convenience rather than a necessity — you
can do everything here with any editor and a fixed-width font. What it adds
is the two things a text editor cannot: you see the ground lit the way the
game will light it, and it tells you the moment the road stops joining up.

The brush is a map character, and you choose it by typing it. `T` paints a
wood, `~` water, `^` mountains, `#` road. That is the whole idea — what you
press is what lands in the file. Which means the arrow keys have to do the
moving, since `h` is a hill here and not a direction.

Saved maps go to the user map directory, where they override anything of the
same name that ships with the game. Delete the file and the original comes
back.
"""

from __future__ import annotations

import curses
import os

import render
import terrain
from render import center, frags, panel, put
from theme import Theme

# Painting order for TAB, roughly ground-you-can-use first.
BRUSHES = [".", ",", '"', "*", ":", "h", "T", "^", "~", "%", "=", "#"]

MARKERS = "SE"

NEW_W, NEW_H = 37, 10
UNDO_DEPTH = 64

HELP = [
    ("arrows", "move"),
    (". , \" * : h", "grass sand scrub snow rubble hill"),
    ("T ^ ~ % =", "wood mountain water marsh ruins"),
    ("#  S  E", "road, the entrance, your base"),
    ("SPACE", "paint  ·  TAB next brush"),
    ("D", "draw as you move"),
    ("[ ]  { }", "wider/narrower, taller/shorter"),
    ("V", "check the road joins up"),
    ("N  O  M", "new  ·  open  ·  name and notes"),
    ("W", "write it to disk"),
    ("U", "undo"),
    ("ESC", "leave the editor"),
]


class Sheet:
    """A map being drawn: a grid of characters and the header that goes with it.

    Deliberately not a MapDef — a half-drawn map has no road yet, and a class
    whose constructor traces the route cannot represent one. The sheet turns
    itself into a MapDef only when asked, which is also when it finds out
    whether it is playable.
    """

    def __init__(self, name: str = "Untitled", rows: list[str] | None = None,
                 meta: dict | None = None) -> None:
        self.name = name
        self.meta = dict(meta or {})
        self.meta["name"] = name
        rows = rows or ([("." * NEW_W)] * NEW_H)
        self.cells = [list(r) for r in rows]
        self.undo: list[list[str]] = []
        self.dirty = False
        self._relief: list[list[int]] | None = None

    # -- shape --------------------------------------------------------------

    @property
    def h(self) -> int:
        return len(self.cells)

    @property
    def w(self) -> int:
        return len(self.cells[0])

    @property
    def fill(self) -> str:
        ch = self.meta.get("fill", ".")[:1]
        return ch if ch in terrain.TERRAIN else "."

    @property
    def road(self) -> str:
        want = self.meta.get("road", terrain.DEFAULT_ROAD)
        return want if want in terrain.ROADS else terrain.DEFAULT_ROAD

    def rows(self) -> list[str]:
        return ["".join(r) for r in self.cells]

    # -- editing ------------------------------------------------------------

    def snapshot(self) -> None:
        self.undo.append(self.rows())
        del self.undo[:-UNDO_DEPTH]

    def restore(self) -> bool:
        if not self.undo:
            return False
        self.cells = [list(r) for r in self.undo.pop()]
        self._relief = None
        return True

    def paint(self, y: int, x: int, ch: str) -> None:
        if self.cells[y][x] == ch:
            return
        self.snapshot()
        if ch in MARKERS:
            # There can only be one entrance and one base, so painting either
            # picks it up and puts it down somewhere else rather than leaving
            # a second one behind for the tracer to complain about.
            for ry in range(self.h):
                for rx in range(self.w):
                    if self.cells[ry][rx] == ch:
                        self.cells[ry][rx] = "#"
        self.cells[y][x] = ch
        self.dirty = True
        self._relief = None

    def resize(self, dw: int, dh: int) -> bool:
        w, h = self.w + dw, self.h + dh
        if not (terrain.MIN_W <= w <= terrain.MAX_W
                and terrain.MIN_H <= h <= terrain.MAX_H):
            return False
        self.snapshot()
        cells = [row[:w] + [self.fill] * max(0, w - len(row))
                 for row in self.cells[:h]]
        cells += [[self.fill] * w for _ in range(max(0, h - len(cells)))]
        self.cells = cells
        self.dirty = True
        self._relief = None
        return True

    # -- what the renderer needs -------------------------------------------

    @property
    def relief(self) -> list[list[int]]:
        if self._relief is None:
            self._relief = terrain.relief(self.rows())
        return self._relief

    def ink(self, y: int, x: int) -> str:
        ch = self.cells[y][x]
        if ch in terrain.PATH_CHARS:
            return "road_" + self.road
        return terrain.terrain_at(ch).ink

    # -- saving -------------------------------------------------------------

    def to_text(self) -> str:
        keys = [k for k in terrain.HEADER_KEYS if self.meta.get(k)]
        extra = [k for k in self.meta if k not in terrain.HEADER_KEYS
                 and self.meta.get(k)]
        lines = [f"name: {self.name}"]
        lines += [f"{k}: {self.meta[k]}" for k in keys if k != "name"]
        lines += [f"{k}: {self.meta[k]}" for k in extra]
        return "\n".join(lines + [terrain.SEPARATOR] + self.rows()) + "\n"

    def check(self) -> str:
        """Empty when this map would load; otherwise why it would not."""
        try:
            terrain.parse(self.to_text(), name=self.name)
        except terrain.MapError as exc:
            return str(exc)
        return ""

    def filename(self) -> str:
        slug = "".join(c if c.isalnum() else "-" for c in self.name.lower())
        return "-".join(p for p in slug.split("-") if p) + terrain.SUFFIX

    def save(self) -> str:
        """Write it out. Returns a line to show the user, good news or bad."""
        folder = terrain.user_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, self.filename())
            with open(path, "w", encoding="utf8") as fh:
                fh.write(self.to_text())
        except OSError as exc:
            return f"could not save: {exc}"
        self.dirty = False
        terrain.reload()
        return f"saved to {path}"

    @classmethod
    def load(cls, m: terrain.MapDef) -> "Sheet":
        return cls(name=m.name, rows=list(m.grid), meta=dict(m.meta))


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def _viewport(sheet: Sheet, rows: int, cols: int) -> tuple[int, int, int]:
    """(palette width, rows of map on screen, columns of map on screen).

    Worked out in one place because the drawing code and the scrolling code
    have to agree about it exactly, or the cursor walks off the edge of a
    window that thinks it is a different size.
    """
    pal_w = 26 if cols >= sheet.w + 30 else 0
    return pal_w, max(1, rows - 5), max(1, cols - 2 - pal_w)


def _draw(scr, theme: Theme, sheet: Sheet, cy: int, cx: int, brush: str,
          drawing: bool, message: str, oy: int, ox: int) -> None:
    rows, cols = scr.getmaxyx()
    scr.erase()

    frags(scr, 0, 1, [
        ("MAP EDITOR", theme.ink("title", bold=True)),
        (f"  {theme.g['sep']}  ", theme.ink("frame", dim=True)),
        (sheet.name, theme.ink("text", bold=True)),
        ("*" if sheet.dirty else " ", theme.ink("warn", bold=True)),
        (f"   {sheet.w}x{sheet.h}", theme.ink("panel", dim=True)),
        (f"   road {sheet.road}", theme.ink("panel", dim=True)),
    ], cols - 2)

    # The board sits under the title bar and above two rows of footer, with a
    # palette column on the right when there is room for one.
    pal_w, view_h, view_w = _viewport(sheet, rows, cols)
    top = 2
    for ry in range(min(view_h, sheet.h - oy)):
        y = oy + ry
        run, run_attr, run_x = [], None, 0
        for rx in range(min(view_w, sheet.w - ox)):
            x = ox + rx
            ink = sheet.ink(y, x)
            attr = theme.land(ink, sheet.relief[y][x])
            if attr != run_attr:
                if run:
                    put(scr, top + ry, 1 + run_x, "".join(run), run_attr)
                run, run_attr, run_x = [], attr, rx
            run.append(theme.tile(ink, y, x))
        if run:
            put(scr, top + ry, 1 + run_x, "".join(run), run_attr)

    ends = {"S": ("start", "start_fg", "start_bg"),
            "E": ("base", "base_fg", "base_bg")}
    for y in range(max(0, oy), min(sheet.h, oy + view_h)):
        for x in range(max(0, ox), min(sheet.w, ox + view_w)):
            mark = ends.get(sheet.cells[y][x])
            if mark:
                glyph, fg, bg = mark
                put(scr, top + y - oy, 1 + x - ox, theme.g[glyph],
                    theme.ink(fg, bg, bold=True))

    # The cursor carries the brush, so you can see what would land before it does.
    if oy <= cy < oy + view_h and ox <= cx < ox + view_w:
        put(scr, top + cy - oy, 1 + cx - ox, brush,
            theme.ink("accent", bold=True) | curses.A_REVERSE)

    if pal_w:
        t = terrain.terrain_at(brush)
        label = "road" if brush in terrain.PATH_CHARS else t.name
        body = [[(f" {brush} ", theme.ink("accent", bold=True) | curses.A_REVERSE),
                 ("  " + label, theme.ink("text", bold=True))],
                [("   " + ("draw is ON" if drawing else "press D to draw"),
                  theme.ink("good" if drawing else "ghost", dim=not drawing))],
                []]
        for key in BRUSHES:
            spec = terrain.TERRAIN.get(key)
            ink = ("road_" + sheet.road) if key == "#" else spec.ink
            body.append([
                (theme.g["sel"] if key == brush else " ",
                 theme.ink("accent", bold=True)),
                (f" {key} ", theme.land(ink, 1)),
                (" " + ("road" if key == "#" else spec.name),
                 theme.ink("text" if key == brush else "panel")),
            ])
        panel(scr, theme, 2, cols - pal_w - 1, pal_w, "BRUSH", body)

    put(scr, rows - 2, 1, message[:cols - 2], theme.ink("accent"))
    hint = ("arrows move   SPACE paint   TAB brush   D draw   V check   "
            "W write   ? keys   ESC out")
    if len(hint) > cols - 2:
        hint = "SPACE paint  TAB brush  V check  W write  ? keys  ESC"
    put(scr, rows - 1, 1, hint[:cols - 2], theme.ink("ghost", dim=True))


def _prompt(scr, theme: Theme, label: str, initial: str, limit: int = 60) -> str | None:
    """A one-line text field. ESC backs out and changes nothing."""
    text = initial[:limit]
    scr.timeout(-1)
    while True:
        rows, cols = scr.getmaxyx()
        width = min(cols - 4, 64)
        left = max(1, (cols - width) // 2)
        y = rows // 2 - 2
        for row in range(5):
            put(scr, y + row, left, " " * width, theme.ink("text"))
        panel(scr, theme, y, left, width, label.upper(), [
            [(text[-(width - 6):] + "_", theme.ink("text", bold=True))],
            [("ENTER to keep it   ·   ESC to leave it alone",
              theme.ink("ghost", dim=True))],
        ])
        scr.refresh()
        key = scr.getch()
        if key in (curses.KEY_ENTER, 10, 13):
            return text.strip()
        if key == 27:
            return None
        if key in (curses.KEY_BACKSPACE, 127, 8):
            text = text[:-1]
        elif 32 <= key < 127 and len(text) < limit:
            text += chr(key)


def _choose_map(scr, theme: Theme) -> terrain.MapDef | None:
    maps = list(terrain.MAPS)
    if not maps:
        return None
    chosen = render.map_screen(scr, theme, maps, title="OPEN A BATTLEFIELD")
    return None if chosen in (None, "random") else chosen


def _keys_screen(scr, theme: Theme) -> None:
    scr.timeout(-1)
    while True:
        rows, cols = scr.getmaxyx()
        width = min(cols - 4, 60)
        left = max(1, (cols - width) // 2)
        scr.erase()
        y = max(1, (rows - len(HELP) - 8) // 2)
        center(scr, y, "THE EDITOR", theme.ink("title", bold=True), cols)
        panel(scr, theme, y + 2, left, width, "KEYS",
              [[(k.ljust(13), theme.ink("text")),
                (v, theme.ink("panel", dim=True))] for k, v in HELP])
        center(scr, min(rows - 2, y + len(HELP) + 5),
               "maps are saved to " + terrain.user_dir(),
               theme.ink("ghost", dim=True), cols)
        scr.refresh()
        if scr.getch() != curses.KEY_RESIZE:
            return


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

MOVES = {curses.KEY_UP: (-1, 0), curses.KEY_DOWN: (1, 0),
         curses.KEY_LEFT: (0, -1), curses.KEY_RIGHT: (0, 1)}

RESIZE = {ord("]"): (1, 0), ord("["): (-1, 0),
          ord("}"): (0, 1), ord("{"): (0, -1)}


def edit(scr, theme: Theme, sheet: Sheet | None = None) -> None:
    """Run the editor until the player leaves it."""
    sheet = sheet or Sheet()
    cy = cx = 0
    oy = ox = 0
    brush = "#"
    drawing = False
    message = "draw a road from S to E, then press V"

    while True:
        rows, cols = scr.getmaxyx()
        # Keep the cursor in view; the map may be wider than the terminal.
        _, view_h, view_w = _viewport(sheet, rows, cols)
        cy, cx = min(cy, sheet.h - 1), min(cx, sheet.w - 1)
        oy = max(0, min(oy, cy, sheet.h - view_h))
        ox = max(0, min(ox, cx, sheet.w - view_w))
        oy = max(oy, cy - view_h + 1)
        ox = max(ox, cx - view_w + 1)

        scr.timeout(-1)
        _draw(scr, theme, sheet, cy, cx, brush, drawing, message, oy, ox)
        scr.refresh()
        key = scr.getch()

        if key == curses.KEY_RESIZE:
            continue
        if key in MOVES:
            dy, dx = MOVES[key]
            cy = max(0, min(sheet.h - 1, cy + dy))
            cx = max(0, min(sheet.w - 1, cx + dx))
            if drawing:
                sheet.paint(cy, cx, brush)
            continue
        if key in RESIZE:
            dw, dh = RESIZE[key]
            message = (f"{sheet.w}x{sheet.h}" if sheet.resize(dw, dh)
                       else "that is as far as it goes")
            continue
        if key in (ord(" "), curses.KEY_ENTER, 10, 13):
            sheet.paint(cy, cx, brush)
            continue
        if key == 9:                              # TAB
            brush = BRUSHES[(BRUSHES.index(brush) + 1) % len(BRUSHES)] \
                if brush in BRUSHES else BRUSHES[0]
            continue
        if 0 <= key < 256 and chr(key) in terrain.TERRAIN:
            brush = chr(key)
            continue
        if 0 <= key < 256 and chr(key) in "#SE":
            brush = chr(key)
            continue

        char = chr(key).lower() if 0 <= key < 256 else ""
        if char == "d":
            drawing = not drawing
            message = "drawing as you move" if drawing else "drawing off"
        elif char == "u":
            message = "undone" if sheet.restore() else "nothing to undo"
        elif char == "v":
            problem = sheet.check()
            message = problem or "the road runs clean from S to E"
        elif char == "w":
            problem = sheet.check()
            message = sheet.save() if not problem \
                else f"not saved — {problem}"
        elif char == "n":
            name = _prompt(scr, theme, "name the battle", "Untitled")
            if name:
                sheet, cy, cx, oy, ox = Sheet(name), 0, 0, 0, 0
                message = "a fresh field"
        elif char == "o":
            picked = _choose_map(scr, theme)
            if picked is not None:
                sheet, cy, cx, oy, ox = Sheet.load(picked), 0, 0, 0, 0
                message = f"opened {sheet.name}"
        elif char == "m":
            for field_, label in (("name", "name the battle"),
                                  ("when", "when was it"),
                                  ("where", "where was it"),
                                  ("who", "who fought"),
                                  ("road", "road look: " + " ".join(terrain.ROADS)),
                                  ("brief", "a line about it")):
                value = _prompt(scr, theme, label, sheet.meta.get(field_, ""))
                if value is None:
                    break
                sheet.meta[field_] = value
                if field_ == "name" and value:
                    sheet.name = value
            sheet.dirty = True
            message = "notes updated"
        elif char == "?":
            _keys_screen(scr, theme)
        elif key == 27 or char == "q":
            if sheet.dirty:
                answer = _prompt(scr, theme,
                                 "unsaved — type yes to leave anyway", "")
                if (answer or "").lower() not in ("y", "yes"):
                    message = "still here"
                    continue
            return


def main(scr) -> None:
    curses.curs_set(0)
    scr.keypad(True)
    if hasattr(curses, "set_escdelay"):
        curses.set_escdelay(50)
    edit(scr, Theme())


if __name__ == "__main__":
    import locale

    locale.setlocale(locale.LC_ALL, "")
    curses.wrapper(main)
