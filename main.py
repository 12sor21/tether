"""
TETHER  —  a one-thumb arcade game with jiggly tether physics.

You drag the ANCHOR (the ring). A heavy BOB hangs off it on a springy tether and
swings, lags and overshoots. You don't control the bob directly -- you *whip* it.

Two modes:
  * LEVELS    -- thread the bob to the green exit through walls and hazards.
                 Numbered, with unlock + stars saved between runs. Every level is
                 guaranteed beatable on a single life (a no-hit route exists).
  * SURVIVAL  -- endless arena: whip the bob through orbs for score + combo while
                 dodging an ever-growing swarm of mines.

Difficulty sets your lives:  Easy 5  ·  Medium 3  ·  Hard 1   (applies to both modes).

Obstacle types: solid+dangerous walls, static mines, patrolling moving mines,
rotating spinners.  Touch-only; everything is drawn immediate-mode on a
per-frame-cleared canvas so no screen can stick.  Build to Android with Buildozer.
"""

import math
import random
from collections import deque

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, Rectangle
from kivy.storage.jsonstore import JsonStore
from kivy.uix.widget import Widget
from kivy.utils import platform

# --- States -----------------------------------------------------------------
MENU, SELECT, PLAYING, PAUSED, CLEAR, FAILED = \
    "menu", "select", "playing", "paused", "clear", "failed"
LEVEL, SURVIVAL = "level", "survival"

# --- Difficulty -------------------------------------------------------------
DIFFS = ["easy", "medium", "hard"]
DIFF_LIVES = {"easy": 5, "medium": 3, "hard": 1}
DIFF_LABEL = {"easy": "Easy", "medium": "Medium", "hard": "Hard"}

# --- Physics (fixed timestep) -----------------------------------------------
STEP = 1.0 / 60.0
MAX_STEPS = 5
REF = 560.0
ANCHOR_ACCEL = 0.9
ANCHOR_FRICTION = 0.88
ANCHOR_MAX = 9.0
SPRING_K = 0.045
SPRING_DAMP = 0.94
TRAIL_LEN = 16
IFRAMES = 70

# --- Survival tuning --------------------------------------------------------
S_ORB_MAX = 5
S_ORB_SPAWN_EVERY = 42
S_ORB_LIFETIME = 320
S_MINE_START = 2
S_MINE_MAX = 10
S_MINE_RAMP_EVERY = 540
S_COMBO_WINDOW = 150

# --- Palette ----------------------------------------------------------------
BG = (0.043, 0.055, 0.078)
GRIDLINE = (0.078, 0.098, 0.145)
WALL_C = (0.27, 0.33, 0.46)
WALL_EDGE = (0.40, 0.49, 0.66)
ANCHOR_C = (0.60, 0.655, 0.74)
TETHER_C = (0.227, 0.29, 0.40)
BOB_C = (1.0, 0.82, 0.40)
BOB_GLOW = (0.48, 0.365, 0.07)
BOB_HIT = (1.0, 0.54, 0.54)
ORB_C = (0.204, 0.878, 0.878)
ORB_DIM = (0.11, 0.43, 0.43)
MINE_C = (1.0, 0.337, 0.439)
MINE_CORE = (0.478, 0.122, 0.18)
SPIN_C = (1.0, 0.45, 0.65)
GOAL_C = (0.42, 0.95, 0.45)
GOAL_DIM = (0.16, 0.45, 0.20)
TITLE_C = (1.0, 0.82, 0.40, 1)
TEXT_C = (0.9, 0.9, 0.9, 1)
DIM_C = (0.66, 0.66, 0.66, 1)
BTN_C = (0.13, 0.17, 0.25, 1)
BTN_EDGE = (0.42, 0.52, 0.70, 1)
BTN_SEL = (0.20, 0.30, 0.20, 1)
BTN_SEL_EDGE = (0.42, 0.85, 0.45, 1)
BTN_LOCK = (0.10, 0.12, 0.16, 1)
STAR_C = (1.0, 0.82, 0.40, 1)
COMBO_TXT = (0.204, 0.878, 0.878, 1)

Window.clearcolor = (*BG, 1)

# --- Levels (ASCII grids; rows top->bottom, all rows same width) ------------
# '#' wall  '.' empty  'S' start  'G' goal
# 'x' static mine  'm' moving mine  '*' orb  'O' spinner
LEVELS = [
    {"name": "First Steps", "grid": [
        ".........",
        "...S.....",
        ".........",
        ".....x...",
        ".........",
        "...*.....",
        ".......x.",
        ".........",
        "...x.....",
        ".....G...",
        ".........",
    ]},
    {"name": "Detour", "grid": [
        ".........",
        ".S.......",
        ".....###.",
        ".....m...",
        ".###.....",
        "....*....",
        ".....###.",
        ".........",
        ".###.....",
        "......G..",
        ".........",
    ]},
    {"name": "Patrol", "grid": [
        ".........",
        ".S.......",
        "....m....",
        "...###...",
        ".........",
        "..m..*.m.",
        ".........",
        "...###...",
        "....m....",
        "......G..",
        ".........",
    ]},
    {"name": "The Maze", "grid": [
        "#########",
        "#S......#",
        "#######.#",
        "#.......#",
        "#.#######",
        "#......*#",
        "#######.#",
        "#.......#",
        "#.#######",
        "#......G#",
        "#########",
    ]},
    {"name": "Spikes & Halls", "grid": [
        "#########",
        "#S......#",
        "#.#####.#",
        "#...m...#",
        "#.#####.#",
        "#x......#",
        "#.#####.#",
        "#...m..*#",
        "#####.#.#",
        "#.......#",
        "#.#####.#",
        "#x....G.#",
        "#########",
    ]},
    {"name": "Gauntlet", "grid": [
        ".........",
        ".S.......",
        "....O....",
        ".........",
        "..x...x..",
        "....*....",
        "..m...m..",
        ".........",
        "....O....",
        ".........",
        "......G..",
        ".........",
    ]},
    {"name": "Slalom", "grid": [
        ".........",
        ".S.......",
        "...#.....",
        ".....m...",
        ".#.....#.",
        "....*....",
        ".#.....#.",
        "...m.....",
        ".....#...",
        ".......G.",
        ".........",
    ]},
    {"name": "Pinwheel", "grid": [
        ".........",
        ".S.......",
        ".........",
        "...O.....",
        ".........",
        "..x...x..",
        ".....*...",
        ".........",
        ".....O...",
        ".......G.",
        ".........",
    ]},
    {"name": "Switchback", "grid": [
        "#########",
        "#S......#",
        "#.#######",
        "#......m#",
        "#######.#",
        "#m......#",
        "#.#######",
        "#......m#",
        "#######.#",
        "#.......#",
        "#.#######",
        "#......G#",
        "#########",
    ]},
    {"name": "Minefield", "grid": [
        ".........",
        ".S.......",
        "...x.x...",
        ".........",
        ".x.....x.",
        "....*....",
        ".x.....x.",
        ".........",
        "...x.x...",
        ".......G.",
        ".........",
    ]},
    {"name": "Twin Spins", "grid": [
        ".........",
        ".S.......",
        "....O....",
        ".........",
        ".........",
        "..*...*..",
        ".........",
        ".........",
        "....O....",
        ".......G.",
        ".........",
    ]},
    {"name": "Tight Squeeze", "grid": [
        "#########",
        "#......S#",
        "#.#######",
        "#.......#",
        "#######.#",
        "#.......#",
        "#.#######",
        "#.......#",
        "#######.#",
        "#.......#",
        "#.#######",
        "#G......#",
        "#########",
    ]},
    {"name": "Box Step", "grid": [
        ".........",
        ".S.......",
        "..##.....",
        ".........",
        ".....##..",
        "...*.....",
        "..##.....",
        ".........",
        ".....##..",
        ".......G.",
        ".........",
    ]},
    {"name": "The Comb", "grid": [
        ".........",
        ".S.......",
        ".#.#.#.#.",
        ".#.#.#.#.",
        ".........",
        "....*....",
        ".#.#.#.#.",
        ".#.#.#.#.",
        ".........",
        ".......G.",
        ".........",
    ]},
    {"name": "Spinner Alley", "grid": [
        ".........",
        ".S.......",
        ".........",
        "..O.O.O..",
        ".........",
        "....*....",
        ".........",
        "..O.O.O..",
        ".........",
        ".......G.",
        ".........",
    ]},
    {"name": "Zigzag", "grid": [
        "#########",
        "#S......#",
        "#.#######",
        "#...O...#",
        "#######.#",
        "#.......#",
        "#.#######",
        "#...O...#",
        "#######.#",
        "#.......#",
        "#.#######",
        "#......G#",
        "#########",
    ]},
    {"name": "Bunkers", "grid": [
        ".........",
        ".S.......",
        "..##.....",
        "..##.x...",
        ".........",
        "...*.....",
        "...x.##..",
        ".....##..",
        ".........",
        ".......G.",
        ".........",
    ]},
    {"name": "Gauntlet II", "grid": [
        ".........",
        ".S.......",
        "...O.....",
        ".........",
        ".x.....x.",
        "....*..m.",
        ".x.....x.",
        ".........",
        ".....O...",
        ".......G.",
        ".........",
    ]},
    {"name": "The Cage", "grid": [
        "#########",
        "#......S#",
        "#######.#",
        "#m......#",
        "#.#######",
        "#......O#",
        "#######.#",
        "#m......#",
        "#.#######",
        "#......m#",
        "#######.#",
        "#G......#",
        "#########",
    ]},
    {"name": "Final", "grid": [
        "#########",
        "#S......#",
        "#.#######",
        "#....O..#",
        "#######.#",
        "#..m....#",
        "#.#######",
        "#....m..#",
        "#######.#",
        "#..O....#",
        "#.#######",
        "#......G#",
        "#########",
    ]},
]

# bob may physically occupy any non-wall cell
PASSABLE = set(".SGxm*O")
# a NO-HIT route (1 life) must avoid walls AND static-mine cells
SAFE = set(".SGm*O")


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _find(grid, ch):
    for i, row in enumerate(grid):
        j = row.find(ch)
        if j >= 0:
            return (i, j)
    return None


def _bfs(grid, passable):
    rows, cols = len(grid), len(grid[0])
    s, g = _find(grid, "S"), _find(grid, "G")
    if not s or not g:
        return False
    seen, q = {s}, deque([s])
    while q:
        i, j = q.popleft()
        if (i, j) == g:
            return True
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < rows and 0 <= nj < cols and (ni, nj) not in seen \
                    and grid[ni][nj] in passable:
                seen.add((ni, nj))
                q.append((ni, nj))
    return False


def solvable(grid):
    """Connectivity through any non-wall cell."""
    return _bfs(grid, PASSABLE)


def no_hit_solvable(grid):
    """A route exists avoiding walls AND static mines -> beatable on 1 life."""
    return _bfs(grid, SAFE)


class MovingMine:
    __slots__ = ("x", "y", "vx", "vy")

    def __init__(self, x, y, vx, vy):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy


class SoundBank:
    def __init__(self):
        self.sounds = {}
        try:
            from kivy.core.audio import SoundLoader
            from os.path import dirname, join, exists
            base = join(dirname(__file__), "data")
            for name in ("pickup", "hit", "start", "win"):
                for ext in (".ogg", ".wav"):
                    p = join(base, name + ext)
                    if exists(p):
                        s = SoundLoader.load(p)
                        if s:
                            self.sounds[name] = s
                        break
        except Exception:
            pass

    def play(self, name, volume=1.0):
        s = self.sounds.get(name)
        if s:
            try:
                s.stop()
                s.volume = volume
                s.play()
            except Exception:
                pass


class GameWidget(Widget):
    def __init__(self, store, sounds, **kw):
        super().__init__(**kw)
        self.store = store
        self.sounds = sounds
        self.progress = self._load_progress()
        self.difficulty = self.store.get("diff")["v"] \
            if self.store.exists("diff") else "medium"
        self.best = self._load_best()    # per-difficulty: {"easy": n, ...}

        self.state = MENU
        self.mode = LEVEL
        self.level_idx = 0
        self.cur = None
        self.held = set()
        self.steering = False
        self._steer_touch = None
        self.target = (0, 0)
        self.accum = 0.0
        self.shake = 0.0
        self._tex_cache = {}
        self._buttons = []
        self._tiles = []
        self._ready = False

        Window.bind(on_key_down=self._key_down, on_key_up=self._key_up)
        Clock.schedule_interval(self.tick, 0)
        self.bind(size=lambda *a: self._on_size())

    def lives_for_difficulty(self):
        return DIFF_LIVES[self.difficulty]

    def _load_best(self):
        if self.store.exists("best"):
            v = self.store.get("best").get("v")
            if isinstance(v, dict):
                return {k: int(n) for k, n in v.items()}
        return {}

    def best_cur(self):
        """Survival best for the CURRENTLY selected difficulty."""
        return int(self.best.get(self.difficulty, 0))

    # --- Persistence --------------------------------------------------------
    def _load_progress(self):
        if self.store.exists("prog"):
            d = self.store.get("prog")
            return {"unlocked": d.get("unlocked", 1),
                    "stars": {int(k): v for k, v in d.get("stars", {}).items()}}
        return {"unlocked": 1, "stars": {}}

    def _save_progress(self):
        try:
            self.store.put("prog", unlocked=self.progress["unlocked"],
                           stars={str(k): v for k, v in self.progress["stars"].items()})
        except Exception:
            pass

    # --- Layout -------------------------------------------------------------
    def _on_size(self):
        w, h = self.size
        self.scale = max(1.0, min(w, h))
        self.sf = self.scale / REF
        self.margin = self.scale * 0.025
        self.accel = ANCHOR_ACCEL * self.sf
        self.vmax = ANCHOR_MAX * self.sf
        self._tex_cache.clear()
        if self.cur:
            self._layout_level()
        self._survival_geom()
        if w > 1 and h > 1:
            self._ready = True

    def _layout_level(self):
        rows, cols = self.cur["rows"], self.cur["cols"]
        x0, y0 = self.margin, self.margin
        pw = self.width - 2 * self.margin
        ph = self.height - 2 * self.margin - self.scale * 0.06
        cell = min(pw / cols, ph / rows)
        self.cell = cell
        gw, gh = cell * cols, cell * rows
        self.gx0 = x0 + (pw - gw) / 2
        self.gy0 = y0 + (ph - gh) / 2
        self.r_bob = cell * 0.27
        self.r_anchor = cell * 0.16
        self.r_mine = cell * 0.30
        self.r_orb = cell * 0.20
        self.r_goal = cell * 0.46
        self.bob_vmax = cell * 0.7

    def _survival_geom(self):
        s = self.scale
        self.sr_bob = s * 0.030
        self.sr_anchor = s * 0.016
        self.sr_orb = s * 0.022
        self.sr_mine = s * 0.026

    def cell_rect(self, i, j):
        ry = self.gy0 + (self.cur["rows"] - 1 - i) * self.cell
        return (self.gx0 + j * self.cell, ry, self.cell, self.cell)

    def cell_center(self, i, j):
        rx, ry, c, _ = self.cell_rect(i, j)
        return (rx + c / 2, ry + c / 2)

    def pixel_cell(self, x, y):
        j = int((x - self.gx0) // self.cell)
        i = self.cur["rows"] - 1 - int((y - self.gy0) // self.cell)
        return i, j

    def is_wall(self, i, j):
        return (i, j) in self.cur["walls"]

    # --- Level load / start -------------------------------------------------
    def load_level(self, idx):
        spec = LEVELS[idx]
        grid = spec["grid"]
        rows, cols = len(grid), len(grid[0])
        walls, statics, movers, orbs, spinners = set(), [], [], [], []
        for i, row in enumerate(grid):
            for j, ch in enumerate(row):
                if ch == "#":
                    walls.add((i, j))
                elif ch == "x":
                    statics.append((i, j))
                elif ch == "m":
                    movers.append((i, j))
                elif ch == "*":
                    orbs.append((i, j))
                elif ch == "O":
                    spinners.append((i, j))
        self.cur = {"name": spec["name"], "grid": grid, "rows": rows, "cols": cols,
                    "walls": walls, "start": _find(grid, "S"), "goal": _find(grid, "G"),
                    "statics": statics, "movers": movers, "orbs": orbs,
                    "spinners": spinners}
        self.level_idx = idx
        self._layout_level()

    def start_level(self, idx):
        self.mode = LEVEL
        self.load_level(idx)
        c = self.cur
        sx, sy = self.cell_center(*c["start"])
        self.ax, self.ay = sx, sy
        self.avx = self.avy = 0.0
        self.bx, self.by = sx, sy
        self.bvx = self.bvy = 0.0
        self.trail = []
        self.lives = self.lives_for_difficulty()
        self.iframes = self.flash = 0
        self.steps = self.collected = 0
        self.steering = False
        self._steer_touch = None

        self.mmines = []
        for (i, j) in c["movers"]:
            cx, cy = self.cell_center(i, j)
            horiz = (not self.is_wall(i, j - 1)) or (not self.is_wall(i, j + 1))
            vert = (not self.is_wall(i - 1, j)) or (not self.is_wall(i + 1, j))
            spd = self.cell * 0.03
            if horiz and not vert:
                vx, vy = spd, 0.0
            elif vert and not horiz:
                vx, vy = 0.0, spd
            else:
                vx, vy = (spd, 0.0) if random.random() < 0.5 else (0.0, spd)
            self.mmines.append(MovingMine(cx, cy, vx, vy))
        self.spinners = []
        for (i, j) in c["spinners"]:
            cx, cy = self.cell_center(i, j)
            self.spinners.append({"cx": cx, "cy": cy, "ang": random.uniform(0, 6.28),
                                  "len": self.cell * 2.1, "spd": 0.035})
        self.orbs = [{"x": self.cell_center(i, j)[0], "y": self.cell_center(i, j)[1],
                      "got": False} for (i, j) in c["orbs"]]
        self.goal_xy = self.cell_center(*c["goal"])
        self.state = PLAYING
        self.sounds.play("start")

    # --- Survival start -----------------------------------------------------
    def start_survival(self):
        self.mode = SURVIVAL
        self.cur = None
        self._survival_geom()
        cx, cy = self.width / 2, self.height / 2
        self.ax, self.ay = cx, cy
        self.avx = self.avy = 0.0
        self.bx, self.by = cx, cy - self.scale * 0.10
        self.bvx = self.bvy = 0.0
        self.trail = []
        self.lives = self.lives_for_difficulty()
        self.iframes = self.flash = 0
        self.steps = self.orb_timer = 0
        self.score = 0
        self.combo = 1
        self.combo_timer = 0
        self.steering = False
        self._steer_touch = None
        self.smines = [self._survival_mine() for _ in range(S_MINE_START)]
        self.sorbs = []
        self.state = PLAYING
        self.sounds.play("start")

    def _survival_mine(self):
        m = self.margin
        rr = self.sr_mine
        for _ in range(40):
            x = random.uniform(m + rr, self.width - m - rr)
            y = random.uniform(m + rr, self.height - m - rr)
            if math.hypot(x - self.bx, y - self.by) > self.scale * 0.25:
                break
        ang = random.uniform(0, math.tau)
        spd = random.uniform(0.6, 1.6) * self.sf
        return MovingMine(x, y, math.cos(ang) * spd, math.sin(ang) * spd)

    # --- Input --------------------------------------------------------------
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        px, py = touch.pos
        for b in self._buttons:
            if b["enabled"] and self._hit(px, py, b):
                self._do(b["action"])
                return True
        if self.state == PLAYING:
            self.steering = True
            self._steer_touch = touch
            self.target = (px, py)
            return True
        return False

    def on_touch_move(self, touch):
        if self.state == PLAYING and touch is self._steer_touch:
            self.target = touch.pos
            return True
        return False

    def on_touch_up(self, touch):
        if touch is self._steer_touch:
            self.steering = False
            self._steer_touch = None
        return False

    @staticmethod
    def _hit(px, py, b):
        return b["x"] <= px <= b["x"] + b["w"] and b["y"] <= py <= b["y"] + b["h"]

    def _do(self, action):
        if action == "play":
            self.state = SELECT
        elif action == "survival":
            self.start_survival()
        elif action == "menu":
            self.state = MENU
        elif action == "select":
            self.state = SELECT
        elif action == "resume":
            self.state = PLAYING
        elif action == "pause":
            self.state = PAUSED
        elif action == "retry":
            if self.mode == SURVIVAL:
                self.start_survival()
            else:
                self.start_level(self.level_idx)
        elif action == "next":
            if self.level_idx + 1 < len(LEVELS):
                self.start_level(self.level_idx + 1)
            else:
                self.state = SELECT
        elif action.startswith("diff:"):
            self.difficulty = action.split(":")[1]
            try:
                self.store.put("diff", v=self.difficulty)
            except Exception:
                pass
        elif action.startswith("level:"):
            idx = int(action.split(":")[1])
            if idx < self.progress["unlocked"]:
                self.start_level(idx)

    def _key_down(self, win, key, scancode, codepoint, modifier):
        if key == 112 and self.state in (PLAYING, PAUSED):
            self.state = PAUSED if self.state == PLAYING else PLAYING
            return
        self.held.add(key)

    def _key_up(self, win, key, scancode):
        self.held.discard(key)

    def _keyboard_thrust(self):
        tx = ty = 0.0
        if self.held & {276, 97}:
            tx -= self.accel
        if self.held & {275, 100}:
            tx += self.accel
        if self.held & {273, 119}:
            ty += self.accel
        if self.held & {274, 115}:
            ty -= self.accel
        return tx, ty

    # --- Loop ---------------------------------------------------------------
    def tick(self, dt):
        if not self._ready:
            self._on_size()
            if not self._ready:
                return
        if self.state == PLAYING:
            self.accum += min(dt, STEP * MAX_STEPS)
            n = 0
            while self.accum >= STEP and n < MAX_STEPS:
                if self.mode == SURVIVAL:
                    self.step_survival()
                else:
                    self.step_level()
                self.accum -= STEP
                n += 1
                if self.state != PLAYING:
                    break
        self.render()

    def _move_anchor(self, x0, y0, x1, y1):
        thx, thy = self._keyboard_thrust()
        if self.steering:
            dx, dy = self.target[0] - self.ax, self.target[1] - self.ay
            d = math.hypot(dx, dy)
            if d > 1:
                f = min(1.0, d / (self.scale * 0.07))
                thx += (dx / d) * self.accel * f
                thy += (dy / d) * self.accel * f
        self.avx = clamp((self.avx + thx) * ANCHOR_FRICTION, -self.vmax, self.vmax)
        self.avy = clamp((self.avy + thy) * ANCHOR_FRICTION, -self.vmax, self.vmax)
        self.ax = clamp(self.ax + self.avx, x0, x1)
        self.ay = clamp(self.ay + self.avy, y0, y1)

    def _decay_fx(self):
        if self.iframes > 0:
            self.iframes -= 1
        if self.flash > 0:
            self.flash -= 1
        if self.shake > 0:
            self.shake *= 0.85
            if self.shake < 0.5:
                self.shake = 0

    # --- Level physics ------------------------------------------------------
    def step_level(self):
        self.steps += 1
        x0, y0 = self.gx0, self.gy0
        x1 = self.gx0 + self.cell * self.cur["cols"]
        y1 = self.gy0 + self.cell * self.cur["rows"]
        self._move_anchor(x0, y0, x1, y1)

        self.bvx = (self.bvx + (self.ax - self.bx) * SPRING_K) * SPRING_DAMP
        self.bvy = (self.bvy + (self.ay - self.by) * SPRING_K) * SPRING_DAMP
        sp = math.hypot(self.bvx, self.bvy)
        if sp > self.bob_vmax:
            self.bvx *= self.bob_vmax / sp
            self.bvy *= self.bob_vmax / sp
        self.bx += self.bvx
        self.by += self.bvy

        rb = self.r_bob
        if self.bx < x0 + rb:
            self.bx, self.bvx = x0 + rb, abs(self.bvx) * 0.5
        elif self.bx > x1 - rb:
            self.bx, self.bvx = x1 - rb, -abs(self.bvx) * 0.5
        if self.by < y0 + rb:
            self.by, self.bvy = y0 + rb, abs(self.bvy) * 0.5
        elif self.by > y1 - rb:
            self.by, self.bvy = y1 - rb, -abs(self.bvy) * 0.5

        ci, cj = self.pixel_cell(self.bx, self.by)
        touched = False
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if (ci + di, cj + dj) in self.cur["walls"]:
                    if self._collide_rect(self.cell_rect(ci + di, cj + dj)):
                        touched = True
        if touched:
            self._hurt()

        self.trail.append((self.bx, self.by))
        if len(self.trail) > TRAIL_LEN:
            self.trail.pop(0)

        for (i, j) in self.cur["statics"]:
            mx, my = self.cell_center(i, j)
            if math.hypot(mx - self.bx, my - self.by) < rb + self.r_mine:
                self._hurt(mx, my)

        for m in self.mmines:
            m.x += m.vx
            m.y += m.vy
            mi, mj = self.pixel_cell(m.x, m.y)
            ni = mi - (1 if m.vy > 0 else -1 if m.vy < 0 else 0)
            nj = mj + (1 if m.vx > 0 else -1 if m.vx < 0 else 0)
            if not (0 <= nj < self.cur["cols"]) or not (0 <= ni < self.cur["rows"]) \
                    or self.is_wall(ni, nj):
                m.vx, m.vy = -m.vx, -m.vy
            if math.hypot(m.x - self.bx, m.y - self.by) < rb + self.r_mine:
                self._hurt(m.x, m.y)

        for s in self.spinners:
            s["ang"] += s["spd"]
            ex = s["cx"] + math.cos(s["ang"]) * s["len"]
            ey = s["cy"] + math.sin(s["ang"]) * s["len"]
            if self._point_seg(self.bx, self.by, s["cx"], s["cy"], ex, ey) \
                    < rb + self.cell * 0.10:
                self._hurt(s["cx"], s["cy"])

        for o in self.orbs:
            if not o["got"] and math.hypot(o["x"] - self.bx, o["y"] - self.by) < rb + self.r_orb:
                o["got"] = True
                self.collected += 1
                self.sounds.play("pickup", volume=0.7)

        if math.hypot(self.goal_xy[0] - self.bx, self.goal_xy[1] - self.by) < self.r_goal:
            self._level_clear()
        self._decay_fx()

    # --- Survival physics ---------------------------------------------------
    def step_survival(self):
        self.steps += 1
        m = self.margin
        x0, y0, x1, y1 = m, m, self.width - m, self.height - m
        self._move_anchor(x0, y0, x1, y1)
        rb = self.sr_bob

        self.bvx = (self.bvx + (self.ax - self.bx) * SPRING_K) * SPRING_DAMP
        self.bvy = (self.bvy + (self.ay - self.by) * SPRING_K) * SPRING_DAMP
        self.bx += self.bvx
        self.by += self.bvy
        if self.bx < x0 + rb or self.bx > x1 - rb:
            self.bvx *= -0.6
            self.bx = clamp(self.bx, x0 + rb, x1 - rb)
        if self.by < y0 + rb or self.by > y1 - rb:
            self.bvy *= -0.6
            self.by = clamp(self.by, y0 + rb, y1 - rb)

        self.trail.append((self.bx, self.by))
        if len(self.trail) > TRAIL_LEN:
            self.trail.pop(0)

        self.orb_timer += 1
        if self.orb_timer >= S_ORB_SPAWN_EVERY and len(self.sorbs) < S_ORB_MAX:
            self.orb_timer = 0
            ox = random.uniform(x0 + self.sr_orb, x1 - self.sr_orb)
            oy = random.uniform(y0 + self.sr_orb, y1 - self.sr_orb)
            self.sorbs.append({"x": ox, "y": oy, "life": S_ORB_LIFETIME})

        if self.steps % S_MINE_RAMP_EVERY == 0 and len(self.smines) < S_MINE_MAX:
            self.smines.append(self._survival_mine())

        for o in self.sorbs:
            o["life"] -= 1
        self.sorbs = [o for o in self.sorbs if o["life"] > 0]

        if self.combo_timer > 0:
            self.combo_timer -= 1
            if self.combo_timer == 0:
                self.combo = 1

        kept = []
        for o in self.sorbs:
            if math.hypot(o["x"] - self.bx, o["y"] - self.by) < rb + self.sr_orb:
                self.combo = min(self.combo + 1, 9) if self.combo_timer > 0 else 2
                self.combo_timer = S_COMBO_WINDOW
                self.score += 10 * self.combo
                self.flash = 6
                self.sounds.play("pickup", volume=0.7)
            else:
                kept.append(o)
        self.sorbs = kept

        for mm in self.smines:
            mm.x += mm.vx
            mm.y += mm.vy
            if mm.x < x0 + self.sr_mine or mm.x > x1 - self.sr_mine:
                mm.vx *= -1
                mm.x = clamp(mm.x, x0 + self.sr_mine, x1 - self.sr_mine)
            if mm.y < y0 + self.sr_mine or mm.y > y1 - self.sr_mine:
                mm.vy *= -1
                mm.y = clamp(mm.y, y0 + self.sr_mine, y1 - self.sr_mine)
        if self.iframes <= 0:
            for mm in self.smines:
                if math.hypot(mm.x - self.bx, mm.y - self.by) < rb + self.sr_mine:
                    self.combo = 1
                    self.combo_timer = 0
                    self._hurt(mm.x, mm.y)
                    break
        self._decay_fx()

    # --- Collision helpers --------------------------------------------------
    def _collide_rect(self, rect):
        rx, ry, rw, rh = rect
        nx = clamp(self.bx, rx, rx + rw)
        ny = clamp(self.by, ry, ry + rh)
        dx, dy = self.bx - nx, self.by - ny
        d2 = dx * dx + dy * dy
        rb = self.r_bob
        if d2 >= rb * rb:
            return False
        d = math.sqrt(d2) if d2 > 1e-6 else 0.0
        if d > 0:
            push = rb - d
            self.bx += dx / d * push
            self.by += dy / d * push
            nxn, nyn = dx / d, dy / d
            dot = self.bvx * nxn + self.bvy * nyn
            self.bvx -= 1.5 * dot * nxn
            self.bvy -= 1.5 * dot * nyn
        else:
            self.by += rb
        return True

    @staticmethod
    def _point_seg(px, py, ax, ay, bx, by):
        vx, vy = bx - ax, by - ay
        wx, wy = px - ax, py - ay
        seg = vx * vx + vy * vy
        t = 0.0 if seg <= 1e-6 else clamp((wx * vx + wy * vy) / seg, 0.0, 1.0)
        cx, cy = ax + t * vx, ay + t * vy
        return math.hypot(px - cx, py - cy)

    def _hurt(self, hx=None, hy=None):
        if self.iframes > 0:
            return
        self.lives -= 1
        self.iframes = IFRAMES
        self.shake = self.scale * 0.02
        self.flash = 6
        self.sounds.play("hit")
        if hx is not None:
            ang = math.atan2(self.by - hy, self.bx - hx)
            kick = 6 * (self.sf if self.mode == SURVIVAL else 1.0)
            self.bvx += math.cos(ang) * kick
            self.bvy += math.sin(ang) * kick
        if self.lives <= 0:
            self._game_over()

    def _game_over(self):
        if self.mode == SURVIVAL and self.score > self.best_cur():
            self.best[self.difficulty] = self.score
            try:
                self.store.put("best", v=self.best)
            except Exception:
                pass
        self.state = FAILED

    def _level_clear(self):
        self.state = CLEAR
        base = {"easy": 1, "medium": 2, "hard": 3}[self.difficulty]
        if self.orbs and self.collected >= len(self.orbs) and base < 3:
            base += 1
        stars = min(3, base)
        self.last_stars = stars
        prev = self.progress["stars"].get(self.level_idx, 0)
        self.progress["stars"][self.level_idx] = max(prev, stars)
        if self.level_idx + 1 == self.progress["unlocked"]:
            self.progress["unlocked"] = min(len(LEVELS), self.progress["unlocked"] + 1)
        self._save_progress()
        self.sounds.play("win")

    # --- Text ---------------------------------------------------------------
    def _tex(self, text, fs, bold=False, mw=None):
        key = (text, int(fs), bold, int(mw or 0))
        t = self._tex_cache.get(key)
        if t is None:
            kw = dict(text=text, font_size=int(fs), bold=bold)
            if mw:
                kw["text_size"] = (mw, None)
                kw["halign"] = "center"
            cl = CoreLabel(**kw)
            cl.refresh()
            t = cl.texture
            if len(self._tex_cache) > 400:
                self._tex_cache.clear()
            self._tex_cache[key] = t
        return t

    def _text(self, text, cx, cy, fs, color, bold=False, mw=None, anchor="center"):
        t = self._tex(text, fs, bold, mw)
        if not t:
            return
        w, h = t.size
        if anchor == "center":
            pos = (cx - w / 2, cy - h / 2)
        elif anchor == "tl":
            pos = (cx, cy - h)
        else:
            pos = (cx - w, cy - h)
        Color(*color)
        Rectangle(texture=t, pos=pos, size=(w, h))

    # --- Buttons ------------------------------------------------------------
    def _btn(self, x, y, w, h, label, action, enabled=True, fs=None,
             locked=False, sel=False):
        self._buttons.append({"x": x, "y": y, "w": w, "h": h, "label": label,
                              "action": action, "enabled": enabled,
                              "fs": fs or self.scale * 0.040, "locked": locked,
                              "sel": sel})

    def _draw_buttons(self):
        for b in self._buttons:
            if b["locked"]:
                fill, edge = BTN_LOCK, DIM_C
            elif b["sel"]:
                fill, edge = BTN_SEL, BTN_SEL_EDGE
            else:
                fill, edge = BTN_C, BTN_EDGE
            Color(*fill)
            Rectangle(pos=(b["x"], b["y"]), size=(b["w"], b["h"]))
            Color(*edge)
            Line(rectangle=(b["x"], b["y"], b["w"], b["h"]), width=1.4)
            if b["label"]:
                self._text(b["label"], b["x"] + b["w"] / 2, b["y"] + b["h"] / 2,
                           b["fs"], DIM_C if b["locked"] else TEXT_C, bold=True)

    def _lock(self, cx, cy, sz):
        Color(*DIM_C)
        bw, bh = sz, sz * 0.72
        Rectangle(pos=(cx - bw / 2, cy - bh / 2), size=(bw, bh))
        top = cy + bh / 2
        sh = sz * 0.30
        Line(points=[cx - sz * 0.22, top, cx - sz * 0.22, top + sh,
                     cx + sz * 0.22, top + sh, cx + sz * 0.22, top], width=1.6)

    # --- Rendering ----------------------------------------------------------
    def render(self):
        self.canvas.clear()
        self._buttons = []
        if not self._ready:
            return
        w, h, s = self.width, self.height, self.scale
        with self.canvas:
            Color(*BG)
            Rectangle(pos=(0, 0), size=(w, h))
            Color(*GRIDLINE)
            g = s * 0.07
            x = 0
            while x < w:
                Line(points=[x, 0, x, h], width=1)
                x += g
            y = 0
            while y < h:
                Line(points=[0, y, w, y], width=1)
                y += g

            if self.state in (PLAYING, PAUSED, CLEAR, FAILED):
                if self.mode == SURVIVAL:
                    self._draw_survival()
                elif self.cur:
                    self._draw_level()

            if self.state == MENU:
                self._draw_menu()
            elif self.state == SELECT:
                self._draw_select()
            elif self.state == PLAYING:
                self._draw_play_hud()
            elif self.state == PAUSED:
                self._overlay("PAUSED", None)
                self._stack(["Resume", "Retry", "Menu"], ["resume", "retry", "menu"])
            elif self.state == CLEAR:
                self._overlay("LEVEL CLEAR", None, stars=getattr(self, "last_stars", 0))
                nx = self.level_idx + 1 < len(LEVELS)
                self._stack(["Next", "Retry", "Levels"] if nx else ["Retry", "Levels"],
                            ["next", "retry", "select"] if nx else ["retry", "select"])
            elif self.state == FAILED:
                if self.mode == SURVIVAL:
                    self._overlay("GAME OVER",
                                  f"Score {self.score}    Best {self.best_cur()}  "
                                  f"({DIFF_LABEL[self.difficulty]})")
                    self._stack(["Retry", "Menu"], ["retry", "menu"])
                else:
                    self._overlay("FAILED", "The bob couldn't make it.")
                    self._stack(["Retry", "Levels"], ["retry", "select"])
            self._draw_buttons()
            # Tile decorations (numbers/stars/locks) go ON TOP of the button fills.
            if self.state == SELECT:
                self._draw_tile_overlay()

    # ----- world: level
    def _draw_level(self):
        ox = oy = 0.0
        if self.shake:
            ox = random.uniform(-self.shake, self.shake)
            oy = random.uniform(-self.shake, self.shake)
        s, cell = self.scale, self.cell
        for (i, j) in self.cur["walls"]:
            rx, ry, c, _ = self.cell_rect(i, j)
            Color(*WALL_C)
            Rectangle(pos=(rx + ox, ry + oy), size=(c, c))
            Color(*WALL_EDGE)
            Line(rectangle=(rx + ox, ry + oy, c, c), width=1.2)

        gx, gy = self.goal_xy
        pulse = 1 + 0.12 * math.sin(self.steps * 0.12)
        Color(*GOAL_DIM)
        self._disc(gx + ox, gy + oy, self.r_goal * 1.15 * pulse)
        Color(*GOAL_C)
        Line(circle=(gx + ox, gy + oy, self.r_goal * pulse), width=2.2)
        self._disc(gx + ox, gy + oy, self.r_goal * 0.30)

        for o in self.orbs:
            if o["got"]:
                continue
            Color(*ORB_DIM)
            self._disc(o["x"] + ox, o["y"] + oy, self.r_orb + s * 0.005)
            Color(*ORB_C)
            self._disc(o["x"] + ox, o["y"] + oy, self.r_orb)

        for (i, j) in self.cur["statics"]:
            mx, my = self.cell_center(i, j)
            self._mine(mx + ox, my + oy, self.r_mine)
        for m in self.mmines:
            self._mine(m.x + ox, m.y + oy, self.r_mine)
        for sp in self.spinners:
            ex = sp["cx"] + math.cos(sp["ang"]) * sp["len"]
            ey = sp["cy"] + math.sin(sp["ang"]) * sp["len"]
            Color(*SPIN_C)
            Line(points=[sp["cx"] + ox, sp["cy"] + oy, ex + ox, ey + oy],
                 width=max(2, cell * 0.10))
            self._disc(ex + ox, ey + oy, cell * 0.12)
            Color(*MINE_CORE)
            self._disc(sp["cx"] + ox, sp["cy"] + oy, cell * 0.14)

        self._draw_bob(ox, oy, self.r_bob, self.r_anchor)

    # ----- world: survival
    def _draw_survival(self):
        ox = oy = 0.0
        if self.shake:
            ox = random.uniform(-self.shake, self.shake)
            oy = random.uniform(-self.shake, self.shake)
        s = self.scale
        for o in self.sorbs:
            frac = o["life"] / S_ORB_LIFETIME
            r = self.sr_orb * (0.55 + 0.45 * frac) * (1 + 0.18 * math.sin(self.steps * 0.2))
            Color(*ORB_DIM)
            self._disc(o["x"] + ox, o["y"] + oy, r + s * 0.006)
            Color(*(ORB_C if frac > 0.35 else ORB_DIM))
            self._disc(o["x"] + ox, o["y"] + oy, r)
        for mm in self.smines:
            self._mine(mm.x + ox, mm.y + oy, self.sr_mine)
        self._draw_bob(ox, oy, self.sr_bob, self.sr_anchor)

    def _draw_bob(self, ox, oy, rb, ra):
        s = self.scale
        Color(*TETHER_C)
        Line(points=[self.ax + ox, self.ay + oy, self.bx + ox, self.by + oy],
             width=max(1.2, s * 0.004))
        n = len(self.trail)
        for k, (tx, ty) in enumerate(self.trail):
            Color(*BOB_GLOW)
            self._disc(tx + ox, ty + oy, rb * (0.25 + 0.5 * (k / max(n, 1))))
        blink = self.iframes > 0 and (self.iframes // 5) % 2 == 0
        Color(*BOB_GLOW)
        self._disc(self.bx + ox, self.by + oy, rb + s * 0.008)
        Color(*(BOB_HIT if blink else BOB_C))
        self._disc(self.bx + ox, self.by + oy, rb)
        if self.flash > 0:
            Color(*MINE_C)
            Line(circle=(self.bx + ox, self.by + oy, rb + s * 0.012 + self.flash), width=2)
        Color(*ANCHOR_C)
        Line(circle=(self.ax + ox, self.ay + oy, ra), width=max(2, s * 0.006))

    def _disc(self, x, y, r):
        Ellipse(pos=(x - r, y - r), size=(2 * r, 2 * r))

    def _mine(self, x, y, r):
        Color(*MINE_CORE)
        self._disc(x, y, r + self.scale * 0.004)
        Color(*MINE_C)
        self._disc(x, y, r)
        Color(*MINE_CORE)
        self._disc(x, y, r * 0.42)

    # ----- HUD / menus
    def _draw_play_hud(self):
        s, m = self.scale, self.margin
        if self.mode == SURVIVAL:
            self._text(f"Score {self.score}", m * 1.3, self.height - m,
                       s * 0.045, TEXT_C, bold=True, anchor="tl")
            self._text(f"Best {self.best_cur()}", m * 1.3, self.height - m - s * 0.055,
                       s * 0.028, DIM_C, anchor="tl")
            if self.combo > 1:
                self._text(f"x{self.combo}", self.width / 2, self.height - m - s * 0.02,
                           s * 0.05, COMBO_TXT, bold=True)
        else:
            self._text(f"{self.level_idx + 1}.  {self.cur['name']}", self.width / 2,
                       self.height - m - s * 0.02, s * 0.034, TEXT_C, bold=True)
            if self.orbs:
                self._text(f"orbs {self.collected}/{len(self.orbs)}", m * 1.3,
                           self.height - m - s * 0.07, s * 0.026, ORB_C, anchor="tl")
        for i in range(self.lives):
            Color(*BOB_C)
            self._disc(m * 1.5 + i * s * 0.05, self.height - m - s * 0.035, s * 0.016)
        bs = s * 0.075
        self._btn(self.width - m - bs, self.height - m - bs, bs, bs, "II",
                  "pause", fs=s * 0.035)

    def _diff_row(self, cy):
        w, s = self.width, self.scale
        bw = w * 0.26
        gap = w * 0.02
        total = 3 * bw + 2 * gap
        x = w / 2 - total / 2
        for d in DIFFS:
            self._btn(x, cy, bw, s * 0.075, DIFF_LABEL[d], f"diff:{d}",
                      fs=s * 0.03, sel=(d == self.difficulty))
            x += bw + gap

    def _draw_menu(self):
        w, h, s = self.width, self.height, self.scale
        self._text("TETHER", w / 2, h * 0.78, s * 0.13, TITLE_C, bold=True)
        self._text("Whip the jiggly bob to the exit. Mind the walls.",
                   w / 2, h * 0.69, s * 0.030, TEXT_C, mw=w * 0.86)
        self._text(f"Difficulty  ·  {DIFF_LIVES[self.difficulty]} lives",
                   w / 2, h * 0.605, s * 0.030, DIM_C)
        self._diff_row(h * 0.55 - s * 0.0375)
        bw, bh = w * 0.56, s * 0.095
        self._btn(w / 2 - bw / 2, h * 0.40, bw, bh, "PLAY  LEVELS", "play", fs=s * 0.045)
        self._btn(w / 2 - bw / 2, h * 0.28, bw, bh, "SURVIVAL", "survival", fs=s * 0.045)
        done = sum(self.progress["stars"].values())
        self._text(f"{self.progress['unlocked']}/{len(LEVELS)} levels  ·  "
                   f"{done}/{len(LEVELS) * 3} stars  ·  "
                   f"survival best {self.best_cur()} ({DIFF_LABEL[self.difficulty]})",
                   w / 2, h * 0.17, s * 0.024, DIM_C, mw=w * 0.92)

    def _draw_select(self):
        w, h, s = self.width, self.height, self.scale
        self._text("SELECT LEVEL", w / 2, h - self.margin - s * 0.045,
                   s * 0.048, TITLE_C, bold=True)
        self._text(f"{DIFF_LABEL[self.difficulty]}  ·  "
                   f"{DIFF_LIVES[self.difficulty]} lives",
                   w / 2, h - self.margin - s * 0.095, s * 0.026, DIM_C)
        self._diff_row(h * 0.80)
        # Fit a 4-wide grid of all levels inside the available box, sizing the
        # tiles by BOTH width and height so they never overflow on any aspect.
        cols = 4
        rows = (len(LEVELS) + cols - 1) // cols
        gap = min(w, h) * 0.02
        menu_h = s * 0.075
        ytop = h * 0.72
        ybot = h * 0.045 + menu_h + gap
        w_av = w * 0.92
        h_av = ytop - ybot
        tile = min((w_av - (cols - 1) * gap) / cols,
                   (h_av - (rows - 1) * gap) / rows)
        grid_w = cols * tile + (cols - 1) * gap
        gx0 = (w - grid_w) / 2
        self._tiles = []
        for idx in range(len(LEVELS)):
            r, c = divmod(idx, cols)
            x = gx0 + c * (tile + gap)
            y = ytop - tile - r * (tile + gap)
            unlocked = idx < self.progress["unlocked"]
            self._btn(x, y, tile, tile, "", f"level:{idx}", enabled=unlocked,
                      locked=not unlocked)
            self._tiles.append((idx, x, y, tile, unlocked))
        bw2 = w * 0.4
        self._btn(w / 2 - bw2 / 2, h * 0.045, bw2, menu_h, "Menu", "menu", fs=s * 0.038)

    def _draw_tile_overlay(self):
        for (idx, x, y, tile, unlocked) in self._tiles:
            cx = x + tile / 2
            self._text(str(idx + 1), cx, y + tile * (0.56 if unlocked else 0.58),
                       tile * 0.42, TEXT_C if unlocked else DIM_C, bold=True)
            if unlocked:
                self._stars(cx, y + tile * 0.24, self.progress["stars"].get(idx, 0),
                            tile * 0.085)
            else:
                self._lock(cx, y + tile * 0.30, tile * 0.34)

    def _stars(self, cx, cy, n, r):
        for k in range(3):
            x = cx + (k - 1) * r * 2.6
            Color(*(STAR_C if k < n else (0.3, 0.3, 0.34, 1)))
            self._disc(x, cy, r)

    def _overlay(self, title, sub, stars=None):
        w, h, s = self.width, self.height, self.scale
        Color(*BG, 0.66)
        Rectangle(pos=(0, 0), size=(w, h))
        self._text(title, w / 2, h * 0.66, s * 0.085, TITLE_C, bold=True)
        if stars is not None:
            self._stars(w / 2, h * 0.565, stars, s * 0.03)
        if sub:
            self._text(sub, w / 2, h * 0.50, s * 0.032, TEXT_C, mw=w * 0.85)

    def _stack(self, labels, actions):
        w, h, s = self.width, self.height, self.scale
        bw, bh = w * 0.5, s * 0.09
        gap = s * 0.025
        total = len(labels) * bh + (len(labels) - 1) * gap
        y = h * 0.42 + total - bh
        for lab, act in zip(labels, actions):
            self._btn(w / 2 - bw / 2, y, bw, bh, lab, act, fs=s * 0.04)
            y -= bh + gap


class TetherApp(App):
    def build(self):
        self.title = "Tether"
        store = JsonStore(self._store_path())
        self.game = GameWidget(store, SoundBank(), size_hint=(1, 1))
        return self.game

    def _store_path(self):
        try:
            from os.path import join
            return join(self.user_data_dir, "tether.json")
        except Exception:
            return "tether.json"

    def on_pause(self):
        if getattr(self, "game", None) and self.game.state == PLAYING:
            self.game.state = PAUSED
        return True

    def on_resume(self):
        return True


if __name__ == "__main__":
    for _lv in LEVELS:
        assert no_hit_solvable(_lv["grid"]), \
            f"Level not beatable on 1 life: {_lv['name']}"
    if platform not in ("android", "ios"):
        Window.size = (414, 736)
    TetherApp().run()
