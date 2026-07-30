"""
The leaderboard.

A small JSON file under the user's data directory, holding the best runs per
mode. Every operation degrades quietly: an unreadable or corrupt file reads as
an empty board, and a directory we cannot write to just means this run will not
be remembered. Losing a high score is not worth crashing a game over.
"""

from __future__ import annotations

import getpass
import json
import os
import time
from dataclasses import asdict, dataclass, field

TOP_N = 10          # kept per mode
NAME_MAX = 12


def default_path() -> str:
    base = os.environ.get("TTD_SCORES")
    if base:
        return base
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(home, "ttd", "scores.json")


def default_name() -> str:
    try:
        return (getpass.getuser() or "player")[:NAME_MAX]
    except Exception:
        return "player"


@dataclass
class Entry:
    name: str
    mode: str
    map: str
    wave: int
    score: int
    kills: int
    won: bool = False
    when: float = field(default_factory=time.time)

    @property
    def rank_key(self) -> tuple:
        """Score first, then how far they got, then how long ago — so a tie is
        broken by the deeper run, and an older run keeps its place."""
        return (self.score, self.wave, -self.when)

    def dated(self) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(self.when))


class Board:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or default_path()
        self.entries: list[Entry] = []
        self.writable = True
        self.load()

    # -- persistence --------------------------------------------------------

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf8") as fh:
                raw = json.load(fh)
            fields = Entry.__dataclass_fields__
            self.entries = [Entry(**{k: v for k, v in row.items() if k in fields})
                            for row in raw.get("entries", [])]
        except (OSError, ValueError, TypeError):
            self.entries = []

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf8") as fh:
                json.dump({"version": 1,
                           "entries": [asdict(e) for e in self.entries]}, fh, indent=1)
            os.replace(tmp, self.path)          # never leave a half-written file
            return True
        except OSError:
            self.writable = False
            return False

    # -- queries ------------------------------------------------------------

    def top(self, mode: str | None = None, n: int = TOP_N) -> list[Entry]:
        rows = [e for e in self.entries if mode is None or e.mode == mode]
        rows.sort(key=lambda e: e.rank_key, reverse=True)
        return rows[:n]

    def best(self, mode: str) -> int:
        rows = self.top(mode, 1)
        return rows[0].score if rows else 0

    def qualifies(self, entry: Entry) -> bool:
        """Would this run make its mode's table?"""
        if entry.score <= 0:
            return False
        rows = self.top(entry.mode)
        return len(rows) < TOP_N or entry.rank_key > rows[-1].rank_key

    def place(self, entry: Entry) -> int | None:
        """Where an entry sits in its mode's table, 1-based, or None."""
        for i, row in enumerate(self.top(entry.mode), start=1):
            if row is entry:
                return i
        return None

    def add(self, entry: Entry) -> int | None:
        """File a run, trim the mode back to TOP_N, and persist. Returns its place."""
        self.entries.append(entry)
        keep = {id(e) for m in {e.mode for e in self.entries} for e in self.top(m)}
        self.entries = [e for e in self.entries if id(e) in keep]
        self.save()
        return self.place(entry)
