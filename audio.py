"""
Sound, if this machine can make any.

There is no portable way to make a noise from a terminal program, so this does
the next best thing: it synthesises a handful of short WAV files at start-up
and hands them to whatever command-line player the system happens to have.
No dependencies, nothing to install, and a silent no-op when nothing is found.

Two rules keep it from becoming a problem:

    Nothing per-bullet.  Cues fire on events a player would notice — building,
                         a leak, a wave starting — never on every shot.
    Everything throttled. Each cue has a minimum gap, and only a few players
                         may run at once, so a busy battle cannot fork-bomb.

There is music too — four square-wave loops written out as a three-line
tracker at the bottom of this file. A daemon thread bakes them on demand and
keeps the loop alive, so screens that own their own key loops never have to
think about it: they just say which tune they want.

It also talks, when the system has a text-to-speech command to talk with:
the wave number, the name on a quote, the thing that just walked onto the
road. Announcements are dropped rather than queued.

Set TTD_SILENT=1 to keep it quiet, TTD_NOMUSIC=1 for cues without music, or
TTD_NOVOICE=1 to keep the announcements off.
"""

from __future__ import annotations

import array
import atexit
import math
import os
import random
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from dataclasses import dataclass

RATE = 11025            # plenty for blips, and keeps the files tiny
MAX_VOICES = 4          # concurrent player processes

# Players in order of preference. Each entry is (command, extra arguments).
PLAYERS = [
    ("pw-play", ["--volume", "0.6"]),
    ("paplay", []),
    ("aplay", ["-q"]),
    ("afplay", []),
    ("play", ["-q"]),
    ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
]

# A cue is (segments, waveform, volume, gap) where each segment glides from one
# frequency to another over a number of seconds, and `gap` is the shortest time
# allowed between two plays of that cue.
CUES = {
    "move":    ([(880, 880, 0.012)], "sine", 0.10, 0.03),
    "select":  ([(660, 990, 0.055)], "sine", 0.22, 0.05),
    "build":   ([(440, 700, 0.070)], "sine", 0.30, 0.05),
    "sell":    ([(700, 330, 0.090)], "sine", 0.26, 0.05),
    "upgrade": ([(523, 784, 0.070), (784, 1175, 0.090)], "sine", 0.30, 0.05),
    "deny":    ([(180, 150, 0.110)], "square", 0.16, 0.12),
    "power":   ([(320, 200, 0.180), (200, 320, 0.180)], "square", 0.16, 1.50),
    "wave":    ([(300, 300, 0.090), (400, 400, 0.140)], "square", 0.18, 0.40),
    "boom":    ([(140, 60, 0.130)], "noise", 0.24, 0.35),
    "leak":    ([(260, 90, 0.240)], "sine", 0.34, 0.20),
    "cleared": ([(523, 523, 0.080), (659, 659, 0.080), (880, 880, 0.160)],
                "sine", 0.30, 0.40),
    "defeat":  ([(330, 220, 0.300), (220, 70, 0.550)], "sine", 0.38, 1.00),
    "victory": ([(523, 523, 0.130), (659, 659, 0.130), (784, 784, 0.130),
                 (1046, 1046, 0.340)], "sine", 0.36, 1.00),
    "record":  ([(784, 784, 0.090), (1046, 1046, 0.090), (1318, 1318, 0.220)],
                "sine", 0.32, 1.00),
    "boss":    ([(110, 110, 0.320), (98, 98, 0.320), (73, 73, 0.640)],
                "square", 0.30, 2.00),
}


def _render(segments, kind: str, volume: float) -> bytes:
    """Turn a cue description into 16-bit mono PCM."""
    samples: list[float] = []
    phase = 0.0
    for f0, f1, dur in segments:
        n = max(1, int(dur * RATE))
        for i in range(n):
            t = i / n
            phase += 2 * math.pi * (f0 + (f1 - f0) * t) / RATE
            if kind == "sine":
                samples.append(math.sin(phase))
            elif kind == "square":
                samples.append(1.0 if math.sin(phase) > 0 else -1.0)
            else:
                samples.append(random.uniform(-1.0, 1.0))

    # A quick attack and a long decay: without them every cue starts and ends
    # on a click, which is far more noticeable than the tone itself.
    total = len(samples)
    attack = max(1, int(0.004 * RATE))
    pcm = array.array("h")
    for i, s in enumerate(samples):
        env = min(1.0, i / attack) * (1.0 - i / total) ** 1.5
        pcm.append(int(max(-1.0, min(1.0, s * env * volume)) * 32767))
    return pcm.tobytes()


# ---------------------------------------------------------------------------
# Music: a three-line tracker
# ---------------------------------------------------------------------------
#
# Each tune is three parallel lines of tokens, one token per eighth note:
#
#     "A4"   strike that note        "."   hold the one before it
#     "-"    silence                 drums: "k" kick, "s" snare, "h" hat
#
# Lead is a 25% pulse (the thin, reedy NES voice), bass is a triangle, drums
# are shaped noise. That is the whole synthesiser, and it is enough.

SEMITONES = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4,
             "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}


def note_hz(token: str) -> float:
    """'A4' -> 440.0, 'A#2' -> 116.5. Sharps only; no one needs flats here."""
    return 440.0 * 2 ** ((SEMITONES[token[:-1]] + 12 * (int(token[-1]) - 4)) / 12)


@dataclass(frozen=True)
class Tune:
    bpm: int
    lead: str
    bass: str
    drums: str
    volume: float = 0.18


TUNES = {
    # Menus and quotes: slow, minor, a little wistful. Am — F — C — G.
    "menu": Tune(
        bpm=96, volume=0.20,
        lead="A4 .  C5 E5 .  .  B4 .   A4 .  F4 A4 .  .  C5 .  "
             "E5 .  D5 C5 .  .  G4 .   A4 .  B4 C5 .  .  .  .  ",
        bass="A2 .  .  .  E2 .  .  .   F2 .  .  .  C3 .  .  .  "
             "C3 .  .  .  G2 .  .  .   G2 .  .  .  E2 .  .  .  ",
        drums="-  -  h  -  -  -  h  -   -  -  h  -  -  -  h  -  "
              "-  -  h  -  -  -  h  -   -  -  h  -  -  -  h  h  "),

    # Between waves: you are spending money, not dying. Warmer, still tense.
    "build": Tune(
        bpm=104, volume=0.18,
        lead="E4 .  G4 .  A4 .  G4 .   E4 .  D4 .  E4 .  .  .  "
             "C5 .  E5 .  G4 .  E4 .   D4 .  .  .  .  .  .  .  ",
        bass="C3 .  .  .  G2 .  .  .   A2 .  .  .  E2 .  .  .  "
             "F2 .  .  .  C3 .  .  .   G2 .  .  .  G2 .  .  .  ",
        drums="k  -  -  -  h  -  -  -   k  -  -  -  h  -  -  -  "
              "k  -  -  -  h  -  -  -   k  -  -  h  k  -  h  -  "),

    # A wave is walking. Faster, a running bass, no room to breathe.
    "battle": Tune(
        bpm=144, volume=0.24,
        lead="A4 A4 .  C5 B4 .  A4 G4   A4 .  E5 .  D5 .  C5 .  "
             "A4 A4 .  C5 B4 .  D5 C5   B4 .  A4 .  E4 .  .  .  ",
        bass="A2 A2 A3 A2 A2 A2 A3 A2   F2 F2 F3 F2 F2 F2 F3 F2  "
             "C3 C3 C4 C3 C3 C3 C4 C3   E2 E2 E3 E2 E2 E2 E3 E2  ",
        drums="k  -  h  -  s  -  h  -    k  -  h  -  s  -  h  -   "
              "k  -  h  -  s  -  h  -    k  -  h  k  s  -  h  h   "),

    # Elites, and the Warlord. Phrygian — that flat second is the whole point.
    "siege": Tune(
        bpm=152, volume=0.26,
        lead="A4 .  A#4 .  A4 .  F4 .   E4 .  F4 .  E4 .  D4 .  "
             "A4 .  A#4 .  C5 .  A#4 .  A4 .  G4 .  F4 .  E4 .  ",
        bass="A2 A2 A2 A2 A#2 A#2 A#2 A#2  A2 A2 A2 A2 E2 E2 E2 E2 "
             "F2 F2 F2 F2 E2 E2 E2 E2      A2 A2 A2 A2 A2 A2 A2 A2 ",
        drums="k  -  k  -  s  -  -  k    k  -  k  -  s  -  h  -   "
              "k  -  k  -  s  -  -  k    k  k  k  k  s  s  h  h   "),
}


# The typewriter. Baked once as a loop of clatter rather than one process per
# keystroke — a quote is a few hundred characters, and a few hundred processes
# is a fork bomb with good intentions. It runs while the letters appear and is
# cut off the moment they stop, which is close enough to synchronised that
# nobody has ever noticed the difference.
TYPE_SECONDS = 8.0        # length of the loop; the keeper repeats it if needed
TYPE_RATE = 11.0          # keystrokes per second
TYPE_RETURN = 34          # keystrokes between carriage-return bells


def render_clicks() -> bytes:
    """Type-bar clatter: a hammer strike every so often, a bell at the margin."""
    buf = [0.0] * int(TYPE_SECONDS * RATE)
    t, struck = 0.0, 0
    while t < TYPE_SECONDS - 0.2:
        at = int(t * RATE)
        # A strike is a knock of noise with a short woody tone under it.
        length = int(0.030 * RATE)
        tone = random.uniform(900, 1500)
        phase = 0.0
        for i in range(min(length, len(buf) - at)):
            env = (1.0 - i / length) ** 3
            phase += 2 * math.pi * tone / RATE
            buf[at + i] += (random.uniform(-1.0, 1.0) * 0.7
                            + math.sin(phase) * 0.3) * env * 0.5
        struck += 1
        if struck % TYPE_RETURN == 0:            # the carriage comes back
            _lay(buf, at, 1760.0, 0.28, "tri", 0.30)
            t += 0.35
        t += (1.0 / TYPE_RATE) * random.uniform(0.75, 1.35)

    pcm = array.array("h")
    for s in buf:
        pcm.append(int(max(-1.0, min(1.0, s * 0.55)) * 32767))
    return pcm.tobytes()


# ---------------------------------------------------------------------------
# Speech
# ---------------------------------------------------------------------------
#
# Announcements — the wave number, the name on a quote, the thing that just
# walked onto the road — go through whatever text-to-speech command the system
# has. Every one of these plays the text itself, so the last argument is the
# line to speak and there is nothing to synthesise here.

# Engines that can write the line to a WAV, most human-sounding first, with
# {text} and {path} filled in. flite's `rms` and `awb` voices are built from
# the CMU ARCTIC corpus — a real person, recorded once, free to use — which is
# why they rank above the formant synthesisers that only ever sound like a
# kettle. Whatever comes out of these is then dragged down into the cellar by
# `demonise` below, so the announcer is a human voice, not a human being.
VOICES = [
    ("flite", ["-voice", "rms", "-t", "{text}", "-o", "{path}"]),
    ("say", ["-o", "{path}", "--data-format=LEI16@22050", "{text}"]),   # macOS
    ("pico2wave", ["-w", "{path}", "{text}"]),
    ("espeak-ng", ["-v", "en", "-s", "128", "-p", "10", "-w", "{path}", "{text}"]),
    ("espeak", ["-v", "en", "-s", "128", "-p", "10", "-w", "{path}", "{text}"]),
]

# Last resort: engines that only ever speak out loud. Nothing can be done to
# these on the way past, so they get to sound like themselves.
SAYERS = [
    ("spd-say", ["-w", "-r", "-20", "-p", "-50"]),
]

SPEECH_GAP = 0.8          # shortest time between two announcements

# What the voice is put through. Playing a recording back slower drops its
# pitch and stretches it; a second copy a hair off the first beats against it
# into a growl; a short echo puts the whole thing in a much bigger room.
VOICE_DROP = 0.78         # playback rate — under 1.0 is deeper and slower
VOICE_GROWL = 0.55        # level of the detuned copy
VOICE_DETUNE = 1.021      # how far off the copy sits
VOICE_ECHO = 0.34         # level of the echo
VOICE_ECHO_MS = 85
VOICE_SHUDDER = 0.18      # depth of a slow tremolo, for the menace
VOICE_SHUDDER_HZ = 24.0
VOICE_PEAK = 0.86         # what it is normalised to afterwards


def _find_speaker() -> tuple[str, list[str], bool] | None:
    """(command, argument template, whether it writes a file)."""
    for name, args in VOICES:
        if shutil.which(name):
            return name, args, True
    for name, args in SAYERS:
        if shutil.which(name):
            return name, args, False
    return None


def _read_wav(path: str) -> tuple[array.array, int] | None:
    """Mono 16-bit samples and their rate, or None for anything exotic."""
    try:
        with wave.open(path, "rb") as fh:
            if fh.getsampwidth() != 2:
                return None
            frames = fh.readframes(fh.getnframes())
            rate, channels = fh.getframerate(), fh.getnchannels()
    except (OSError, wave.Error):
        return None
    samples = array.array("h")
    samples.frombytes(frames)
    if channels > 1:                       # fold to mono; nothing here is stereo
        samples = array.array("h", samples[::channels])
    return samples, rate


def demonise(samples: array.array, rate: int) -> bytes:
    """Drag a spoken line down into something that enjoys its work.

    Four things, in order: slow it down so the pitch falls, lay a slightly
    detuned copy over it so the two beat against each other, put it in a large
    stone room, and let the whole thing shudder. The speech stays intelligible
    because the pitch only drops about four semitones — a demon nobody can
    understand is just noise.
    """
    n = len(samples)
    if n == 0:
        return b""
    out = [0.0] * int(n / VOICE_DROP + 1)

    def stretch(step: float, gain: float) -> None:
        pos = 0.0
        for i in range(len(out)):
            j = int(pos)
            if j + 1 >= n:
                return
            frac = pos - j
            out[i] += (samples[j] + (samples[j + 1] - samples[j]) * frac) * gain
            pos += step

    stretch(VOICE_DROP, 1.0)
    stretch(VOICE_DROP * VOICE_DETUNE, VOICE_GROWL)

    delay = int(VOICE_ECHO_MS / 1000.0 * rate)
    for i in range(delay, len(out)):
        out[i] += out[i - delay] * VOICE_ECHO

    peak = max(1.0, max(abs(v) for v in out))
    scale = VOICE_PEAK * 32767 / peak
    pcm = array.array("h")
    for i, v in enumerate(out):
        shudder = 1.0 - VOICE_SHUDDER * (
            0.5 - 0.5 * math.cos(2 * math.pi * VOICE_SHUDDER_HZ * i / rate))
        pcm.append(int(max(-32767, min(32767, v * scale * shudder))))
    return pcm.tobytes()


def _wave_at(kind: str, phase: float) -> float:
    if kind == "pulse":                       # 25% duty: thin and nasal
        return 1.0 if (phase % (2 * math.pi)) < (math.pi / 2) else -1.0
    if kind == "tri":
        t = (phase / (2 * math.pi)) % 1.0
        return 4 * abs(t - 0.5) - 1
    return random.uniform(-1.0, 1.0)


def _lay(buf: list[float], start: int, hz: float, dur: float,
         kind: str, gain: float) -> None:
    """Mix one note into the buffer, with a plucked chip envelope."""
    n = min(int(dur * RATE), len(buf) - start)
    phase = 0.0
    for i in range(max(0, n)):
        phase += 2 * math.pi * hz / RATE
        # Instant attack, exponential decay: no chiptune ever had a slow one.
        env = math.exp(-3.0 * i / n) * min(1.0, i / 24)
        buf[start + i] += _wave_at(kind, phase) * env * gain


def _hit(buf: list[float], start: int, kind: str, gain: float) -> None:
    """Mix in one drum: kick is a fast downward sweep, the rest is noise."""
    length = int((0.09 if kind == "k" else 0.05 if kind == "s" else 0.02) * RATE)
    phase = 0.0
    for i in range(min(length, len(buf) - start)):
        env = (1.0 - i / length) ** 2
        if kind == "k":
            phase += 2 * math.pi * (150 - 110 * i / length) / RATE
            buf[start + i] += math.sin(phase) * env * gain * 1.6
        else:
            buf[start + i] += random.uniform(-1.0, 1.0) * env * gain


def _play_line(buf: list[float], line: str, step: float,
               kind: str, gain: float) -> None:
    """Lay one tracker line down, honouring '.' as a hold on the note before."""
    tokens = line.split()
    i = 0
    while i < len(tokens):
        if tokens[i] in ("-", "."):
            i += 1
            continue
        held = 1
        while i + held < len(tokens) and tokens[i + held] == ".":
            held += 1
        if kind == "drum":
            _hit(buf, int(i * step * RATE), tokens[i], gain)
        else:
            _lay(buf, int(i * step * RATE), note_hz(tokens[i]),
                 held * step * 0.98, kind, gain)
        i += held


def render_tune(tune: Tune) -> bytes:
    """Bake one loop down to 16-bit mono PCM. Takes a moment; do it off-thread."""
    step = 30.0 / tune.bpm                          # one eighth note
    steps = max(len(line.split())
                for line in (tune.lead, tune.bass, tune.drums))
    buf = [0.0] * int(steps * step * RATE)
    _play_line(buf, tune.lead, step, "pulse", 0.42)
    _play_line(buf, tune.bass, step, "tri", 0.75)
    _play_line(buf, tune.drums, step, "drum", 0.55)

    pcm = array.array("h")
    for s in buf:
        pcm.append(int(max(-1.0, min(1.0, s * tune.volume)) * 32767))
    return pcm.tobytes()


def _write_wav(path: str, pcm: bytes) -> None:
    with wave.open(path, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(RATE)
        fh.writeframes(pcm)


def _find_player() -> tuple[str, list[str]] | None:
    for name, args in PLAYERS:
        if shutil.which(name):
            return name, args
    return None


class Audio:
    """The game's whole relationship with the sound card."""

    def __init__(self) -> None:
        self.enabled = not os.environ.get("TTD_SILENT")
        self.music_on = not os.environ.get("TTD_NOMUSIC")
        self.player = _find_player() if self.enabled else None
        self.available = self.player is not None
        self.speaker = _find_speaker() if not os.environ.get("TTD_NOVOICE") else None
        self._files: dict[str, str] = {}
        self._last: dict[str, float] = {}
        self._voices: list[subprocess.Popen] = []
        self._mouth: subprocess.Popen | None = None
        self._talking: threading.Thread | None = None
        self._spoken: dict[str, str] = {}       # line -> the WAV of it, kept
        self._spoke = 0.0
        self._dir: str | None = None

        # Background channels. `_want` is the only thing the rest of the game
        # touches; everything else belongs to the keeper thread, so there is
        # nothing to lock and no way for a slow bake to stall a frame.
        self._want: dict[str, str | None] = {"music": None, "typing": None}
        self._loops: dict[str, str] = {}                  # name -> baked WAV
        self._broken: set[str] = set()                    # names that would not bake
        self._procs: dict[str, subprocess.Popen | None] = {}
        self._playing: dict[str, str | None] = {}
        self._done = threading.Event()
        self._keeper: threading.Thread | None = None

        if self.available:
            self._bake()
            atexit.register(self.close)
            self._keeper = threading.Thread(target=self._keep_music, daemon=True)
            self._keeper.start()

    @property
    def on(self) -> bool:
        return self.enabled and self.available

    def _bake(self) -> None:
        """Write every cue out as a WAV once, up front."""
        try:
            self._dir = tempfile.mkdtemp(prefix="ttd-audio-")
            for name, (segs, kind, vol, _) in CUES.items():
                path = os.path.join(self._dir, f"{name}.wav")
                _write_wav(path, _render(segs, kind, vol))
                self._files[name] = path
        except OSError:
            self.available = False

    def play(self, cue: str) -> None:
        """Fire a cue, unless it is too soon or too many are already running."""
        if not self.on or cue not in self._files:
            return
        now = time.monotonic()
        if now - self._last.get(cue, -99.0) < CUES[cue][3]:
            return

        self._voices = [p for p in self._voices if p.poll() is None]
        if len(self._voices) >= MAX_VOICES:
            return

        cmd, args = self.player
        try:
            self._voices.append(subprocess.Popen(
                [cmd, *args, self._files[cue]],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL))
            self._last[cue] = now
        except OSError:
            self.available = False      # player vanished mid-game; give up

    # -- music --------------------------------------------------------------

    def music(self, tune: str | None) -> None:
        """Ask for a background loop by name, or None for silence.

        Returns immediately: the keeper thread does the baking and the
        spawning, and picks the change up within a fifth of a second.
        """
        self._want["music"] = tune

    def typing(self, on: bool) -> None:
        """Start or stop the typewriter clatter under a quote."""
        self._want["typing"] = "typewriter" if on else None

    def toggle_music(self) -> bool:
        self.music_on = not self.music_on
        return self.music_on and self.on

    def _wanted(self, channel: str) -> str | None:
        """What a channel should be playing right now, mutes included."""
        if not self.on:
            return None
        if channel == "music" and not self.music_on:
            return None
        return self._want[channel]

    def _keep_music(self) -> None:
        """Bake loops, start the wanted ones, and restart them when they end.

        Command-line players do not loop, so a loop is simply played again
        each time its process exits. The seam is audible if you listen for it,
        which is a fair price for having no audio library at all.
        """
        while not self._done.is_set():
            for channel in self._want:
                want = self._wanted(channel)
                proc = self._procs.get(channel)
                ended = proc is not None and proc.poll() is not None
                if want == self._playing.get(channel) and not ended:
                    continue
                if want != self._playing.get(channel):
                    self._hush(channel)
                path = self._loop_file(want) if want else None
                self._procs[channel] = self._spawn(path) if path else None
                self._playing[channel] = want if path else None
            self._done.wait(0.2)

    def _loop_file(self, name: str) -> str | None:
        """The WAV behind a looping channel, baked on first request.

        A name that cannot be baked is remembered as broken, so a bad tune
        costs one failed attempt rather than five a second forever.
        """
        if name in self._broken:
            return None
        if name not in self._loops:
            if not self._dir:
                return None
            try:
                if name in TUNES:
                    pcm = render_tune(TUNES[name])
                elif name == "typewriter":
                    pcm = render_clicks()
                else:
                    raise ValueError(name)
                path = os.path.join(self._dir, f"loop-{name}.wav")
                _write_wav(path, pcm)
            except (OSError, ValueError):
                self._broken.add(name)
                return None
            self._loops[name] = path
        return self._loops[name]

    def _spawn(self, path: str) -> subprocess.Popen | None:
        cmd, args = self.player
        try:
            return subprocess.Popen([cmd, *args, path],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL)
        except OSError:
            self.available = False
            return None

    def _hush(self, channel: str) -> None:
        proc = self._procs.get(channel)
        if proc is not None and proc.poll() is None:
            proc.terminate()
        self._procs[channel] = None
        self._playing[channel] = None

    # -- speech -------------------------------------------------------------

    def say(self, text: str) -> None:
        """Announce a line out loud, if this machine can talk.

        Announcements never queue and never overlap: if the last one is still
        being read, or was only a moment ago, this one is simply dropped. A
        wave that arrives while the Warlord is still being named does not need
        saying twice.

        The work — synthesising the line and dragging it down an octave-ish —
        happens on a thread of its own, because a frame is 33ms and a voice is
        not.
        """
        if not text or not self.on or self.speaker is None:
            return
        now = time.monotonic()
        if now - self._spoke < SPEECH_GAP:
            return
        if self._talking is not None and self._talking.is_alive():
            return
        if self._mouth is not None and self._mouth.poll() is None:
            return
        self._spoke = now
        self._talking = threading.Thread(target=self._utter, args=(text,),
                                         daemon=True)
        self._talking.start()

    def _utter(self, text: str) -> None:
        """Off-thread: get the line, then play it."""
        cmd, args, writes_file = self.speaker
        if not writes_file:
            self._mouth = self._run([cmd, *args, text])
            return
        path = self._voice_file(text)
        if path:
            self._mouth = self._spawn(path)

    def _voice_file(self, text: str) -> str | None:
        """The demonised WAV for a line, synthesised once and kept.

        The same handful of lines come round every run — "Warlord.", the wave
        numbers — so each one is worth keeping for as long as the game lives.
        """
        if text in self._spoken:
            return self._spoken[text]
        cmd, args, _ = self.speaker
        if not self._dir:
            return None
        raw = os.path.join(self._dir, "voice-raw.wav")
        done = os.path.join(self._dir, f"voice-{len(self._spoken):02d}.wav")
        argv = [cmd] + [a.format(text=text, path=raw) for a in args]
        proc = self._run(argv)
        if proc is None or proc.wait() != 0:
            self.speaker = None                  # it cannot do what it claimed
            return None
        heard = _read_wav(raw)
        if heard is None:
            self.speaker = None
            return None
        samples, rate = heard
        try:
            with wave.open(done, "wb") as fh:
                fh.setnchannels(1)
                fh.setsampwidth(2)
                fh.setframerate(rate)
                fh.writeframes(demonise(samples, rate))
        except OSError:
            return None
        self._spoken[text] = done
        return done

    def _run(self, argv: list[str]) -> subprocess.Popen | None:
        try:
            return subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    stdin=subprocess.DEVNULL)
        except OSError:
            self.speaker = None
            return None

    # -- lifecycle ----------------------------------------------------------

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.on

    def close(self) -> None:
        self._done.set()
        if self._keeper is not None:
            self._keeper.join(timeout=1.0)
        for channel in list(self._want):
            self._hush(channel)
        if self._mouth is not None and self._mouth.poll() is None:
            self._mouth.terminate()
        for p in self._voices:
            if p.poll() is None:
                p.terminate()
        self._voices.clear()
        if self._dir:
            self._files.update(self._loops)
            self._files.update(self._spoken)
            self._files["raw"] = os.path.join(self._dir, "voice-raw.wav")
            for path in self._files.values():
                try:
                    os.unlink(path)
                except OSError:
                    pass
            try:
                os.rmdir(self._dir)
            except OSError:
                pass
            self._dir = None


class Silence:
    """Stand-in used when sound is switched off entirely."""
    on = available = enabled = music_on = False
    speaker = None

    def play(self, cue: str) -> None:
        pass

    def music(self, tune: str | None) -> None:
        pass

    def typing(self, on: bool) -> None:
        pass

    def say(self, text: str) -> None:
        pass

    def toggle(self) -> bool:
        return False

    def toggle_music(self) -> bool:
        return False

    def close(self) -> None:
        pass
