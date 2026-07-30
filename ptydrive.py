#!/usr/bin/env python3
"""
Drive the real game in a pty and report what the screen said.

    python3 ptydrive.py

Dev tool. Each scenario is a window size and a script of (delay, keys); after
the last one the screen is read back and grepped for the things that scenario
is supposed to prove. Nothing here is imported by the game.
"""
import fcntl, os, pty, signal, struct, sys, termios, time

ENTER, ESC = b"\r", b"\x1b"
DOWN, UP = b"\x1bOB", b"\x1bOA"      # keypad(True) means application-cursor mode

# Title -> SKIRMISH -> Classic -> a battlefield at random -> the quote, skipped
# and then dismissed. Every battle scenario starts with this, so when the
# menus move there is one place to fix it.
TO_BATTLE = [(1.0, [DOWN, ENTER]), (0.6, ENTER), (0.8, ENTER),
             (3.0, [ENTER, ENTER])]


def run(name, cols, rows, script, env=None, seconds=0.6):
    """Play the script, then hand back the final screen as text."""
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update({"TERM": "xterm-256color", "TTD_SILENT": "1"})
        os.environ.update(env or {})
        os.execv(sys.executable, [sys.executable, "ttd.py"])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    # Non-blocking, or a screen that stops redrawing — anything sitting on a
    # blocking getch, like the help screen — wedges this harness forever.
    fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)

    buf = b""

    def drain(seconds):
        nonlocal buf
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                buf += os.read(fd, 65536)
            except BlockingIOError:
                time.sleep(0.02)
            except OSError:
                return

    for delay, keys in script:
        drain(delay)
        # One key per write, with a beat between them. Four arrow sequences in
        # a single write and curses swallows one while it is deciding whether
        # an ESC starts a sequence or stands alone.
        for key in ([keys] if isinstance(keys, bytes) else keys):
            try:
                os.write(fd, key)
            except OSError:
                break
            drain(0.15)
    drain(seconds)
    try:
        os.kill(pid, signal.SIGKILL)
        os.close(fd)
    except OSError:
        pass
    os.waitpid(pid, 0)
    return buf.decode("utf8", "replace")


def check(name, text, wanted, forbidden=()):
    missing = [w for w in wanted if w not in text]
    present = [w for w in forbidden if w in text]
    ok = not missing and not present
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    if missing:
        print(f"          missing: {missing}")
    if present:
        print(f"          should not be there: {present}")
    return ok


SCENARIOS = []


def scenario(fn):
    SCENARIOS.append(fn)
    return fn


@scenario
def pause_menu():
    """P opens the menu, arrows move in it, ESC puts you back in the battle."""
    text = run("pause", 110, 32, TO_BATTLE + [
        (2.0, b"p"),           # into the battle, then pause
        (0.8, [DOWN, DOWN]),   # down to MUSIC
        (0.5, ENTER),          # toggle it
        (0.5, ESC),            # back to the battle
        (1.0, b"p"),           # and pause again to prove it still opens
    ])
    return check("P pauses, the menu answers arrows, ESC resumes", text,
                 ["PAUSED", "RESUME", "ABANDON THE RUN", "MUSIC"])


@scenario
def abandon():
    """ABANDON THE RUN walks back to the title screen instead of quitting."""
    text = run("abandon", 110, 32, TO_BATTLE + [
        (2.0, b"p"),
        (0.8, [DOWN] * 4),     # RESUME -> SOUND -> MUSIC -> HOW TO PLAY -> ABANDON
        (0.5, ENTER),
        (1.5, b""),
    ])
    return check("ABANDON THE RUN returns to the menu", text,
                 ["T E R M I N A L   T O W E R   D E F E N S E", "HIGH SCORES"])


@scenario
def help_from_pause():
    """The controls are reachable without leaving the run."""
    text = run("help", 110, 34, TO_BATTLE + [
        (2.0, b"p"),
        (0.8, [DOWN] * 3),
        (0.5, ENTER),
        (1.2, ESC),
        (0.8, b""),
    ])
    return check("HOW TO PLAY opens over a paused run", text,
                 ["HOW TO HOLD A LINE", "PAUSED"])


@scenario
def ascii_tier():
    """The whole thing still runs with no Unicode at all."""
    text = run("ascii", 100, 30, TO_BATTLE + [
        (2.0, b"p"),
        (1.0, ESC),
        (1.0, b""),
    ], env={"TTD_ASCII": "1"})
    return check("the ASCII tier reaches the pause menu", text,
                 ["PAUSED", "RESUME"], forbidden=["Traceback"])


@scenario
def no_crash_at_speed():
    """Four times speed for a while, with a pause in the middle of it."""
    text = run("speed", 120, 36, TO_BATTLE + [
        (0.5, [b"+"] * 4),
        (6.0, b"p"),
        (0.8, ESC),
        (6.0, b""),
    ])
    return check("a fast run survives being paused mid-wave", text,
                 ["TTD"], forbidden=["Traceback", "curses.error"])


@scenario
def quote_typewriter():
    """The quote types itself out with the machine running under it.

    Sound is left on for this one — the point is that starting the clatter,
    stopping it and reading the name out does not disturb the typing.

    Only text drawn in one go can be asserted on here. Curses ships the
    difference between frames, so a line revealed one character at a time
    arrives as a stream of single letters and never appears whole. Use
    `preview.py quote` to read the finished screen itself.
    """
    text = run("quote", 100, 30, [
        (1.0, [DOWN, ENTER]), (0.6, ENTER), (0.8, ENTER),
        (6.0, ENTER),          # let the whole quote type itself
        (1.0, ENTER),          # then dismiss it
        (1.5, b"p"),
    ], env={"TTD_SILENT": "", "TTD_NOVOICE": "1"})
    return check("a quote types out and the battle follows it", text,
                 ["BEFORE THE BATTLE", "any key to take the field",
                  "PAUSED", "RESUME"],
                 forbidden=["Traceback"])


@scenario
def campaign():
    """The campaign opens on its first battle and briefs before it starts."""
    text = run("story", 110, 34, [
        (1.0, ENTER),          # title: THE CAMPAIGN
        (1.0, ENTER),          # the chapter list: whatever is unlocked
        (1.2, ENTER),          # the briefing
        (2.0, b"p"),
    ], env={"TTD_STORY": "/dev/null"})
    return check("the campaign briefs a chapter and starts it", text,
                 ["THE CAMPAIGN", "battles won", "Marathon", "PAUSED"],
                 forbidden=["Traceback"])


@scenario
def map_choice():
    """A skirmish can be pinned to one named battlefield."""
    text = run("maps", 110, 34, [
        (1.0, [DOWN, ENTER]),  # title: SKIRMISH
        (0.6, ENTER),          # modes: Classic
        (0.8, [DOWN, DOWN]),   # random -> Marathon -> Thermopylae
        (0.5, ENTER),
        (3.0, [ENTER, ENTER]),
        (2.0, b"p"),
    ])
    return check("choosing a battlefield takes you to that one", text,
                 ["CHOOSE A BATTLEFIELD", "Thermopylae", "PAUSED"],
                 forbidden=["Traceback"])


@scenario
def editor_opens():
    """The editor loads a map, paints, and validates without leaving curses."""
    text = run("editor", 110, 30, [
        (1.0, [DOWN, DOWN, DOWN, ENTER]),   # title: MAP EDITOR
        (0.8, b"T"),                        # brush: forest
        (0.4, b" "),                        # paint
        (0.4, b"v"),                        # check the road
        (0.8, b"?"),                        # the key list
        (0.8, ESC),
    ])
    return check("the editor opens, paints and checks a map", text,
                 ["MAP EDITOR", "BRUSH", "THE EDITOR"],
                 forbidden=["Traceback", "curses.error"])


if __name__ == "__main__":
    print("driving the real binary in a pty")
    ok = all([fn() for fn in SCENARIOS])
    print("\nall good" if ok else "\nsomething is wrong")
    sys.exit(0 if ok else 1)
