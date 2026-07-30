"""
The rules.

`Game` owns every piece of mutable state and knows nothing whatsoever about
terminals — it exposes `update(dt)` for the simulation and a handful of methods
for what the player can do. Everything drawn on screen is derived from its
public attributes by `render`, which keeps the two halves independent and makes
the whole thing testable without a terminal (see `selftest.py`).

Time runs on `Game.clock`, not the wall clock. Every deadline in here — gun
cooldowns, when an explosion has finished blooming — is a timestamp on that
clock, so the speed dial rescales all of them at once rather than just making
creeps walk faster.

Three resources are in tension, and that tension is the game:

    gold    earned from kills and cleared waves
    power   generators supply it, weapons draw it, and a deficit browns the
            whole defense out rather than switching anything off
    ground  a Cannon stands on four cells, a Gun on one — and on a real
            battlefield most of the ground is a wood, a bog or the sea, so
            the spots you can actually use are fewer than they look

The map is the fourth resource, really. `terrain.py` says which cells will
take a building and which will not, and standing a weapon on high ground
buys it reach — which is the whole reason armies fight over ridges.

Player actions return the name of a sound cue (or None), which is the only
concession this module makes to the rest of the program.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from content import (BUILDINGS, ENEMIES, MIN_POWER_RATIO, SPEEDS, BuildSpec,
                     EnemySpec, Mode, Tier, build_wave, is_boss_wave, menace,
                     wave_bounty)
from terrain import PATH_CHARS, MapDef, Terrain

SELL_REFUND = 0.6

# Creep speeds are quoted for a path of this length. Real maps range from 60
# to 400 cells, so speed is scaled to keep a lap across the board taking about
# the same time everywhere — otherwise the small maps would be brutal and the
# big ones a stroll.
REFERENCE_PATH = 150.0

# Longest slice of battle simulated in one go; see Game.update.
MAX_STEP = 0.05

# Phases of a run.
BUILD, WAVE, LOST, WON = "BUILD", "WAVE", "LOST", "WON"


def dist2(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Squared distance — comparing squares saves a pointless square root."""
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


@dataclass
class Enemy:
    """A creep walking the path. `dist` is its position in path-cell units."""
    spec: EnemySpec
    max_hp: float
    hp: float
    speed: float                 # already scaled by mode and map length
    dist: float = 0.0
    chill: float = 1.0           # speed multiplier from whatever frost it stands in
    hurt_until: float = 0.0      # brief flash after taking a hit
    rank: int = 0                # 0 recruit, 1 veteran, 2 elite — looks only

    def pos(self, path: list[tuple[int, int]]) -> tuple[float, float]:
        """Sub-cell position, interpolated so range checks stay smooth."""
        i = min(int(self.dist), len(path) - 1)
        j = min(i + 1, len(path) - 1)
        f = self.dist - int(self.dist)
        (ay, ax), (by, bx) = path[i], path[j]
        return ay + (by - ay) * f, ax + (bx - ax) * f

    @property
    def health(self) -> float:
        return max(0.0, self.hp / self.max_hp)


@dataclass
class Building:
    """Anything you put on the grass. `y, x` is the top-left of its footprint."""
    spec: BuildSpec
    y: int
    x: int
    level: int = 1
    ready_at: float = 0.0        # game-clock time it may fire again
    kills: int = 0
    damage_done: float = 0.0
    flash_until: float = 0.0     # muzzle flash

    @property
    def tier(self) -> Tier:
        return self.spec.tiers[self.level - 1]

    @property
    def next_tier(self) -> Tier | None:
        return self.spec.tiers[self.level] if self.upgradable else None

    @property
    def upgradable(self) -> bool:
        return self.level < self.spec.marks

    @property
    def invested(self) -> int:
        """Everything paid for this building so far, upgrades included."""
        return sum(t.cost for t in self.spec.tiers[:self.level])

    @property
    def centre(self) -> tuple[float, float]:
        h, w = self.spec.foot
        return self.y + (h - 1) / 2, self.x + (w - 1) / 2

    def cells(self):
        h, w = self.spec.foot
        for dy in range(h):
            for dx in range(w):
                yield self.y + dy, self.x + dx


@dataclass
class Projectile:
    """A shot in flight. Bullets and shells travel, so towers can miss.

    While its mark is alive the projectile homes on it; once the mark dies it
    carries on to where it last saw it — a bullet fizzles there, a shell still
    goes off, which is the whole appeal of splash damage.
    """
    kind: str                    # bullet / shell, for the renderer
    owner: Building
    y: float
    x: float
    ty: float
    tx: float
    speed: float
    damage: float
    splash: float
    mark: "Enemy | None"
    ttl: float                   # seconds before it gives up
    trail: list[tuple[float, float]] = field(default_factory=list)
    spent: bool = False


@dataclass
class Effect:
    """A short-lived flourish: a spark, or a blast ring opening outwards."""
    kind: str                    # spark / blast
    y: float
    x: float
    radius: float
    born: float
    life: float

    def age(self, now: float) -> float:
        """0 at birth, 1 when it should be swept away."""
        return (now - self.born) / self.life


class Game:
    def __init__(self, mode: Mode, field_: MapDef) -> None:
        self.mode = mode
        self.map = field_
        self.map_name = field_.name
        self.grid, self.path = field_.grid, field_.path
        self.h, self.w = field_.h, field_.w

        # See REFERENCE_PATH above.
        self.pace = mode.speed * (len(self.path) / REFERENCE_PATH)

        self.gold = mode.gold
        self.lives = mode.lives
        self.max_lives = mode.lives
        self.score = 0
        self.wave = 1
        self.kills = 0
        self.leaked = 0
        self.spent = 0

        self.clock = 0.0
        self.speed_step = 0

        # Buildings are held twice: once by their anchor cell, and once per
        # occupied cell, so "what is under the cursor" and "is this ground
        # free" are both a dictionary lookup rather than a search.
        self.buildings: dict[tuple[int, int], Building] = {}
        self.plots: dict[tuple[int, int], Building] = {}
        # cell -> (strongest frost mark over it, coldest slow factor)
        self.chill: dict[tuple[int, int], tuple[int, float]] = {}
        self.supply = mode.power
        self.draw = 0
        self._was_short = False

        self.enemies: list[Enemy] = []
        self.shots: list[Projectile] = []
        self.effects: list[Effect] = []

        self.queue: list[str] = []           # creeps still to spawn this wave
        self.wave_total = 0                  # size of the wave, for the progress bar
        self.hp_mult = 1.0
        self.spawn_at = 0.0

        self.state = BUILD
        self.timer = mode.build_time
        self.paused = False
        self.message = "Build a generator, then something to shoot with."

        # Start the cursor just off the entrance, where the first fight will be.
        sy, sx = self.path[0]
        self.cy = min(max(sy + 1, 0), self.h - 1)
        self.cx = min(max(sx + 2, 0), self.w - 1)
        self.selected = 0

    # -- queries ------------------------------------------------------------

    def is_path(self, y: int, x: int) -> bool:
        return self.grid[y][x] in PATH_CHARS

    def ground(self, y: int, x: int) -> Terrain:
        return self.map.ground(y, x)

    def buildable(self, y: int, x: int) -> bool:
        """Ground a tower could stand on if nothing were already there.

        The road is out because creeps walk it, and so is anything a gun
        crew could not physically emplace on: open water, a bog that will
        not take the weight, a wood too thick to cut a field of fire in, a
        mountainside. It is the map, not the rules, that decides.
        """
        return self.map.buildable(y, x)

    def at(self, y: int, x: int) -> Building | None:
        return self.plots.get((y, x))

    def can_place(self, y: int, x: int, spec: BuildSpec) -> bool:
        """Every cell of the footprint must be clear, buildable, and on the map."""
        h, w = spec.foot
        if y < 0 or x < 0 or y + h > self.h or x + w > self.w:
            return False
        for dy in range(h):
            for dx in range(w):
                if not self.buildable(y + dy, x + dx) or (y + dy, x + dx) in self.plots:
                    return False
        return True

    def high_ground(self, y: int, x: int, spec: BuildSpec) -> float:
        """Extra reach a footprint anchored at (y, x) would get from the ground.

        The whole emplacement has to be up there, not one corner of it — a
        battery half on the ridge is a battery in the valley. Which is why
        armies spend so much of their time walking uphill.
        """
        h, w = spec.foot
        return min((self.ground(y + dy, x + dx).high
                    for dy in range(h) for dx in range(w)
                    if 0 <= y + dy < self.h and 0 <= x + dx < self.w),
                   default=0.0)

    def reach(self, b: Building) -> float:
        """A weapon's range where it actually stands."""
        if b.tier.range <= 0:
            return b.tier.range
        return b.tier.range + self.high_ground(b.y, b.x, b.spec)

    def site(self, y: int, x: int, spec: BuildSpec) -> tuple[int, int] | None:
        """Where a footprint would actually land if you built at (y, x).

        The cursor is one cell but a Cannon is four, so the obvious rule —
        read the cursor as the top-left corner — refuses perfectly good
        ground the moment you stand at the bottom or right edge of a
        clearing. Instead the cursor only has to fall *somewhere inside* the
        footprint: try the top-left reading first, then slide the block up
        and left until it sits on open ground. Returns the anchor, or None
        when no arrangement covering (y, x) is clear.
        """
        h, w = spec.foot
        offsets = sorted(((oy, ox) for oy in range(h) for ox in range(w)),
                         key=lambda o: (o[0] + o[1], o))
        for oy, ox in offsets:
            if self.can_place(y - oy, x - ox, spec):
                return y - oy, x - ox
        return None

    @property
    def over(self) -> bool:
        return self.state in (LOST, WON)

    @property
    def spec(self) -> BuildSpec:
        return BUILDINGS[self.selected]

    @property
    def speed(self) -> float:
        return SPEEDS[self.speed_step]

    @property
    def power_ratio(self) -> float:
        """How well the grid is keeping up, 1.0 when comfortable.

        A deficit does not switch anything off — it drags everything down
        together, which is recoverable and much easier to read on the HUD.
        """
        if self.draw <= 0:
            return 1.0
        return max(MIN_POWER_RATIO, min(1.0, self.supply / self.draw))

    @property
    def short_of_power(self) -> bool:
        return self.draw > self.supply

    @property
    def waves_left(self) -> int | None:
        """Waves still to survive, or None in the endless modes.

        `wave` counts the one being fought or prepared for, so the number
        already behind you is `wave - 1` in either phase.
        """
        if self.mode.target is None:
            return None
        if self.state == WON:
            return 0
        return max(0, self.mode.target - self.wave + 1)

    @property
    def run_progress(self) -> float | None:
        """How far through a finite run we are, 0..1."""
        if self.mode.target is None:
            return None
        if self.state == WON:
            return 1.0
        done = self.wave - 1 + (self.wave_progress if self.state == WAVE else 0.0)
        return min(1.0, done / self.mode.target)

    @property
    def wave_progress(self) -> float:
        """How much of the current wave has been dealt with, 0..1."""
        if self.state != WAVE or not self.wave_total:
            return 1.0 if self.over else 0.0
        return 1 - (len(self.queue) + len(self.enemies)) / self.wave_total

    @property
    def menace(self) -> int:
        """How hard this wave looks: 0 recruits, 1 veterans, 2 elites.

        Read off the health the wave is carrying, not its number, so it lines
        up with the difficulty in every mode. During a build phase it reports
        what is about to walk in, which is what the player wants to know.
        """
        mult = self.hp_mult if self.state == WAVE else \
            self.mode.hp_growth ** (self.wave - 1)
        return menace(mult)

    @property
    def boss_wave(self) -> bool:
        """True when this wave ends with a Warlord."""
        return is_boss_wave(self.wave)

    def wave_census(self) -> list[tuple[EnemySpec, int]]:
        """What is still coming, for the sidebar: (spec, count) by type."""
        tally: dict[str, int] = {}
        for key in self.queue:
            tally[key] = tally.get(key, 0) + 1
        for e in self.enemies:
            for key, spec in ENEMIES.items():
                if spec is e.spec:
                    tally[key] = tally.get(key, 0) + 1
        return [(ENEMIES[k], tally[k]) for k in ENEMIES if k in tally]

    # -- the grid -----------------------------------------------------------

    def _resurvey(self) -> None:
        """Recompute supply, draw and the frost map. Cheap, and called only
        when something is built, sold or upgraded."""
        self.supply = self.mode.power
        self.draw = 0
        self.chill = {}
        for b in self.buildings.values():
            power = b.tier.power
            if power < 0:
                self.supply -= power
            else:
                self.draw += power
            if b.tier.aura > 0:
                self._paint_chill(b)

    def _paint_chill(self, b: Building) -> None:
        cy, cx = b.centre
        r = b.tier.aura
        for y in range(max(0, int(cy - r)), min(self.h, int(cy + r) + 1)):
            for x in range(max(0, int(cx - r)), min(self.w, int(cx + r) + 1)):
                if math.hypot(y - cy, x - cx) <= r:
                    mark, slow = self.chill.get((y, x), (0, 1.0))
                    self.chill[(y, x)] = (max(mark, b.level), min(slow, b.tier.slow))

    def chill_at(self, y: int, x: int) -> tuple[int, float]:
        """(frost mark, slow factor) over a cell, both neutral when clear."""
        return self.chill.get((y, x), (0, 1.0))

    # -- player actions -----------------------------------------------------

    def move_cursor(self, dy: int, dx: int) -> None:
        self.cy = max(0, min(self.h - 1, self.cy + dy))
        self.cx = max(0, min(self.w - 1, self.cx + dx))

    def build(self) -> str:
        spec = self.spec
        spot = self.site(self.cy, self.cx, spec)
        if spot is None:
            h, w = spec.foot
            here = self.ground(self.cy, self.cx)
            if not self.is_path(self.cy, self.cx) and not here.build:
                self.message = f"Nothing stands in {here.name}."
            else:
                self.message = (f"A {spec.name} needs {h}x{w} of open ground here."
                                if spec.cells > 1 else "No room there.")
            return "deny"
        if self.gold < spec.cost:
            self.message = f"Not enough gold for a {spec.name} (${spec.cost})."
            return "deny"

        b = Building(spec, *spot)
        self.buildings[spot] = b
        for cell in b.cells():
            self.plots[cell] = b
        self.gold -= spec.cost
        self.spent += spec.cost
        self._resurvey()
        if spec.role == "generator":
            self.message = f"Generator online. Grid at {self.supply} units."
        elif self.high_ground(*spot, spec):
            self.message = (f"{spec.name} on the high ground — "
                            f"reach {self.reach(b):.1f}.")
        else:
            self.message = f"{spec.name} emplaced, drawing {b.tier.power}."
        return "build"

    def sell(self) -> str:
        b = self.at(self.cy, self.cx)
        if b is None:
            self.message = "Nothing to sell here."
            return "deny"
        refund = int(b.invested * SELL_REFUND)
        del self.buildings[(b.y, b.x)]
        for cell in b.cells():
            self.plots.pop(cell, None)
        self.gold += refund
        self._resurvey()
        self.message = f"Scrapped a {b.spec.name} for ${refund}."
        return "sell"

    def upgrade(self) -> str:
        b = self.at(self.cy, self.cx)
        if b is None:
            self.message = "Nothing to upgrade here."
            return "deny"
        if not b.upgradable:
            self.message = f"That {b.spec.name} is already mk{b.level}."
            return "deny"
        nxt = b.next_tier
        if self.gold < nxt.cost:
            self.message = f"Upgrading needs ${nxt.cost}."
            return "deny"
        self.gold -= nxt.cost
        self.spent += nxt.cost
        b.level += 1
        self._resurvey()
        self.message = f"{b.spec.name} mk{b.level} — {nxt.note}."
        return "upgrade"

    def call_wave(self) -> str:
        """Cut the build phase short; the seconds you give up become gold."""
        if self.state != BUILD:
            return ""
        self.gold += int(self.timer) * 2
        self.timer = 0.0
        self.message = "Wave incoming."
        return "wave"

    def change_speed(self, step: int) -> str:
        was = self.speed_step
        self.speed_step = max(0, min(len(SPEEDS) - 1, self.speed_step + step))
        if self.speed_step == was:
            return ""
        self.message = f"Battle speed x{self.speed:g}."
        return "select"

    # -- simulation ---------------------------------------------------------

    def update(self, dt: float) -> list[str]:
        """Advance by `dt` seconds of wall time, scaled by the speed dial.

        Long steps are chopped up first. At 4x a single frame is a third of a
        second of battle, which is enough for a creep to stride clean through
        a tower's firing arc between two ticks — so the dial would quietly
        make the game easier. Sub-stepping keeps every speed honest.

        Returns the sound cues this step earned.
        """
        self.cues: list[str] = []
        if self.over or self.paused:
            return self.cues
        remaining = dt * self.speed
        while remaining > 0 and not self.over:
            step = min(remaining, MAX_STEP)
            remaining -= step
            self._advance(step)

        short = self.short_of_power
        if short != self._was_short:
            self._was_short = short
            if short:
                self.message = "Brownout — the grid cannot keep up."
                self.cues.append("power")
        return self.cues

    def _advance(self, dt: float) -> None:
        self.clock += dt
        now = self.clock
        # Swept here rather than in _reap: a blast from the last kill of a wave
        # would otherwise hang on screen for the whole of the build phase.
        self.effects = [f for f in self.effects if f.age(now) < 1.0]

        if self.state == BUILD:
            self.timer -= dt
            if self.timer <= 0:
                self.queue, self.hp_mult = build_wave(self.mode, self.wave)
                self.wave_total = len(self.queue)
                self.spawn_at = now
                self.state = WAVE
                self.cues.append("wave")
            return

        self._spawn(now)
        self._march(now, dt)
        if self.over:
            return
        for b in self.buildings.values():
            self._fire(b, now)
        self._fly(now, dt)
        self._reap(now)

        if not self.queue and not self.enemies and not self.shots:
            self._end_wave()

    def _spawn(self, now: float) -> None:
        while self.queue and now >= self.spawn_at:
            spec = ENEMIES[self.queue.pop()]
            hp = spec.hp * self.hp_mult
            self.enemies.append(Enemy(spec, hp, hp, spec.speed * self.pace,
                                      rank=self.menace))
            if spec.name == "Warlord":
                self.message = "The Warlord walks."
                self.cues.append("boss")
            self.spawn_at += self.mode.spawn_gap

    def _march(self, now: float, dt: float) -> None:
        """Advance every creep, chilling whatever stands in a frost field."""
        finish = len(self.path) - 1
        ratio = self.power_ratio
        survivors = []
        for e in self.enemies:
            y, x = e.pos(self.path)
            _, slow = self.chill_at(round(y), round(x))
            # A field running on half power only bites half as hard.
            e.chill = 1.0 - (1.0 - slow) * ratio
            e.dist += e.speed * e.chill * dt
            if e.dist >= finish:
                self.lives -= e.spec.leak
                self.leaked += 1
                self.message = f"A {e.spec.name} reached the base.  −{e.spec.leak}"
                self.cues.append("leak")
            else:
                survivors.append(e)
        self.enemies = survivors

        if self.lives <= 0:
            self.lives = 0
            self.state = LOST
            self.message = "The base has fallen."
            self.cues.append("defeat")

    def _fire(self, b: Building, now: float) -> None:
        tier = b.tier
        if not b.spec.shot or tier.damage <= 0 or now < b.ready_at:
            return
        origin = b.centre
        reach = self.reach(b) ** 2

        # Classic "first" targeting: shoot whatever is nearest to the base.
        target, best = None, -1.0
        for e in self.enemies:
            if dist2(origin, e.pos(self.path)) <= reach and e.dist > best:
                target, best = e, e.dist
        if target is None:
            return

        # Short of power, everything reloads more slowly.
        b.ready_at = now + tier.cooldown / self.power_ratio
        b.flash_until = now + 0.09
        ty, tx = target.pos(self.path)
        self.shots.append(Projectile(
            kind=b.spec.shot, owner=b, y=origin[0], x=origin[1], ty=ty, tx=tx,
            speed=b.spec.shot_speed * self.pace, damage=tier.damage,
            splash=tier.splash, mark=target, ttl=2.5))

    def _fly(self, now: float, dt: float) -> None:
        """Move every shot along its line and detonate whatever arrives."""
        for p in self.shots:
            p.ttl -= dt
            if p.mark is not None and p.mark.hp > 0:
                p.ty, p.tx = p.mark.pos(self.path)   # home while the mark lives
            dy, dx = p.ty - p.y, p.tx - p.x
            gap = math.hypot(dy, dx)
            step = p.speed * dt

            p.trail.insert(0, (p.y, p.x))
            del p.trail[3:]

            if gap <= step or gap < 0.15:
                p.y, p.x = p.ty, p.tx
                self._impact(p, now)
                p.spent = True
            elif p.ttl <= 0:
                p.spent = True
            else:
                p.y += dy / gap * step
                p.x += dx / gap * step
        self.shots = [p for p in self.shots if not p.spent]

    def _impact(self, p: Projectile, now: float) -> None:
        here = (p.y, p.x)
        if p.splash:
            burst = p.splash ** 2
            for e in self.enemies:
                if dist2(here, e.pos(self.path)) <= burst:
                    self._wound(p.owner, e, p.damage, now)
            self.effects.append(Effect("blast", p.y, p.x, p.splash, now, 0.34))
            self.cues.append("boom")
            return

        # A single shot lands on its mark, or on whatever has wandered into
        # the space where the mark used to be.
        hit = p.mark if (p.mark is not None and p.mark.hp > 0) else None
        if hit is None:
            near = [e for e in self.enemies if dist2(here, e.pos(self.path)) <= 0.6]
            hit = near[0] if near else None
        if hit is not None:
            self._wound(p.owner, hit, p.damage, now)
            self.effects.append(Effect("spark", p.y, p.x, 0.0, now, 0.16))

    def _wound(self, b: Building, enemy: Enemy, damage: float, now: float) -> None:
        enemy.hp -= damage
        enemy.hurt_until = now + 0.10
        b.damage_done += damage
        if enemy.hp <= 0:
            b.kills += 1

    def _reap(self, now: float) -> None:
        """Pay out bounties for the dead."""
        alive = []
        for e in self.enemies:
            if e.hp > 0:
                alive.append(e)
            else:
                self.kills += 1
                self.gold += int(e.spec.bounty * self.mode.bounty)
                self.score += int(e.spec.bounty * self.mode.bounty)
                self.effects.append(Effect("spark", *e.pos(self.path), 0.0, now, 0.22))
        self.enemies = alive

    def _end_wave(self) -> None:
        bonus = wave_bounty(self.mode, self.wave)
        self.gold += bonus
        self.score += bonus
        if self.mode.target is not None and self.wave >= self.mode.target:
            self.state = WON
            self.message = "The field is yours."
            self.cues.append("victory")
            return
        self.message = f"Wave {self.wave} broken.  +${bonus}"
        self.cues.append("cleared")
        self.wave += 1
        self.state = BUILD
        self.timer = self.mode.break_time
