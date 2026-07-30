"""
Look and feel.

Everything the renderer needs to know about *this particular terminal* — which
glyphs it can draw and how many colours it can paint them with — is resolved
once at start-up into a single `Theme` object.  Nothing else in the game asks
the terminal any questions.

Three tiers, each degrading gracefully into the next:

    Unicode + 256 colours   the intended look: textured terrain, box panels
    Unicode + 8 colours     same shapes, blunter palette
    ASCII + no colour       plain letters, still perfectly playable

Set TTD_ASCII=1 to force the ASCII tier (useful if your font renders the
geometric shapes double-width and skews the board).
"""

from __future__ import annotations

import curses
import locale
import os
import sys


# ---------------------------------------------------------------------------
# Glyph sets
# ---------------------------------------------------------------------------
#
# Tuples are *textures*: a cell picks one entry by hashing its coordinates, so
# the ground looks scattered but never flickers between frames.

UNICODE_GLYPHS = {
    "grass":  (" ", " ", " ", "'", " ", " ", ",", " ", " ", "`", " ", "„"),
    "path":   ("░", "░", "░", "░", "░", "▒"),
    "start":  "»",
    "base":   "⌂",
    # Chess pieces for the three weapons: pawn, bishop, rook reads as the
    # same small / medium / heavy progression as their cost and footprint.
    "gun":    "♟",
    "frost":  "♝",
    "cannon": "♜",
    "generator": "Ξ",
    "bolt":   "↯",
    "bullet": "•",
    "shell":  "●",
    "trail":  ("·", "˙"),
    "ring":   ("▓", "▒", "░"),
    "flake":  "❋",
    "hulk":   ("▚", "▞"),   # the bulk a boss drags behind its head
    "ghost":  "▪",
    "cross":  "✗",
    "shot":   "·",
    "burst":  "✳",
    "heart":  "♥",
    "coin":   "◈",
    "hp":     ("░", "▒", "▓", "█"),
    "pip":    "▪",
    "arrow":  "▶",
    "sel":    "▌",
    "dot":    "·",
    "sep":    "·",
    "move":   "↑↓←→",
    "box":    "╭╮╰╯─│",     # top-left, top-right, bottom-left, bottom-right, h, v
    "frame":  "╔╗╚╝═║",     # heavier frame, used around the battlefield
    "bar":    ("█", "░"),
    "rule":   "─",
}

ASCII_GLYPHS = {
    "grass":  (" ", " ", " ", "'", " ", " ", ",", " ", " ", "`", " ", "*"),
    "path":   (".", ".", ".", ".", ".", ":"),
    "start":  ">",
    "base":   "@",
    "gun":    "P",           # pawn
    "frost":  "B",           # bishop
    "cannon": "R",           # rook
    "generator": "G",
    "bolt":   "!",
    "bullet": "*",
    "shell":  "O",
    "trail":  (".", "'"),
    "ring":   ("#", "=", "-"),
    "flake":  "*",
    "hulk":   ("=", "-"),
    "ghost":  ".",
    "cross":  "X",
    "shot":   ".",
    "burst":  "*",
    "heart":  "+",
    "coin":   "$",
    "hp":     (".", ":", "=", "#"),
    "pip":    "-",
    "arrow":  ">",
    "sel":    ">",
    "dot":    ".",
    "sep":    "-",
    "move":   "arrows",
    "box":    "++++-|",     # same six slots as the Unicode set
    "frame":  "++++=|",
    "bar":    ("#", "-"),
    "rule":   "-",
}


# Creeps get three faces each — the recruits you meet early, the veterans, and
# the elites of the late waves — and every face takes steps. The inner tuple
# is the gait: two frames alternating as the thing covers ground, so a wave
# walks rather than slides. The silhouette stays in the same family the whole
# way — circles stay circles, stars stay stars — so a Runner still reads as a
# Runner at wave 20; it has just grown teeth.
UNICODE_MENACE = {
    "grunt":   (("●", "•"), ("◉", "◎"), ("⊛", "⊗")),
    "runner":  (("✦", "✧"), ("✷", "✶"), ("✺", "✹")),
    "tank":    (("■", "▪"), ("▣", "▤"), ("▩", "▨")),
    "reaper":  (("†", "✝"), ("‡", "☨"), ("☠", "✞")),
    # She arrives fully grown, and steps between the black queen and the
    # white one — the heavy flicker Space Impact bosses had on a 3310.
    "warlord": (("♛", "♕"), ("♛", "♕"), ("♛", "♕")),
}

# The plain tier keeps one frame per rank. Two letters swapping back and forth
# at walking pace reads as noise rather than motion, and this tier's whole job
# is to stay legible when nothing else can be trusted.
ASCII_MENACE = {
    "grunt":   (("o",), ("0",), ("8",)),
    "runner":  (("x",), ("y",), ("&",)),
    "tank":    (("t",), ("T",), ("H",)),
    "reaper":  (("v",), ("V",), ("%",)),
    "warlord": (("W",), ("W",), ("W",)),
}

# How many cells a creep covers before its gait takes the next step.
STRIDE = 0.5


# ---------------------------------------------------------------------------
# Colour slots
# ---------------------------------------------------------------------------
#
# The rest of the game only ever refers to colours by these names, so swapping
# a palette is a one-line change here.

RICH = {                    # xterm-256 indices
    "grass_bg": 22,  "grass_fg": 65,
    "path_bg": 94,   "path_fg": 180,
    "start_bg": 28,  "start_fg": 232,
    "base_bg": 124,  "base_fg": 231,
    "gun": 51, "frost": 87, "cannon": 208, "generator": 227,
    "gun_bg": 23, "frost_bg": 24, "cannon_bg": 52, "generator_bg": 58,
    "chill1": 17, "chill2": 18, "chill3": 25, "chill_fg": 117,
    "grunt": 231, "runner": 213, "tank": 203, "reaper": 141, "warlord": 199,
    "menace1": 52, "menace2": 88,      # the ground a veteran / elite walks on
    "shot": 226, "range": 45,
    "frame": 240, "panel": 244, "text": 252, "ghost": 238,
    "gold": 220, "life": 203, "warn": 196, "good": 84,
    "accent": 45, "title": 81, "quote": 253, "ink": 250,
    "blood": 88,
}

BASIC = {                   # the guaranteed eight, on the default background
    "grass_bg": -1,  "grass_fg": curses.COLOR_GREEN,
    "path_bg": -1,   "path_fg": curses.COLOR_YELLOW,
    "start_bg": -1,  "start_fg": curses.COLOR_GREEN,
    "base_bg": -1,   "base_fg": curses.COLOR_RED,
    "gun": curses.COLOR_CYAN, "frost": curses.COLOR_CYAN,
    "cannon": curses.COLOR_RED, "generator": curses.COLOR_YELLOW,
    "gun_bg": -1, "frost_bg": -1, "cannon_bg": -1, "generator_bg": -1,
    "chill1": curses.COLOR_BLUE, "chill2": curses.COLOR_BLUE,
    "chill3": curses.COLOR_BLUE, "chill_fg": curses.COLOR_CYAN,
    "grunt": curses.COLOR_WHITE, "runner": curses.COLOR_MAGENTA, "tank": curses.COLOR_RED,
    "reaper": curses.COLOR_MAGENTA, "warlord": curses.COLOR_RED,
    # Eight colours cannot do a subtle blood-tinted road, so at this tier the
    # rank shows in the silhouette alone.
    "menace1": -1, "menace2": -1,
    "shot": curses.COLOR_YELLOW, "range": curses.COLOR_CYAN,
    "frame": curses.COLOR_BLUE, "panel": curses.COLOR_BLUE,
    "text": curses.COLOR_WHITE, "ghost": curses.COLOR_BLUE,
    "gold": curses.COLOR_YELLOW, "life": curses.COLOR_RED,
    "warn": curses.COLOR_RED, "good": curses.COLOR_GREEN,
    "accent": curses.COLOR_CYAN, "title": curses.COLOR_CYAN,
    "quote": curses.COLOR_WHITE, "ink": curses.COLOR_WHITE,
    "blood": curses.COLOR_RED,
}


def unicode_ok() -> bool:
    """True when we can safely paint box-drawing and block characters."""
    if os.environ.get("TTD_ASCII"):
        return False
    enc = (sys.stdout.encoding or locale.getpreferredencoding(False) or "").lower()
    return "utf" in enc


class Theme:
    """Glyphs plus a lazily-allocated colour-pair cache.

    Colour pairs are allocated on first use rather than up front, which keeps
    the palette declarative: any (foreground, background) combination the
    renderer asks for simply works.
    """

    def __init__(self) -> None:
        self.unicode = unicode_ok()
        self.g = UNICODE_GLYPHS if self.unicode else ASCII_GLYPHS
        self.m = UNICODE_MENACE if self.unicode else ASCII_MENACE
        self.color = curses.has_colors()
        self._pairs: dict[tuple[int, int], int] = {}
        self._next = 1

        if not self.color:
            self.c = {k: -1 for k in RICH}
            return

        curses.start_color()
        self.default_bg = True
        try:
            curses.use_default_colors()
        except curses.error:
            self.default_bg = False
        self.c = dict(RICH if curses.COLORS >= 256 else BASIC)
        if not self.default_bg:
            self.c = {k: (curses.COLOR_BLACK if v == -1 else v) for k, v in self.c.items()}

    # -- colour -------------------------------------------------------------

    def ink(self, fg: str, bg: str | None = None,
            bold: bool = False, dim: bool = False) -> int:
        """Attribute for a named foreground on an optional named background."""
        attr = 0
        if self.color:
            f = self.c.get(fg, -1)
            b = self.c.get(bg, -1) if bg else (-1 if self.default_bg else curses.COLOR_BLACK)
            attr = self._pair(f, b)
        if bold:
            attr |= curses.A_BOLD
        if dim:
            attr |= curses.A_DIM
        return attr

    def _pair(self, fg: int, bg: int) -> int:
        key = (fg, bg)
        if key not in self._pairs:
            if self._next >= min(curses.COLOR_PAIRS, 250):
                return 0                       # out of pairs: fall back to plain
            try:
                curses.init_pair(self._next, fg, bg)
            except curses.error:
                return 0
            self._pairs[key] = curses.color_pair(self._next)
            self._next += 1
        return self._pairs[key]

    # -- glyphs -------------------------------------------------------------

    def texture(self, key: str, y: int, x: int) -> str:
        """Pick a stable texture tile for a cell from its coordinates.

        The bit-mixing matters: a plain multiply-and-xor leaves the low bits
        marching in step with x, and the ground comes out visibly tiled.
        """
        h = (y * 0x9E3779B1) ^ (x * 0x85EBCA77)
        h &= 0xFFFFFFFF
        h ^= h >> 13
        h = (h * 0xC2B2AE35) & 0xFFFFFFFF
        h ^= h >> 16
        tiles = self.g[key]
        return tiles[h % len(tiles)]

    def creep(self, key: str, rank: int = 0, walked: float = 0.0) -> str:
        """A creep's face at the given rank, mid-stride.

        `walked` is how far along the road it is, in cells — the gait is a
        function of distance rather than of time, so anything frozen in a
        frost field slows its step to match, and a paused game stands still.
        """
        gait = self.m[key][max(0, min(len(self.m[key]) - 1, rank))]
        return gait[int(walked / STRIDE) % len(gait)]

    def box(self, heavy: bool = False) -> str:
        return self.g["frame"] if heavy else self.g["box"]
