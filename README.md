# TTD — Terminal Tower Defense

A real-time tower defense game that runs in your terminal, fought over sixteen
real battlefields from Marathon to Dien Bien Phu. Pure Python standard library,
no dependencies, no install.

```
python3 ttd.py
```

Needs Python 3.9+ and a terminal at least **46x16**. It uses whatever room you
give it: a wide window gets a big battlefield with a full sidebar, a narrow one
gets a smaller map with a compact HUD, and resizing mid-battle is fine.

## Playing

Creeps walk the road from the entrance `»` to your base `⌂`. You spend gold on
towers placed on the ground beside it. Everything that gets through costs you
lives; at zero the run ends.

| Key | Action |
| --- | --- |
| `←↑↓→` / `hjkl` / `wasd` | move the build cursor |
| `1` `2` `3` `4` | choose what to build — its reach is previewed at the cursor |
| `Space` / `Enter` | put it down |
| `U` | upgrade what's under the cursor a mark, up to mk3 |
| `X` | sell it back at 60% |
| `N` | call the next wave early; the seconds you give up become gold |
| `+` `-` | run the battle faster or slower — 1x up to 4x |
| `S` `M` | mute the lot (cues, music, announcer), or just the music |
| `P` / `Esc` / `Q` | the pause menu |

Ground beside the road is not all the same. Most of a real battlefield is
wood, bog, water or rock, and none of it will take a gun; what is left is
worth arguing over. A weapon standing **wholly** on high ground sees further
than the same weapon on the flat, which is why armies spend so much of their
time walking uphill.

### What you build

Three currencies, not one. Gold you earn; power comes off the grid; ground beside
the road is finite. A Cannon covers four times the footprint of a Gun and draws
three times the power, so a line of heavy artillery needs a generator farm
behind it.

The three weapons are chess pieces, and the piece tells you the weight:

| | Building | Cost | Ground | Power | Notes |
| --- | --- | --- | --- | --- | --- |
| `♟` | Gun | $20 | 1x1 | −2 | pawn — quick bullets, cheap, close in |
| `♝` | Frost | $35 | 1x2 | −4 | bishop — freezes the ground around it |
| `♜` | Cannon | $55 | 2x2 | −6 | rook — slow shells, wide blast |
| `Ξ` | Generator | $40 | 2x2 | **+20** | not a weapon; feeds everything else |

In the ASCII tier they keep their chess notation: `P`, `B`, `R`.

The cursor is one cell but a Cannon is four, so the cursor only has to fall
*somewhere inside* the footprint — the block slides up and left to fit rather
than refusing because you happened to stand at the wrong corner of a clearing.
The ghost under the cursor is drawn on the ground it will actually take, and
the SITE panel says `fits` or `blocked` before you spend anything.

Each has three marks. `U` buys the next one. A mark costs more gold and more
power than the last, but **never more ground** — a mk3 Cannon stands on the same
2x2 as a mk1, so upgrading is how you get stronger once the good spots by the
road are gone.

| | mk1 | mk2 | mk3 |
| --- | --- | --- | --- |
| Gun | 6 dmg, reach 4.5 | 10 dmg, reach 5.0 | 16 dmg, reach 5.5 |
| Frost | field 2.5, ×0.65 speed | field 3.5, ×0.45 | field 4.5, ×0.30 |
| Cannon | 22 dmg, blast 2.2 | 34 dmg, blast 2.6 | 50 dmg, blast 3.0 |
| Generator | 20 power | 32 power | 46 power |

Frost does no damage. It paints the ground inside its field in ice — you can
see exactly where creeps will crawl — and a bigger mark covers more ground and
bites harder, for a lot more power.

Draw more power than you supply and nothing switches off; the whole defense
browns out together, guns reloading slower and frost fields thawing, down to a
floor of a quarter strength. It is a problem to fix, not a loss.

Weapons shoot whichever creep in range is nearest to your base. Shots travel
rather than landing instantly, so a tower can waste one on a creep that dies
before the shell arrives — and a Cannon shell still goes off where its mark
used to be, which is the point of splash.

### Pausing

`P` (or `Esc`, or `Q`) freezes the battle and puts a menu over the middle of the
board — resume, mute the sound or the music, read the controls, abandon the run,
or quit. The battlefield stays visible around it, because half of pausing is
standing back and looking at the line you have built. Nothing moves while it is
up: the clock stops, and the time you spent reading is not battle time.

There is no way to lose a run by mistake any more. `Q` mid-battle opens this
menu rather than quitting out from under you.

### The enemy

| | Creep | From | Costs | Notes |
| --- | --- | --- | --- | --- |
| `●` | Grunt | wave 1 | 1 life | the crowd — endless, unremarkable |
| `✦` | Runner | wave 3 | 1 life | twice the pace, half the health |
| `■` | Tank | wave 5 | 4 lives | slow armour, hard to shift |
| `†` | Reaper | wave 9 | 3 lives | fast *and* heavy — kill it early |
| `♛` | Warlord | wave 12 | 6 lives | the black queen, every fifth wave, walking in behind her army |

Each of them has three faces, wears the one its wave has earned, and **walks**
— every face is two frames that alternate as the thing covers ground:

| | recruit | veteran | elite |
| --- | --- | --- | --- |
| Grunt | `● •` | `◉ ◎` | `⊛ ⊗` |
| Runner | `✦ ✧` | `✷ ✶` | `✺ ✹` |
| Tank | `■ ▪` | `▣ ▤` | `▩ ▨` |
| Reaper | `† ✝` | `‡ ☨` | `☠ ✞` |
| Warlord | `♛ ♕` | | |

The gait is driven by distance covered rather than by the clock, so a creep
wading through a frost field visibly slows its step, and a paused game stands
perfectly still.

The sidebar carries an index of the whole roster — every creep, always in the
same order, so a glyph on the road can be looked up rather than remembered.
What is walking right now shows its count and its current face; what you have
met but is not in this wave sits dim; what has not turned up yet shows the
wave it starts at and keeps its recruit face, because the elite silhouette is
a surprise worth saving. In a window with no room for all five, the creeps
furthest from turning up drop out first, and the narrow HUD gets the same
index squeezed onto one line.

The Warlord steps between the black queen and the white one — the heavy
flicker a Nokia 3310 boss had — and drags her bulk behind her: the road cell
at her back is painted as her body, so she is two cells of presence walking
down a one-cell road. The rules never see it; she is a single creep like
everything else.

The silhouette stays in the same family the whole way — circles stay circles,
stars stay stars — so a Runner still reads as a Runner at wave 20; it has just
grown teeth. Veterans and elites darken the road they walk on, an elite's
outline pulses, and the sidebar retitles itself `INCOMING · ELITES`.

Rank is read off the *health a wave carries*, not its number, so it means the
same thing in every mode: twice the health of wave one and the ranks are
veterans, four times and they are elites. In Classic that is wave 6 and wave 11;
in Gauntlet, which escalates faster, wave 5 and wave 8. It is a matter of
appearance only — the danger was already in the health multiplier.

### The campaign

Sixteen battles, in the order they happened, from Marathon to Dien Bien Phu.
Each one is its own battlefield with its own rules, and the rules are picked
so that whatever decided the real thing decides this one too.

| | | |
| --- | --- | --- |
| I | **Marathon** | 490 BC — a short field and time to think |
| II | **Thermopylae** | 480 BC — almost no ground to build on, and it does not matter |
| III | **Gaugamela** | 331 BC — the biggest waves in the game across the flattest map |
| IV | **Cannae** | 216 BC — money for a deep line, and the sides are where you lose it |
| V | **Alesia** | 52 BC — the longest road in the game, walked from the outside in |
| VI | **Teutoburg** | AD 9 — little money, less warning, and trees on both sides |
| VII | **Hastings** | 1066 — a ridge worth reach, and a marsh for anyone who leaves it |
| VIII | **Agincourt** | 1415 — mud: everything slow, and a funnel pays for itself |
| IX | **Waterloo** | 1815 — hold until nightfall, and not one wave longer |
| X | **Gettysburg** | 1863 — a fishhook, and the hills that hold its ends |
| XI | **Rorke's Drift** | 1879 — one small perimeter, overlooked, all night |
| XII | **Midway** | 1942 — one island, no room, no second chance |
| XIII | **El Alamein** | 1942 — supplies, and plenty of them, for the first time |
| XIV | **Stalingrad** | 1942 — rubble to build in, ruins you cannot, no room to give |
| XV | **Kursk** | 1943 — they know you are coming, and you get to dig first |
| XVI | **Dien Bien Phu** | 1954 — the valley floor, and they hold every hill above it |

Every chapter ends: hold the stated number of waves and it is won, and
winning opens the next. Losing takes nothing away — the chapter is still
there, and so is everything you cleared before it. Progress lives in
`~/.local/share/ttd/story.json` (override with `TTD_STORY`).

There is a page of history before each battle and another one after it. They
are short on purpose: a briefing, not a lecture.

### Skirmish

One-off battles, on any map you like, under one of four sets of rules:

| Mode | |
| --- | --- |
| **Classic** | endless waves at a fair pace — start here |
| **Blitz** | everything faster, breaks short, gold doubled |
| **Gauntlet** | hold for 20 waves and you win; the only mode with an ending |
| **Last Stand** | three lives, plenty of gold, no mercy |

Pick the battlefield yourself, or leave it on *a battlefield at random* and
every run draws the largest map your window can hold — so a bigger terminal
means a bigger battle rather than just more whitespace.

The speed dial only buys you time. Everything in the simulation is clocked off
one scaled game clock, and long steps are chopped up before they are simulated,
so running at 4x is exactly the same battle as running at 1x — just quicker.

## Sound and scores

Sound is synthesised at start-up into a handful of short WAV files and handed to
whatever player the system has — `pw-play`, `paplay`, `aplay`, `afplay`, `play`
or `ffplay`. If none is installed the game is simply silent. Cues fire on events
you would notice, never on individual bullets, and each is throttled.

The music is four 8-bit loops, written as a three-line tracker at the bottom of
`audio.py`: a 25% pulse lead, a triangle bass, and noise drums. One is baked to
a WAV the first time it is asked for and kept looping by a background thread,
so nothing in the game has to think about it beyond naming a tune.

| Tune | |
| --- | --- |
| `menu` | the title, the mode list, the quotes — slow, minor, wistful |
| `build` | between waves; you are spending money, not dying |
| `battle` | a wave is walking, at 144bpm with a running bass |
| `siege` | elites and Warlords — Phrygian, and that flat second is the point |

The music escalates with the wave for the same reason the creeps do: by wave
twelve it should not sound like wave one. `M` mutes it on its own; `TTD_NOMUSIC=1`
starts without it.

**The typewriter.** Quotes type themselves out over a loop of type-bar clatter
— a hammer strike about ten times a second, with a bell when the carriage comes
back. It is one baked loop started when the letters start and cut off when they
stop, not a process per keystroke: a quote is a few hundred characters, and a
few hundred processes is a fork bomb with good intentions.

**The announcer.** If the system can speak, the game talks. It names the
author when a quote finishes typing, calls each wave as it forms up, and names
the Warlord when she walks. That is all it says; a narrator who reads out
every explosion stops being dramatic by the third wave. Announcements are
dropped rather than queued, so they never pile up or talk over each other.

The voice is a real one. TTD looks for a speech command in order of how human
it sounds, preferring the ones built from recorded people over the ones that
model a throat:

| | |
| --- | --- |
| `flite -voice rms` | **preferred** — the CMU ARCTIC recordings: one man, recorded properly, free to use |
| `say` | macOS, and very good |
| `pico2wave` | SVOX Pico, small and natural |
| `espeak-ng` / `espeak` | formant synthesis; robotic, but always there |
| `spd-say` | last resort, and the only one that cannot be processed |

Whatever comes out is then dragged into the cellar before you hear it. The
line is written to a WAV, played back at 0.78 speed — four semitones down and
a quarter longer — with a second copy 2% off the first so the two beat against
each other into a growl, an 85ms echo to put it in a much larger room, and a
24Hz shudder over the top. It stays intelligible on purpose: a demon nobody
can understand is just noise. Each line is synthesised once and kept, since
the same handful come round every run.

None of this ships any audio. `apt install flite` (or `brew install flite`)
buys you the human voice; with nothing installed the game is simply quiet, and
`TTD_NOVOICE=1` keeps it that way on purpose.

High scores live in `~/.local/share/ttd/scores.json` (override with `TTD_SCORES`),
ten per mode. Make the table and you are asked to sign it. An unwritable or
corrupt file costs you the record, never the run.

## Layout of the code

`ttd.py` is the entry point. The rest splits along one line: the rules do not
know a terminal exists, and the renderer does not know the rules.

| File | |
| --- | --- |
| `ttd.py` | owns the terminal, moves between screens, runs the frame loop |
| `content.py` | balance, modes and the words between the fighting |
| `terrain.py` | the map format: ground, the road tracer, relief, loading |
| `maps/*.map` | the battlefields themselves, in plain text |
| `story.py` | the campaign, and what is remembered between runs |
| `game.py` | the simulation: creeps, towers, waves, gold, lives |
| `render.py` | layout and drawing, including the menus and the typewriter |
| `editor.py` | drawing maps without leaving the game |
| `theme.py` | what this terminal can draw, and in what colours |
| `audio.py` | synthesised blips and the chiptune, through whatever player exists |
| `scores.py` | the persistent leaderboard |
| `selftest.py` | checks that need no terminal — run it after changing anything |
| `preview.py` | dev tool: renders one screen and prints it as text |
| `ptydrive.py` | dev tool: plays the real game in a pty and greps the screen |

To change how the game *plays*, you need `content.py`. To change *where* it is
played, you need a text editor and the `maps/` directory.

```
python3 selftest.py                # maps trace, layouts fit, the game can be lost
python3 terrain.py                 # list every map, and say what is wrong with the bad ones
python3 terrain.py Cannae          # print one, header and all
python3 editor.py                  # the map editor on its own
python3 preview.py board 120 34    # battlefield mid-firefight
python3 preview.py map:Midway 120 34    # any battlefield by name
python3 preview.py story 90 34     # the campaign menu
python3 preview.py maps 90 34      # the battlefield chooser
python3 preview.py editor 110 30   # the map editor
python3 preview.py compact 60 16   # the narrow HUD
python3 preview.py elite 120 36    # a wave-12 board: elites and a Warlord
python3 preview.py pause 120 36    # the pause menu over a frozen battle
python3 ptydrive.py                # drives the real binary through the menus
```

## Drawing a map

A map is a text file. Open `maps/06-hastings.map` in anything and you will see
the whole format:

```
name: Hastings
when: 1066
where: Senlac Hill, Sussex
who: Harold's housecarls vs William of Normandy
road: mud
brief: Harold held the ridge with a shield wall and lost it to a feigned
---
S####################################
...TTTT.......................T.....#
....................................#
#####################################
#..hhhhhhhhhhhhhhhhhhhhhhhhhhhh......#
```

A few `key: value` lines, a line of `---`, and then the ground. Only `name` is
required; a file with no header at all is read as pure art and named after
itself.

### The alphabet

| | | |
| --- | --- | --- |
| `S` | the entrance | creeps walk in here |
| `E` | your base | and this is what they are walking to |
| `#` | road | you cannot build on it |
| `.` | grass | open ground |
| `,` | sand | open ground |
| `"` | scrub | open ground — dry steppe |
| `*` | snow | open ground |
| `:` | rubble | open ground — broken stone, still firm |
| `h` | hill | open ground, **and weapons on it see further** |
| `T` | forest | blocked |
| `^` | mountain | blocked |
| `~` | water | blocked |
| `%` | marsh | blocked |
| `=` | ruins | blocked |

Short rows are padded out with the map's own ground (set `fill:` to choose
which), so the art only has to be exact where the road and the scenery are.
`road:` picks how the road looks — `dust`, `mud`, `stone`, `snow`, `sand`,
`water` or `grass` — and is cosmetic; every road plays the same.

### The one rule

Draw a single-width corridor from `S` to `E` with no forks, and the loader
traces it into a route by itself. That trace is the only pathfinding anywhere
in the game. Two road cells that touch but are not consecutive are a fork, and
a fork has no answer to "where does this creep go next", so leave at least one
cell of ground between parallel stretches of road.

```
python3 terrain.py
```

lists every map it can find and, for the ones it cannot load, says which row
and column to look at. A broken map is set aside; it never takes the game
down with it.

Creep speed is scaled by path length, so a map four times longer does not make
the game four times easier. Draw them in whatever size you like — anything
from 10x5 up to 220x90.

### Where maps come from

Two directories are read, in order, and the later one wins a name clash:

```
./maps/                       what ships with the game
~/.local/share/ttd/maps/      yours
```

So dropping your own `Cannae.map` in the second one quietly replaces the one
that ships; deleting it puts the original back. `TTD_MAPS` (colon-separated)
replaces the search path entirely.

## The map editor

`MAP EDITOR` on the title screen, or `python3 editor.py` on its own.

Everything it does you could do in a text editor. What it adds is that you see
the ground lit the way the game will light it, and it tells you the moment the
road stops joining up.

The brush is a map character and you choose it by typing it: `T` paints a
wood, `~` water, `^` mountains, `#` road. Which means the arrow keys do the
moving, since `h` is a hill here and not a direction.

| Key | |
| --- | --- |
| arrows | move |
| `Space` | paint  ·  `Tab` cycles the brush |
| `D` | keep painting as you move |
| `[` `]` `{` `}` | wider, narrower, taller, shorter |
| `V` | check that the road joins up |
| `W` | write it to disk |
| `U` | undo |
| `N` `O` `M` | new  ·  open  ·  name and notes |
| `?` | the key list |
| `Esc` | leave |

Saved maps go to `~/.local/share/ttd/maps/`, so they are picked up by the map
chooser the next time you look at it.

## How it looks

The board is flat characters, so height has to be faked, and it is faked the
way a painting fakes it: one light source that never moves.

Every kind of ground carries three colours — the face in shadow, the face
lying flat, the face catching the light — and each cell picks one of the three
from how tall its neighbours are. The light comes from the top left, always,
so a cell below or to the right of something taller sits in its shadow and a
cell that rises above its neighbours takes the light on its near edge. That is
the whole trick, and it is worked out once when the map loads, because terrain
does not move.

Everything else follows from it. Mountains cast further than hills. A wood has
a dark side. A shoreline reads as an edge instead of a colour change. Anything
you build gets a lit lip along its top and throws its own shadow onto the
ground down and to the right — the one thing that most makes a tower look like
it is standing on the field rather than printed on it. Water and marsh are the
only ground that moves.

Flat country is mottled rather than uniform, from a hash of each cell's
coordinates, so an open plain has texture without ever flickering between
frames.

## If it looks wrong

The game picks the best of three tiers at start-up: Unicode with 256 colours,
Unicode with 8, or plain ASCII with none. In the eight-colour tier the three
shades collapse into dim, plain and bold, which says less but says the same
thing. If your font renders the geometric shapes double-width and skews the
board, force the bottom tier:

```
TTD_ASCII=1 python3 ttd.py
TTD_SILENT=1 python3 ttd.py      # no sound at all
TTD_NOMUSIC=1 python3 ttd.py     # cues, but no music
TTD_NOVOICE=1 python3 ttd.py     # no spoken announcements
TTD_MAPS=~/battles python3 ttd.py    # read maps from somewhere else entirely
```

In the ASCII tier the creeps keep their three ranks as letters and symbols —
`o 0 8`, `x y &`, `t T H`, `v V %`, and `W` for the Warlord. They do not
animate there: two letters swapping back and forth at walking pace reads as
noise rather than motion, and that tier's whole job is to stay legible.
