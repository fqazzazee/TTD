# TTD — Terminal Tower Defense

Creeps walk a road from `»` to your base `⌂`. You spend gold on guns beside it.
Everything that gets through costs you lives.

TTD is a real-time tower defense game that runs in a terminal, fought over
sixteen real battlefields from Marathon in 490 BC to Dien Bien Phu in 1954.
Woods, bog, water and rock will not take a gun, and a weapon standing wholly on
high ground outranges one on the flat, so *where* you build is half of it.
There is a campaign through all sixteen battles, four skirmish rulesets, a map
editor, and every battlefield is a plain text file you can rewrite.

Pure Python standard library. No dependencies, no build step, no install.

**[Read the game guide →](GUIDE.md)**

## What you need

Python 3.9 or newer, and a terminal at least **46x16**. That is the whole list.
`curses` ships with Python on Linux, so there is nothing to `pip install`.

## Linux

Install Python, clone, run:

```sh
git clone https://github.com/fqazzazee/TTD.git
cd TTD
python3 ttd.py
```

Python is already there on almost every desktop install. If it isn't:

| | |
| --- | --- |
| Debian, Ubuntu, Mint, Pop!_OS | `sudo apt install python3 git` |
| Fedora, RHEL, Rocky, Alma | `sudo dnf install python3 git` |
| Arch, Manjaro, EndeavourOS | `sudo pacman -S python git` |
| openSUSE | `sudo zypper install python3 python3-curses git` |
| Alpine | `sudo apk add python3 git ncurses-terminfo-base` |
| Void | `sudo xbps-install python3 git` |

openSUSE and Alpine are the two that need something extra: openSUSE packages
`curses` separately, and Alpine ships no terminal descriptions by default.

## WSL

TTD runs under WSL 1 and WSL 2 alike. From PowerShell, if you don't already
have a distro:

```powershell
wsl --install -d Ubuntu
```

Then, inside it:

```sh
sudo apt update && sudo apt install -y python3 git
git clone https://github.com/fqazzazee/TTD.git
cd TTD
python3 ttd.py
```

Four things worth knowing:

**Use Windows Terminal**, not the old `conhost` console. It is the default on
Windows 11 and a free download on Windows 10. TTD checks what your terminal can
do and drops to a plainer look if it has to, and the legacy console will get you
the plainest one.

**Pick a font with box-drawing characters.** Cascadia Mono, which Windows
Terminal ships with, is fine. DejaVu Sans Mono has the widest coverage if any
glyphs come out as empty boxes. If the board looks skewed instead, the font is
rendering the geometric shapes double-width; run `TTD_ASCII=1 python3 ttd.py`
for a letters-only board that always lines up.

**Keep the clone in the Linux filesystem** (`~/TTD`), not under `/mnt/c`.
Windows-side paths are much slower to read, and TTD loads sixteen map files at
start-up.

**Sound needs WSL 2 with WSLg**, which comes with Windows 11 and recent
Windows 10 builds. Install a player with `sudo apt install pulseaudio-utils`
and you will get the music and the cues. On WSL 1, or without WSLg, the game is
simply silent and nothing else about it changes.

## Sound and voice (optional)

TTD synthesises its own audio at start-up and hands it to whatever player the
system already has. It ships no audio files and needs no library. If it finds
nothing, it is silent.

| Install any one of | for |
| --- | --- |
| `pipewire-utils`, `pulseaudio-utils`, `alsa-utils`, `sox`, `ffmpeg` | music and sound effects |
| `flite` | the announcer, in a real recorded voice |
| `espeak-ng` | the announcer, robotic but always available |

Package names follow the command names on every distro above. `flite` is the one
worth having: it names each wave in a human voice dragged four semitones down
into a growl.

## Running it

```sh
python3 ttd.py                   # the title screen: campaign, skirmish, editor
python3 editor.py                # the map editor on its own
python3 terrain.py               # list and check every installed map
python3 selftest.py              # 112 checks that need no terminal
```

Environment switches, if something looks or sounds wrong:

```sh
TTD_ASCII=1 python3 ttd.py       # plain letters, for stubborn fonts
TTD_SILENT=1 python3 ttd.py      # no sound at all
TTD_NOMUSIC=1 python3 ttd.py     # sound effects, but no music
TTD_NOVOICE=1 python3 ttd.py     # no spoken announcements
TTD_MAPS=~/battles python3 ttd.py    # load maps from somewhere else
```

Your own maps go in `~/.local/share/ttd/maps/`, where they override anything of
the same name that ships with the game. Scores and campaign progress live
alongside them in `~/.local/share/ttd/`.

## The guide

Everything else — the buildings and what they cost, the enemy, the campaign,
how to draw a battlefield, the map editor, and how a flat grid of characters is
made to look like ground — is in **[GUIDE.md](GUIDE.md)**.
