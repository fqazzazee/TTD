#!/usr/bin/env python3
"""
Render a scene into a real curses screen inside a pty, then read the screen
back and print it as text. Dev tool for eyeballing layout without playing.

    python3 preview.py board 120 30
    python3 preview.py board 80 24
    python3 preview.py compact 60 16
    python3 preview.py title 80 24
    python3 preview.py modes 80 24
    python3 preview.py help 90 34
    python3 preview.py quote 80 24
    python3 preview.py elite 120 36    # a late wave: elite creeps and a Warlord
    python3 preview.py pause 120 36    # the pause menu over a frozen battle
"""
import curses, fcntl, os, pty, random, struct, sys, tempfile, termios, time


def child(scene, cols, rows, outfile):
    import render
    from content import MAPS, MODES, WAR_QUOTES, build_wave
    from game import WAVE, Game
    from theme import Theme

    def body(scr):
        curses.curs_set(0)
        theme = Theme()
        random.seed(4)
        if scene in ("board", "compact", "level", "pause", "elite"):
            # Biggest map this window can hold, exactly as the game picks one.
            wanted = MAPS[0] if scene == "compact" else MAPS[4]
            g = Game(MODES[2] if scene == "level" else MODES[0], *wanted)
            if not render.fits(rows, cols, g.h, g.w):
                for name, art in MAPS:
                    probe = Game(g.mode, name, art)
                    if render.fits(rows, cols, probe.h, probe.w):
                        g = probe
                        break
            lay = render.plan(rows, cols, g.h, g.w)
            g.gold = 99999

            # A working base: generators for the grid, a mixed line of
            # weapons beside the road, some of them upgraded.
            ground = [(y, x) for y in range(g.h) for x in range(g.w)
                      if not g.is_path(y, x)]
            near = [(y, x) for (y, x) in ground if any(
                0 <= p < g.h and 0 <= q < g.w and g.is_path(p, q)
                for p, q in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)))]
            for pick, count in ((3, 3), (2, 2), (1, 2), (0, 8)):
                placed = 0
                for (y, x) in random.sample(ground if pick == 3 else near,
                                            len(ground if pick == 3 else near)):
                    if placed >= count:
                        break
                    g.cy, g.cx, g.selected = y, x, pick
                    if g.build() == "build":
                        placed += 1
            for i, anchor in enumerate(list(g.buildings)):
                if i % 3 == 0:
                    g.cy, g.cx = anchor
                    g.upgrade()
                    g.upgrade()

            g.timer = 0.0
            if scene in ("pause", "elite"):
                # Drop straight into a late wave: elites on the road and a
                # Warlord behind them, without simulating eleven waves first.
                g.wave = 12
                g.queue, g.hp_mult = build_wave(g.mode, g.wave)
                g.wave_total = len(g.queue)
                g.state, g.spawn_at = WAVE, g.clock
                for _ in range(1500):
                    g.update(1 / 30)
                    if any(e.spec.name == "Warlord" and e.dist > 3 for e in g.enemies):
                        break                    # far enough in to see her bulk
            else:
                for _ in range(3000):
                    g.update(1 / 30)
                    if len(g.shots) >= 2 and g.effects:
                        break
            g.cy, g.cx, g.selected = min(2, g.h - 1), min(8, g.w - 1), 2
            g.message = (f"wave {g.wave}, menace {g.menace}, "
                         f"{len(g.enemies)} on the road")
            render.draw_game(scr, theme, g, lay, time.monotonic())
            if scene == "pause":
                render.pause_overlay(scr, theme, g, lay, [
                    "RESUME", "SOUND            on", "MUSIC            on",
                    "HOW TO PLAY", "ABANDON THE RUN", "QUIT TTD"], 0)
        elif scene == "title":
            scr.timeout(1)
            render.title_screen(scr, theme)
        elif scene == "modes":
            scr.timeout(1)
            render.mode_screen(scr, theme, MODES)
        elif scene == "scores":
            import scores as sc
            board = sc.Board(os.path.join(tempfile.gettempdir(), "ttd-preview.json"))
            board.entries = [
                sc.Entry("hannibal", "Classic", "Coil", 31, 4820, 402, False,
                         1751000000),
                sc.Entry("zhukov", "Classic", "Spiral", 24, 3110, 288, False,
                         1752000000),
                sc.Entry("tesla", "Classic", "Labyrinth", 20, 2740, 250, True,
                         1753000000),
                sc.Entry("scipio", "Classic", "Brook", 12, 900, 96, False,
                         1754000000),
            ]
            board.writable = True
            scr.timeout(1)
            render.scores_screen(scr, theme, board, MODES)
        elif scene == "name":
            scr.timeout(1)
            render.ask_name(scr, theme, "tesla", 2)
        elif scene == "help":
            scr.timeout(1)
            render.help_screen(scr, theme)
        elif scene == "quote":
            scr.timeout(1)
            render.quote_scene(scr, theme, "BEFORE THE BATTLE",
                               theme.ink("title", bold=True), WAR_QUOTES[12],
                               "Classic  ·  Spiral", "any key to take the field")
        scr.refresh()
        real_rows, real_cols = scr.getmaxyx()
        with open(outfile, "w") as fh:
            fh.write(f"[curses sees {real_cols}x{real_rows}]\n")
            for y in range(rows):
                try:
                    # instr() counts *bytes*, so ask for the whole line.
                    fh.write(scr.instr(y, 0).decode("utf8", "replace").rstrip() + "\n")
                except curses.error:
                    fh.write("\n")

    curses.wrapper(body)


if __name__ == "__main__":
    scene = sys.argv[1] if len(sys.argv) > 1 else "board"
    cols = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    rows = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    tmp = tempfile.mktemp(suffix=".txt")
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        import locale
        locale.setlocale(locale.LC_ALL, "")
        try:
            child(scene, cols, rows, tmp)
        except BaseException:
            import traceback
            open(tmp, "w").write(traceback.format_exc())
        os._exit(0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    # Enough keys to skip a typewriter and then dismiss whatever it typed.
    for _ in range(3):
        time.sleep(1.5)
        try:
            os.write(fd, b"\r")
        except OSError:
            break
    time.sleep(0.5)
    try:
        os.close(fd)
    except OSError:
        pass
    os.waitpid(pid, 0)
    print(open(tmp).read() if os.path.exists(tmp) else "(nothing rendered)")
