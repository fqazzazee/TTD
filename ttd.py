#!/usr/bin/env python3
"""
TTD — Terminal Tower Defense
============================

    $ python3 ttd.py

Creeps walk a road from the entrance to your base. You spend gold on towers
placed on the grass beside it. Everything that gets through costs you lives.

This file is the front door: it owns the terminal, moves between screens, and
runs the frame loop. The interesting parts live next door —

    content.py   balance numbers, game modes, quotes
    terrain.py   the map format, the ground, and every battlefield on disk
    maps/*.map   the battlefields themselves, in plain text
    game.py      the rules, with no idea a terminal exists
    render.py    layout and drawing, with no idea of the rules
    theme.py     what this particular terminal can draw, and in what colours
    audio.py     synthesised blips and 8-bit music, through any player found
    scores.py    the persistent leaderboard

Set TTD_ASCII=1 to force plain ASCII if the glyphs render badly in your font,
TTD_SILENT=1 to keep it quiet, and TTD_NOMUSIC=1 for sound effects without
the chiptune. TTD_MAPS points the map loader somewhere else entirely.
"""

from __future__ import annotations

import curses
import locale
import random
import time

import audio
import render
import scores
import terrain
from content import (BUILDINGS, DEFEAT_QUOTES, MODES, VICTORY_QUOTES,
                     WAR_QUOTES)
from game import BUILD, WON, Game
from theme import Theme

FRAME_MS = 33                      # getch timeout, which also paces the game

# Movement keys: arrows, vi keys and WASD all do the same thing.
MOVES = {
    curses.KEY_UP: (-1, 0), curses.KEY_DOWN: (1, 0),
    curses.KEY_LEFT: (0, -1), curses.KEY_RIGHT: (0, 1),
    ord("k"): (-1, 0), ord("j"): (1, 0), ord("h"): (0, -1), ord("l"): (0, 1),
    ord("w"): (-1, 0), ord("s"): (1, 0), ord("a"): (0, -1), ord("d"): (0, 1),
}

ESC = 27


# ---------------------------------------------------------------------------
# Playing
# ---------------------------------------------------------------------------


def handle_key(g: Game, key: int, sound) -> str | None:
    """Apply one keypress.

    Returns a screen change when the player asks to leave, otherwise None.
    Anything that makes a noise does so here: the game itself only names the
    cue, it never touches the sound card.
    """
    if key in (ord("q"), ord("Q")) or key == ESC:
        return "pause"
    if key in MOVES:
        g.move_cursor(*MOVES[key])
    elif ord("1") <= key <= ord("0") + len(BUILDINGS):
        g.selected = key - ord("1")
        sound.play("select")
    elif key in (ord(" "), curses.KEY_ENTER, 10, 13):
        sound.play(g.build())
    elif key in (ord("u"), ord("U")):
        sound.play(g.upgrade())
    elif key in (ord("x"), ord("X")):
        sound.play(g.sell())
    elif key in (ord("n"), ord("N")):
        sound.play(g.call_wave())
    elif key in (ord("p"), ord("P")):
        return "pause"
    elif key in (ord("+"), ord("="), ord(".")):
        sound.play(g.change_speed(+1))
    elif key in (ord("-"), ord("_"), ord(",")):
        sound.play(g.change_speed(-1))
    elif key in (ord("s"), ord("S")):
        g.message = "Sound on." if sound.toggle() else "Sound off."
    elif key in (ord("m"), ord("M")):
        g.message = "Music on." if sound.toggle_music() else "Music off."
    return None


def announce(g: Game, cue: str) -> str:
    """What to say out loud when a cue fires, or "" to keep quiet.

    Only two things get announced. An narrator that reads out every explosion
    stops being dramatic by the third wave, and the one who only ever says
    what is about to walk in never does.
    """
    if cue == "wave":
        return f"Wave {g.wave}." + (" The Warlord comes." if g.boss_wave else "")
    if cue == "boss":
        return "Warlord."
    return ""


def battle_tune(g: Game) -> str:
    """Which loop suits the moment. The music escalates with the wave for the
    same reason the creeps do: by wave twelve it should not feel like wave one."""
    if g.state == BUILD:
        return "build"
    return "siege" if g.menace >= 2 or g.boss_wave else "battle"


PAUSE_ACTIONS = ["resume", "sound", "music", "help", "menu", "quit"]


def pause_menu(scr, theme: Theme, g: Game, sound) -> str:
    """Freeze the battle and put a menu over it.

    Returns 'resume', 'menu' or 'quit'. The clock does not move while this is
    up — `g.paused` sees to that — so nothing can walk in while the player is
    reading their own defenses.
    """
    was_paused = g.paused
    g.paused = True
    sel = 0
    scr.timeout(120)
    while True:
        items = [
            "RESUME",
            "SOUND            " + ("on" if sound.on else "off"),
            "MUSIC            " + ("on" if sound.music_on and sound.on else "off"),
            "HOW TO PLAY",
            "ABANDON THE RUN",
            "QUIT TTD",
        ]
        rows, cols = scr.getmaxyx()
        lay = render.plan(rows, cols, g.h, g.w)
        if lay is None:
            render.draw_too_small(scr, theme, *render.smallest_need(g.h, g.w))
        else:
            render.draw_game(scr, theme, g, lay, time.monotonic())
            render.pause_overlay(scr, theme, g, lay, items, sel)
        scr.refresh()

        key = scr.getch()
        if key in (curses.KEY_UP, ord("k")):
            sel = (sel - 1) % len(items)
        elif key in (curses.KEY_DOWN, ord("j")):
            sel = (sel + 1) % len(items)
        elif key in (ESC, ord("p"), ord("P")):
            break
        elif key in (curses.KEY_ENTER, 10, 13, ord(" ")):
            action = PAUSE_ACTIONS[sel]
            sound.play("select")
            if action == "resume":
                break
            if action == "sound":
                sound.toggle()
            elif action == "music":
                sound.toggle_music()
            elif action == "help":
                render.help_screen(scr, theme)
                scr.timeout(120)          # help_screen blocks; the menu breathes
            else:
                g.paused = was_paused
                return action

    g.paused = was_paused
    scr.timeout(FRAME_MS)
    return "resume"


def play(scr, theme: Theme, g: Game, sound) -> str:
    """Run one battle. Returns 'won', 'lost', 'menu' or 'quit'."""
    scr.timeout(FRAME_MS)
    last = time.monotonic()
    while True:
        sound.music(battle_tune(g))
        key = scr.getch()
        if key not in (-1, curses.KEY_RESIZE):
            leaving = handle_key(g, key, sound)
            if leaving == "pause":
                leaving = pause_menu(scr, theme, g, sound)
                last = time.monotonic()      # the pause is not battle time
            if leaving and leaving != "resume":
                return leaving

        now = time.monotonic()
        dt = min(now - last, 0.1)      # a stalled terminal must not teleport creeps
        last = now
        for cue in g.update(dt):       # the speed dial is applied inside
            sound.play(cue)
            sound.say(announce(g, cue))

        rows, cols = scr.getmaxyx()
        lay = render.plan(rows, cols, g.h, g.w)
        if lay is None:
            render.draw_too_small(scr, theme, *render.smallest_need(g.h, g.w))
        else:
            render.draw_game(scr, theme, g, lay, now)
        scr.refresh()

        if g.over:
            _hold(scr, theme, g, 0.9)
            return "won" if g.state == WON else "lost"


def _hold(scr, theme: Theme, g: Game, seconds: float) -> None:
    """Let the final frame sit for a moment before the screen changes."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        rows, cols = scr.getmaxyx()
        lay = render.plan(rows, cols, g.h, g.w)
        if lay:
            render.draw_game(scr, theme, g, lay, time.monotonic())
            scr.refresh()
        time.sleep(0.05)
        scr.getch()                    # swallow keys so they don't skip the quote


# ---------------------------------------------------------------------------
# Choosing a battlefield
# ---------------------------------------------------------------------------


def pick_map(rows: int, cols: int):
    """A random battlefield among those this terminal can display — the
    biggest that fits, so a roomy window gets a proper battle."""
    playable = [m for m in terrain.MAPS if render.fits(rows, cols, m.h, m.w)]
    if not playable:
        return None
    biggest = max((m.h, m.w) for m in playable)
    return random.choice([m for m in playable if (m.h, m.w) == biggest])


def wait_for_room(scr, theme: Theme):
    """Nag until the window can hold a battlefield, or the player quits."""
    scr.timeout(200)
    if terrain.MAPS:
        need = render.smallest_need(*min((m.h, m.w) for m in terrain.MAPS))
    else:
        need = (80, 24)
    while True:
        rows, cols = scr.getmaxyx()
        chosen = pick_map(rows, cols)
        if chosen:
            return chosen
        render.draw_too_small(scr, theme, *need)
        scr.refresh()
        if scr.getch() in (ord("q"), ord("Q")):
            return None


# ---------------------------------------------------------------------------
# The arc of a run
# ---------------------------------------------------------------------------


def run_campaign(scr, theme: Theme, mode, sound, board) -> str:
    """Play `mode` until the player stops. Returns 'menu' or 'quit'.

    Every run draws a fresh map, so the same rules are fought over different
    ground each time.
    """
    while True:
        chosen = wait_for_room(scr, theme)
        if chosen is None:
            return "quit"

        best = board.best(mode.name)
        sound.music("menu")
        key = render.quote_scene(
            scr, theme,
            header="BEFORE THE BATTLE",
            header_attr=theme.ink("title", bold=True),
            quote=random.choice(WAR_QUOTES),
            subtitle=f"{mode.name}  ·  {chosen.name}"
                     + (f"  ·  {chosen.when}" if chosen.when else "")
                     + (f"  ·  best {best:,}" if best else ""),
            footer="any key to take the field   ·   Q to withdraw",
            sound=sound,
        )
        if key in (ord("q"), ord("Q")):
            return "menu"

        g = Game(mode, chosen)
        outcome = play(scr, theme, g, sound)
        if outcome in ("menu", "quit"):
            return outcome

        won = outcome == "won"
        sound.music("menu")
        stat = f"{g.wave} waves held  ·  {g.kills} killed  ·  {g.score:,} points"
        key = render.quote_scene(
            scr, theme,
            header="THE FIELD IS YOURS" if won else "THE LINE HAS FALLEN",
            header_attr=theme.ink("good" if won else "blood", bold=True),
            quote=random.choice(VICTORY_QUOTES if won else DEFEAT_QUOTES),
            subtitle=stat,
            footer="ENTER to take the field again   ·   M for the menu   ·   Q to quit",
            sound=sound,
        )
        record_run(scr, theme, board, g, won, sound)
        if key in (ord("q"), ord("Q")):
            return "quit"
        if key in (ord("m"), ord("M"), ESC):
            return "menu"
        # anything else: another try, another map, another quote


def record_run(scr, theme: Theme, board, g: Game, won: bool, sound) -> None:
    """File the run, and let the player sign it if it made the table."""
    entry = scores.Entry(name=scores.default_name(), mode=g.mode.name,
                         map=g.map_name, wave=g.wave, score=g.score,
                         kills=g.kills, won=won)
    if not board.qualifies(entry):
        return
    sound.play("record")
    provisional = sorted(board.top(g.mode.name) + [entry],
                         key=lambda e: e.rank_key, reverse=True)
    place = provisional.index(entry) + 1
    signed = render.ask_name(scr, theme, entry.name, place)
    if signed is None:
        return                       # declined: the run goes unrecorded
    entry.name = signed
    board.add(entry)
    modes = list(MODES)
    render.scores_screen(scr, theme, board, modes,
                         modes.index(g.mode) if g.mode in modes else 0)


def app(scr) -> None:
    curses.curs_set(0)
    scr.keypad(True)
    if hasattr(curses, "set_escdelay"):
        curses.set_escdelay(50)     # otherwise ESC sits for a full second
    theme = Theme()
    sound = audio.Audio()
    board = scores.Board()

    try:
        while True:
            sound.music("menu")
            choice = render.title_screen(scr, theme)
            sound.play("select")
            if choice == "quit":
                return
            if choice == "help":
                render.help_screen(scr, theme)
                continue
            if choice == "scores":
                render.scores_screen(scr, theme, board, list(MODES))
                continue

            index = render.mode_screen(scr, theme, MODES)
            if index is None:
                continue
            if run_campaign(scr, theme, MODES[index], sound, board) == "quit":
                return
    finally:
        sound.close()


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "")     # let curses emit UTF-8
    curses.wrapper(app)
