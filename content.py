"""
Content: every number, map and word in the game.

This module holds no logic worth speaking of — it is the place to come when
you want to change how TTD *plays* rather than how it works.

    TOWERS / ENEMIES / build_wave()   combat balance
    MODES                             the four ways to play
    MAPS                              hand-drawn battlefields
    WAR_QUOTES / DEFEAT_QUOTES / ...  the words between the fighting
"""

from __future__ import annotations

import random
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Towers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tier:
    """One mark of a building. Tier 1 is what you put down; 2 and 3 are bought
    on top of it with U, and every step wants more of the grid."""
    cost: int                # gold to build (tier 1) or to upgrade into it
    power: int               # units drawn; negative means generated
    damage: float = 0.0
    range: float = 0.0
    cooldown: float = 1.0    # seconds between shots
    splash: float = 0.0      # area-damage radius; 0 means single target
    aura: float = 0.0        # radius of a permanent field (Frost)
    slow: float = 1.0        # speed multiplier for creeps inside that field
    note: str = ""           # what this mark buys you, for the panel


@dataclass(frozen=True)
class BuildSpec:
    key: str                 # number key that selects it
    name: str
    glyph: str               # key into Theme.g, and its colour name
    role: str                # gun / frost / cannon / generator
    foot: tuple[int, int]    # (rows, cols) of ground it stands on
    tiers: tuple[Tier, ...]
    shot: str = ""           # projectile kind; empty for buildings that don't fire
    shot_speed: float = 0.0  # cells per second, before the map's pace scaling
    blurb: str = ""

    @property
    def cost(self) -> int:
        return self.tiers[0].cost

    @property
    def cells(self) -> int:
        return self.foot[0] * self.foot[1]

    @property
    def marks(self) -> int:
        return len(self.tiers)


# Four things to build, and they compete for three different resources: gold,
# power off the grid, and ground beside the road. A Cannon covers four times
# the footprint of a Gun and draws three times the power, so a field of heavy
# artillery needs a generator farm behind it.
BUILDINGS = [
    BuildSpec("1", "Gun", "gun", "gun", foot=(1, 1),
              shot="bullet", shot_speed=34,
              blurb="cheap, quick, close in",
              tiers=(
                  Tier(cost=20, power=2, damage=6, range=4.5, cooldown=0.35,
                       note="rapid single shots"),
                  Tier(cost=25, power=3, damage=10, range=5.0, cooldown=0.30,
                       note="heavier rounds, longer reach"),
                  Tier(cost=40, power=5, damage=16, range=5.5, cooldown=0.26,
                       note="autocannon"),
              )),

    BuildSpec("2", "Frost", "frost", "frost", foot=(1, 2),
              blurb="freezes the ground around it",
              tiers=(
                  Tier(cost=35, power=4, aura=2.5, slow=0.65,
                       note="chills a small patch"),
                  Tier(cost=50, power=8, aura=3.5, slow=0.45,
                       note="wider field, deeper cold"),
                  Tier(cost=75, power=14, aura=4.5, slow=0.30,
                       note="a glacier — and it drinks power"),
              )),

    BuildSpec("3", "Cannon", "cannon", "cannon", foot=(2, 2),
              shot="shell", shot_speed=15,
              blurb="slow shells, big blast",
              tiers=(
                  Tier(cost=55, power=6, damage=22, range=7.5, cooldown=1.50,
                       splash=2.2, note="lobs a shell over everything"),
                  Tier(cost=70, power=10, damage=34, range=8.0, cooldown=1.35,
                       splash=2.6, note="bigger shell, wider blast"),
                  Tier(cost=110, power=15, damage=50, range=8.5, cooldown=1.20,
                       splash=3.0, note="siege gun"),
              )),

    BuildSpec("4", "Generator", "generator", "generator", foot=(2, 2),
              blurb="the grid — build these first",
              tiers=(
                  Tier(cost=40, power=-20, note="20 units on the grid"),
                  Tier(cost=55, power=-32, note="32 units"),
                  Tier(cost=85, power=-46, note="46 units"),
              )),
]

# Below full power everything falls off together — guns fire slower and frost
# fields thaw — but the grid never dies completely, so a brownout is a problem
# to fix rather than an instant loss.
MIN_POWER_RATIO = 0.25

# Simulation speeds the player can cycle through with + and -.
SPEEDS = (1.0, 1.5, 2.0, 3.0, 4.0)


# ---------------------------------------------------------------------------
# Creeps
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnemySpec:
    name: str
    glyph: str               # key into Theme.g and Theme.menace
    hp: float
    speed: float             # cells per second on a reference-length path
    bounty: int
    leak: int                # lives lost if it reaches the base
    from_wave: int           # first wave it can appear in
    blurb: str = ""          # who this thing is, for the bestiary


# Five kinds of trouble, each with its own silhouette and its own reason to
# worry: numbers, speed, armour, the lives it takes with it, and — late on —
# something that simply will not die on schedule.
ENEMIES = {
    "grunt":   EnemySpec("Grunt",   "grunt",  hp=20,  speed=5.5,  bounty=4,  leak=1,
                         from_wave=1,  blurb="endless, unremarkable"),
    "runner":  EnemySpec("Runner",  "runner", hp=12,  speed=10.0, bounty=5,  leak=1,
                         from_wave=3,  blurb="twice the pace, half the hp"),
    "tank":    EnemySpec("Tank",    "tank",   hp=90,  speed=3.2,  bounty=12, leak=4,
                         from_wave=5,  blurb="slow armour, hard to shift"),
    "reaper":  EnemySpec("Reaper",  "reaper", hp=34,  speed=7.0,  bounty=9,  leak=2,
                         from_wave=9,  blurb="fast and heavy at once"),
    "warlord": EnemySpec("Warlord", "warlord", hp=240, speed=2.5, bounty=45, leak=6,
                         from_wave=12, blurb="the black queen herself"),
}

BOSS_EVERY = 5           # waves between Warlords, once they start showing up

# How frightening a wave *looks*. Tied to the health it carries rather than
# its number, so it means the same thing in every mode: twice the health of
# wave one and the ranks are veterans, four times and they are elites. Purely
# a matter of appearance — the danger is already in the health multiplier.
MENACE_STEPS = (2.0, 4.0)


def menace(hp_mult: float) -> int:
    """0 fresh troops, 1 veterans, 2 elites."""
    return sum(1 for step in MENACE_STEPS if hp_mult >= step)


def build_wave(mode: "Mode", wave: int) -> tuple[list[str], float]:
    """Return the creeps in a wave and their health multiplier.

    Waves grow along three independent axes: more creeps, tougher creeps, and
    new creep types unlocking as the run goes on. The list is drained from the
    back, so a Warlord parked at the front of it walks in last — behind its
    own army, the way a warlord should.
    """
    queue = ["grunt"] * (6 + wave)
    if wave >= ENEMIES["runner"].from_wave:
        queue += ["runner"] * (2 + wave // 2)
    if wave >= ENEMIES["tank"].from_wave:
        queue += ["tank"] * (1 + wave // 4)
    if wave >= ENEMIES["reaper"].from_wave:
        queue += ["reaper"] * (1 + (wave - ENEMIES["reaper"].from_wave) // 3)
    random.shuffle(queue)
    if wave >= ENEMIES["warlord"].from_wave and \
            (wave - ENEMIES["warlord"].from_wave) % BOSS_EVERY == 0:
        queue.insert(0, "warlord")
    return queue, mode.hp_growth ** (wave - 1)


def is_boss_wave(wave: int) -> bool:
    """True when a Warlord is coming, so the music and the HUD can say so."""
    first = ENEMIES["warlord"].from_wave
    return wave >= first and (wave - first) % BOSS_EVERY == 0


def wave_bounty(mode: "Mode", wave: int) -> int:
    """Gold for clearing a wave, on top of the per-kill bounties."""
    return int((15 + 6 * wave) * mode.bounty)


# ---------------------------------------------------------------------------
# Game modes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Mode:
    name: str
    tagline: str
    detail: str
    lives: int
    gold: int
    power: int               # grid capacity you start the run with
    hp_growth: float         # creep health multiplier per wave, compounding
    speed: float             # creep speed multiplier
    bounty: float            # gold multiplier
    build_time: float        # seconds before wave 1
    break_time: float        # seconds between waves
    spawn_gap: float
    target: int | None       # waves needed to win; None means endless


MODES = [
    Mode("Classic", "the long war",
         "Endless waves at a fair pace. Start here.",
         lives=20, gold=90, power=10, hp_growth=1.15, speed=1.0, bounty=1.0,
         build_time=15.0, break_time=8.0, spawn_gap=0.55, target=None),

    Mode("Blitz", "no time to think",
         "Everything moves faster and pays double. Breaks are short.",
         lives=20, gold=110, power=12, hp_growth=1.15, speed=1.45, bounty=2.0,
         build_time=8.0, break_time=4.0, spawn_gap=0.32, target=None),

    Mode("Gauntlet", "twenty waves, then peace",
         "A run with an ending — hold the line for 20 waves and you win.",
         lives=15, gold=100, power=10, hp_growth=1.22, speed=1.1, bounty=1.4,
         build_time=15.0, break_time=7.0, spawn_gap=0.50, target=20),

    Mode("Last Stand", "three lives",
         "Almost nothing may pass. Gold is plentiful; mercy is not.",
         lives=3, gold=140, power=14, hp_growth=1.18, speed=1.15, bounty=2.2,
         build_time=20.0, break_time=9.0, spawn_gap=0.50, target=None),
]


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------
#
#     S  entrance      #  path — creeps walk here, you cannot build
#     E  your base     .  grass — buildable
#
# Short rows are padded with grass at load time, so the art only has to be
# exact where the path is. Draw a single-width corridor with no forks and the
# loader traces it into a route by itself.
#
# Three size classes; the game picks a map that fits the terminal it is given.

MAPS: list[tuple[str, str]] = [
    # -- small: fits a 60-column terminal ----------------------------------
    ("Brook", """
S########################
........................#
........................#
#########################
#........................
#........................
#########################
........................E
"""),
    ("Picket", """
S.....#######.....#######
#.....#.....#.....#.....#
#.....#.....#.....#.....#
#.....#.....#.....#.....#
#.....#.....#.....#.....#
#.....#.....#.....#.....#
#.....#.....#.....#.....#
#######.....#######.....E
"""),

    # -- medium: fits an 80-column terminal ---------------------------------
    ("Serpentine", """
S####################################
....................................#
....................................#
#####################################
#....................................
#....................................
#####################################
....................................#
....................................#
E####################################
"""),
    ("Switchback", """
S.....#######.....#######.....#######
#.....#.....#.....#.....#.....#.....#
#.....#.....#.....#.....#.....#.....#
#.....#.....#.....#.....#.....#.....#
#.....#.....#.....#.....#.....#.....#
#.....#.....#.....#.....#.....#.....#
#.....#.....#.....#.....#.....#.....#
#.....#.....#.....#.....#.....#.....#
#.....#.....#.....#.....#.....#.....#
#######.....#######.....#######.....E
"""),
    ("Spiral", """
S####################################
....................................#
###################################.#
#.................................#.#
#.##############################E.#.#
#.#...............................#.#
#.#...............................#.#
#.#################################.#
#...................................#
#####################################
"""),

    # -- large: wants 110+ columns ------------------------------------------
    ("Labyrinth", """
S####################################################
....................................................#
....................................................#
#####################################################
#....................................................
#....................................................
#####################################################
....................................................#
....................................................#
#####################################################
#....................................................
#....................................................
#####################################################
....................................................#
....................................................#
E####################################################
"""),
    ("Coil", """
S####################################################
....................................................#
###################################################.#
#.................................................#.#
#.###############################################.#.#
#.#.............................................#.#.#
#.#.##########################################E.#.#.#
#.#.#...........................................#.#.#
#.#.#...........................................#.#.#
#.#.#...........................................#.#.#
#.#.#...........................................#.#.#
#.#.#############################################.#.#
#.#...............................................#.#
#.#################################################.#
#...................................................#
#####################################################
"""),
]


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Quote:
    text: str
    author: str
    role: str
    born: int                # negative years are BC
    died: int
    approx: bool = False     # dates are traditional / disputed

    @property
    def age(self) -> int:
        return self.died - self.born

    def lifespan(self) -> str:
        """e.g. '1874 – 1965', 'c. 544 – 496 BC', '106 BC – AD 43'."""
        def y(v: int) -> str:
            return f"{-v} BC" if v < 0 else str(v)
        a, b = y(self.born), y(self.died)
        if self.born < 0 and self.died < 0:
            a = str(-self.born)          # '544 – 496 BC' reads better
        return f"{'c. ' if self.approx else ''}{a} – {b}"

    def epitaph(self) -> str:
        return f"{'c. ' if self.approx else ''}{self.age}"


WAR_QUOTES = [
    Quote("War is the father of all and the king of all.",
          "Heraclitus", "philosopher", -535, -475, approx=True),
    Quote("The supreme art of war is to subdue the enemy without fighting.",
          "Sun Tzu", "general", -544, -496, approx=True),
    Quote("In peace, sons bury their fathers. In war, fathers bury their sons.",
          "Herodotus", "historian", -484, -425, approx=True),
    Quote("The strong do what they can, and the weak suffer what they must.",
          "Thucydides", "historian and general", -460, -400, approx=True),
    Quote("They make a desert and call it peace.",
          "Tacitus", "historian", 56, 120, approx=True),
    Quote("War is merely the continuation of policy by other means.",
          "Carl von Clausewitz", "Prussian general", 1780, 1831),
    Quote("War is cruelty. There is no use trying to reform it; "
          "the crueler it is, the sooner it will be over.",
          "William Tecumseh Sherman", "Union general", 1820, 1891),
    Quote("It is well that war is so terrible, "
          "otherwise we should grow too fond of it.",
          "Robert E. Lee", "Confederate general", 1807, 1870),
    Quote("Only the dead have seen the end of war.",
          "George Santayana", "philosopher", 1863, 1952),
    Quote("Every gun that is made, every warship launched, every rocket fired "
          "signifies a theft from those who hunger and are not fed.",
          "Dwight D. Eisenhower", "general and president", 1890, 1969),
    Quote("The first casualty when war comes is truth.",
          "Hiram Johnson", "senator", 1866, 1945),
    Quote("Laws are silent in time of war.",
          "Cicero", "orator", -106, -43),
    Quote("My subject is War, and the pity of War. The Poetry is in the pity.",
          "Wilfred Owen", "soldier and poet", 1893, 1918),
    Quote("You can no more win a war than you can win an earthquake.",
          "Jeannette Rankin", "congresswoman", 1880, 1973),
    Quote("War is an ugly thing, but not the ugliest of things.",
          "John Stuart Mill", "philosopher", 1806, 1873),
    Quote("Older men declare war. But it is youth that must fight and die.",
          "Herbert Hoover", "president", 1874, 1964),
]

DEFEAT_QUOTES = [
    Quote("Never give in. Never, never, never.",
          "Winston Churchill", "prime minister", 1874, 1965),
    Quote("The impediment to action advances action. "
          "What stands in the way becomes the way.",
          "Marcus Aurelius", "emperor", 121, 180),
    Quote("Victory belongs to the most persevering.",
          "Napoleon Bonaparte", "emperor", 1769, 1821),
    Quote("It is not because things are difficult that we do not dare; "
          "it is because we do not dare that they are difficult.",
          "Seneca", "philosopher", -4, 65, approx=True),
    Quote("That which does not kill me makes me stronger.",
          "Friedrich Nietzsche", "philosopher", 1844, 1900),
    Quote("In the midst of chaos, there is also opportunity.",
          "Sun Tzu", "general", -544, -496, approx=True),
    Quote("Cowards die many times before their deaths; "
          "the valiant never taste of death but once.",
          "William Shakespeare", "playwright", 1564, 1616),
    Quote("The brave man is not he who does not feel afraid, "
          "but he who conquers that fear.",
          "Nelson Mandela", "president", 1918, 2013),
    Quote("A man is not finished when he is defeated. "
          "He is finished when he quits.",
          "Richard Nixon", "president", 1913, 1994),
    Quote("The bravest are surely those who have the clearest vision of what "
          "is before them, glory and danger alike, and yet go out to meet it.",
          "Thucydides", "historian and general", -460, -400, approx=True),
    Quote("Death is nothing, but to live defeated and inglorious "
          "is to die daily.",
          "Napoleon Bonaparte", "emperor", 1769, 1821),
    Quote("Death is not the greatest loss in life. The greatest loss "
          "is what dies inside us while we live.",
          "Norman Cousins", "journalist", 1915, 1990),
    Quote("We are not retreating. We are advancing in another direction.",
          "Douglas MacArthur", "general", 1880, 1964),
    Quote("Courage is not the absence of fear, but the triumph over it.",
          "Nelson Mandela", "president", 1918, 2013),
]

VICTORY_QUOTES = [
    Quote("I came, I saw, I conquered.",
          "Julius Caesar", "general", -100, -44),
    Quote("In war there is no substitute for victory.",
          "Douglas MacArthur", "general", 1880, 1964),
    Quote("Victorious warriors win first and then go to war.",
          "Sun Tzu", "general", -544, -496, approx=True),
    Quote("Nothing except a battle lost can be half so melancholy "
          "as a battle won.",
          "Arthur Wellesley, Duke of Wellington", "field marshal", 1769, 1852),
    Quote("The god of war hates those who hesitate.",
          "Euripides", "playwright", -480, -406, approx=True),
]
