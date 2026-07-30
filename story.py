"""
The campaign: sixteen battles, in the order they happened.

A chapter is a map plus the rules of the day plus a few lines about what the
real thing was like. The rules are the interesting part — each battle is set
up so that whatever decided it historically is also what decides it here:

    Marathon      a small field and time to think; the campaign's first lesson
    Thermopylae   almost no ground to build on, and it does not matter
    Gaugamela     the biggest waves in the game across the flattest map
    Cannae        money for a deep line, and the sides are where you lose it
    Alesia        the longest road in the game, walked from the outside in
    Teutoburg     little money, less warning, and trees on both sides
    Hastings      a ridge worth reach, and a marsh for anyone who leaves it
    Agincourt     mud: everything slow, and a funnel pays for itself
    Waterloo      hold until nightfall, and not one wave longer
    Gettysburg    a fishhook, and the hills that hold its ends
    Rorke's Drift one small perimeter, overlooked, all night
    Midway        one island, no room, no second chance
    El Alamein    supplies, and plenty of them, for the first time
    Stalingrad    rubble to build in, ruins you cannot, no room to give
    Kursk         they know you are coming, and you get to dig first
    Dien Bien Phu the valley floor, and they hold every hill above it

Progress is a small JSON file: which chapters have been cleared, and the best
score on each. Clearing one unlocks the next; nothing is ever locked again.
Losing costs you nothing but the run.

The words in here are the only part of TTD that claims to be about history.
They are short on purpose — a briefing, not a lecture.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import terrain
from content import Mode


# ---------------------------------------------------------------------------
# The chapters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chapter:
    """One battle of the campaign.

    `mode` is a full Mode, so a chapter can bend any dial the four skirmish
    modes can — and every chapter sets `target`, because a campaign made of
    endless waves is not a campaign, it is a treadmill with subtitles.
    """
    map_name: str
    title: str               # what this chapter is called
    mode: Mode
    brief: str               # read before the battle
    after: str               # read when it is won

    @property
    def field(self) -> terrain.MapDef | None:
        return terrain.by_name(self.map_name)

    @property
    def order(self) -> str:
        """The numeral beside it in the list — its position, not a stored
        field, so inserting a battle never leaves the campaign miscounted."""
        try:
            return numeral(CHAPTERS.index(self) + 1)
        except ValueError:
            return "?"


def numeral(n: int) -> str:
    out = ""
    for value, sign in ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += sign
            n -= value
    return out


def _mode(name: str, tagline: str, detail: str, **kw) -> Mode:
    """A chapter's rules, starting from something sane and Classic-shaped."""
    base = dict(lives=20, gold=100, power=10, hp_growth=1.16, speed=1.0,
                bounty=1.2, build_time=20.0, break_time=8.0, spawn_gap=0.55,
                target=10)
    base.update(kw)
    return Mode(name, tagline, detail, **base)


CHAPTERS: list[Chapter] = [
    Chapter(
        "Marathon", "The Run Home",
        _mode("Marathon", "where it starts",
              "A short field, a fair fight, and time to think.",
              lives=20, gold=120, power=12, target=6, hp_growth=1.14,
              build_time=30.0, break_time=10.0),
        "A plain a mile wide with the mountains behind you, a marsh at one "
        "end and the bay at the other. There is not much ground and there "
        "does not need to be. Put a generator down first, then something to "
        "shoot with, and watch where the road bends.",
        "The Athenians thinned their centre, let it be pushed back, and "
        "closed from both wings. Then they marched twenty-six miles home "
        "before the Persian fleet could get there — which is the only reason "
        "anybody still runs that distance."),

    Chapter(
        "Thermopylae", "The Hot Gates",
        _mode("Thermopylae", "hold the pass",
              "Numbers cannot help them here. Neither can they help you.",
              lives=15, gold=110, power=12, target=8, hp_growth=1.15,
              build_time=25.0),
        "Xerxes has an army no one can count and a road one cart wide to "
        "bring it down. The cliffs are on your left and the sea is on your "
        "right, and neither of them is going anywhere. Hold the gate.",
        "Eight waves, and the pass held every time. It was a traitor and a "
        "goat path that finished the real thing — nothing that happened at "
        "the wall."),

    Chapter(
        "Gaugamela", "The Levelled Plain",
        _mode("Gaugamela", "no flank, no cover",
              "Darius graded the ground flat. Now everyone can see everything.",
              lives=20, gold=150, power=14, target=10, hp_growth=1.17,
              speed=1.1, bounty=1.4, spawn_gap=0.40),
        "Darius had the ground levelled so his scythed chariots could run at "
        "you cleanly, and there is nothing on this plain to hide behind or "
        "hook a line onto. You will not hold everywhere. Choose where.",
        "The centre broke, as it did in 331 BC, and once the centre breaks "
        "the numbers on the wings stop mattering."),

    Chapter(
        "Cannae", "The Bag",
        _mode("Cannae", "let the centre give",
              "Deep pockets and a river at your back.",
              lives=18, gold=180, power=16, target=11, hp_growth=1.18,
              bounty=1.5),
        "Hannibal's trick was to let his own centre be pushed back until the "
        "legions had walked into a bag and could not lift their arms. You "
        "have the money to build that bag. The river will not let them out.",
        "Rome lost more men in an afternoon at Cannae than on any day before "
        "the Somme, and did not sue for peace. That was the part Hannibal "
        "got wrong."),

    Chapter(
        "Alesia", "Two Walls",
        _mode("Alesia", "besieged from both sides",
              "A very long road, and a very long day.",
              lives=22, gold=200, power=18, target=12, hp_growth=1.17,
              break_time=7.0, bounty=1.4),
        "Caesar ringed the hill fort, then built a second ring facing "
        "outwards when the relief army arrived. Everything walks the whole "
        "spiral. Everything you build gets used twice.",
        "Vercingetorix rode out, laid his arms at Caesar's feet, and spent "
        "six years in a cell before being paraded and strangled. Caesar "
        "wrote it up himself."),

    Chapter(
        "Teutoburg", "Varus' Road",
        _mode("Teutoburg", "the column is strung out",
              "Little money, less warning, and trees on both sides.",
              lives=12, gold=80, power=10, target=10, hp_growth=1.19,
              bounty=1.0, build_time=14.0, break_time=5.0),
        "Three legions on a track between a wooded hill and a bog, in the "
        "rain, strung out over miles because that is what a road does to an "
        "army. The trees take most of the ground. Spend what little you have "
        "where the track bends.",
        "Varus fell on his sword. Augustus is said to have spent months "
        "beating his head against a door — *Quintili Vare, legiones redde*. "
        "Rome never used the numbers XVII, XVIII or XIX again."),

    Chapter(
        "Hastings", "The Shield Wall",
        _mode("Hastings", "hold the ridge",
              "High ground, and a marsh for anyone who leaves it.",
              lives=16, gold=130, power=14, target=10, hp_growth=1.17,
              bounty=1.3),
        "Harold's line stands on Senlac ridge and William's has to come up "
        "the slope into it. The ridge is worth reach; the ridge is worth "
        "everything. Do not be tempted down off it.",
        "The wall held from nine in the morning until dusk, and broke when "
        "men chased a retreat down the hill. The battle was decided by "
        "people leaving the high ground."),

    Chapter(
        "Agincourt", "Mud",
        _mode("Agincourt", "everything is slow",
              "Ground so soft that nothing arrives at speed.",
              lives=18, gold=120, power=14, target=11, hp_growth=1.18,
              speed=0.85, bounty=1.35, break_time=9.0),
        "A ploughed field soaked overnight, narrowing between two woods. "
        "Everything crossing it is already exhausted. Archers on the flanks "
        "and a funnel in the middle: that is the whole plan, and it worked.",
        "Men in armour drowned face down in a foot of mud because they could "
        "not get up. The French lost most of a generation of their nobility "
        "in about three hours."),

    Chapter(
        "Waterloo", "Until Nightfall",
        _mode("Waterloo", "hold until the Prussians come",
              "Ten waves and it is over — whatever is left of you.",
              lives=14, gold=160, power=16, target=10, hp_growth=1.20,
              speed=1.05, bounty=1.4, break_time=6.0),
        "Wellington's whole plan is to still be here at the end of the day. "
        "Three farmhouses in front of the line, the reverse slope behind it, "
        "and Blucher marching somewhere off the map. Do not lose before "
        "dark.",
        "\"The nearest run thing you ever saw in your life.\" Wellington "
        "wrote the dispatch himself and could not finish it without stopping."),

    Chapter(
        "Gettysburg", "Three Days",
        _mode("Gettysburg", "the fishhook",
              "Interior lines, and very little room for error.",
              lives=12, gold=170, power=18, target=12, hp_growth=1.19,
              speed=1.05, bounty=1.4),
        "The line curls from Culp's Hill round to the Round Tops, and its "
        "shape is the advantage: you can move strength from one end to the "
        "other faster than the attack can walk around it. Use the hills.",
        "On the third day fifteen thousand men crossed three-quarters of a "
        "mile of open ground towards the centre of that line. Rather fewer "
        "came back."),

    Chapter(
        "Rorke's Drift", "The Wall of Mealie Bags",
        _mode("Rorke's Drift", "a hundred and fifty men",
              "One small post, all night, and no relief coming.",
              lives=10, gold=140, power=14, target=10, hp_growth=1.19,
              speed=1.1, bounty=1.4, break_time=6.0),
        "A store, a hospital, and a wall thrown up in an afternoon out of "
        "biscuit boxes and bags of maize. Everything is inside the perimeter "
        "or it is lost, and the hill overlooks you the whole time. There is "
        "nothing to be done about the hill.",
        "They came all night and stopped at dawn. Eleven Victoria Crosses "
        "were given for one small building — partly because the same army "
        "had been annihilated at Isandlwana that morning, and London badly "
        "wanted a different story."),

    Chapter(
        "Midway", "Five Minutes",
        _mode("Midway", "one island, no second chance",
              "Almost nowhere to build, and no lives to spare.",
              lives=8, gold=200, power=20, target=10, hp_growth=1.18,
              speed=1.15, bounty=1.6, build_time=25.0),
        "There is one piece of dry land in this entire ocean and it is a "
        "runway. Everything you own has to fit on the atoll and reach the "
        "lanes. The approaches at the edge of the map cannot be covered at "
        "all — accept it and build where it counts.",
        "Three Japanese carriers were lost inside about six minutes, to "
        "aircraft that had spent the morning getting lost. The Pacific war "
        "turned on a navigational accident."),

    Chapter(
        "El Alamein", "Supplies at Last",
        _mode("El Alamein", "no flank to turn",
              "Money and power, for once, in quantity.",
              lives=20, gold=260, power=24, target=12, hp_growth=1.20,
              speed=1.1, bounty=1.5, break_time=7.0),
        "Forty miles between the sea and a depression no tank can cross, so "
        "for once in North Africa there is no way round. Montgomery had "
        "supplies and would not move until he did. You have them too. Build "
        "in depth and grind.",
        "\"Before Alamein we never had a victory. After Alamein we never had "
        "a defeat.\" Churchill was overstating it, but not by very much."),

    Chapter(
        "Stalingrad", "The Last Block",
        _mode("Stalingrad", "rattenkrieg",
              "Rubble to build in, ruins you cannot, and no room to give.",
              lives=10, gold=190, power=20, target=12, hp_growth=1.21,
              speed=1.1, bounty=1.5, build_time=22.0, break_time=6.0),
        "The war of the rats: a front line that runs through factory floors "
        "and stairwells. Chuikov kept his men close enough to the Germans "
        "that their guns could not fire. The ruins are cover for them, not "
        "for you — build in the rubble between.",
        "Two hundred and ninety thousand men were surrounded and about five "
        "thousand came home, some of them a decade later."),

    Chapter(
        "Kursk", "The Prepared Ground",
        _mode("Kursk", "they know you are coming",
              "Open steppe, deep bays, and four months to dig.",
              lives=18, gold=240, power=22, target=13, hp_growth=1.21,
              speed=1.15, bounty=1.5, build_time=30.0, break_time=7.0),
        "The Soviets knew where the attack was coming and spent four months "
        "digging belts of trenches and wire across open wheat country. You "
        "get the same head start. Layer it — nothing here should have to be "
        "stopped by one line.",
        "The largest concentration of armour ever assembled ran into "
        "prepared defenses and stopped. After Kursk, Germany never mounted "
        "another strategic offensive in the east."),

    Chapter(
        "Dien Bien Phu", "The Guns in the Hills",
        _mode("Dien Bien Phu", "the valley floor",
              "They hold the high ground. All of it.",
              lives=10, gold=220, power=22, target=14, hp_growth=1.22,
              speed=1.15, bounty=1.5, break_time=6.0),
        "The garrison sits on the valley floor because nobody believed an "
        "army without trucks could get artillery onto the ridges. They "
        "carried it up by hand. The hills are theirs; the basin road is all "
        "you have. This is the last of it.",
        "The airstrip was unusable inside a week and the garrison was "
        "supplied by parachute until it wasn't. The campaign is over — and "
        "so, shortly afterwards, was French Indochina."),
]


def chapters() -> list[Chapter]:
    """Only the chapters whose map is actually installed.

    Someone who deletes `maps/09-gettysburg.map` should get a thirteen-battle
    campaign, not a crash between chapters eight and ten.
    """
    return [c for c in CHAPTERS if c.field is not None]


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


def default_path() -> str:
    base = os.environ.get("TTD_STORY")
    if base:
        return base
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(home, "ttd", "story.json")


class Progress:
    """How far through the campaign this machine has got.

    Everything here fails quietly, for the same reason the leaderboard does:
    an unwritable home directory should cost you a bookmark, never a run.
    """

    def __init__(self, path: str | None = None) -> None:
        self.path = path or default_path()
        self.cleared: set[str] = set()
        self.best: dict[str, int] = {}
        self.writable = True
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf8") as fh:
                raw = json.load(fh)
            self.cleared = set(raw.get("cleared", []))
            self.best = {k: int(v) for k, v in raw.get("best", {}).items()}
        except (OSError, ValueError, TypeError, AttributeError):
            self.cleared, self.best = set(), {}

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf8") as fh:
                json.dump({"version": 1, "cleared": sorted(self.cleared),
                           "best": self.best}, fh, indent=1)
            os.replace(tmp, self.path)
            return True
        except OSError:
            self.writable = False
            return False

    # -- queries ------------------------------------------------------------

    def is_cleared(self, ch: Chapter) -> bool:
        return ch.map_name in self.cleared

    def unlocked(self, ch: Chapter) -> bool:
        """The first chapter, everything cleared, and the one after the last
        thing you cleared. Nothing further, or there is no campaign left."""
        rows = chapters()
        i = rows.index(ch)
        return i == 0 or self.is_cleared(rows[i - 1]) or self.is_cleared(ch)

    def next_chapter(self) -> "Chapter | None":
        """Where the player left off — the first one not yet cleared."""
        return next((c for c in chapters() if not self.is_cleared(c)), None)

    @property
    def done(self) -> int:
        return sum(1 for c in chapters() if self.is_cleared(c))

    @property
    def complete(self) -> bool:
        rows = chapters()
        return bool(rows) and self.done == len(rows)

    # -- recording ----------------------------------------------------------

    def record(self, ch: Chapter, won: bool, score: int) -> bool:
        """File the result. Returns True when this run unlocked something."""
        fresh = won and not self.is_cleared(ch)
        if won:
            self.cleared.add(ch.map_name)
        if score > self.best.get(ch.map_name, 0):
            self.best[ch.map_name] = score
        self.save()
        return fresh
