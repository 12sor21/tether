"""
TETHER  —  a one-thumb arcade game with jiggly tether physics.

You drag the ANCHOR (the ring). A heavy BOB hangs off it on a springy tether and
swings, lags and overshoots. You don't control the bob directly -- you *whip* it.

Each LEVEL is a goal: thread the bob to the green exit without letting it touch
the walls or hazards. Because the bob jiggles, tight corridors are a real test.

Obstacle types:
    walls          solid + dangerous (touch = lose a life; the bob also bounces)
    static mines   fixed red spikes
    moving mines   patrol along corridors
    spinners       rotating bars that sweep an area

Flow:  START MENU -> LEVEL SELECT -> play a level -> CLEAR / FAILED.
Progress (unlocked levels + stars) is saved between runs.

Touch-only: tap buttons, drag to steer. Keyboard arrows also steer on desktop.
Everything is drawn immediate-mode on a per-frame-cleared canvas, so no screen
can ever "stick".  Package to Android with Buildozer (see README / buildozer.spec).
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
BTN_LOCK = (0.10, 0.12, 0.16, 1)
STAR_C = (1.0, 0.82, 0.40, 1)

Window.clearcolor = (*BG, 1)

# --- Levels (ASCII grids; rows top->bottom, all rows same width) ------------
# '#' wall   '.' empty   'S' start   'G' goal
# 'x' static mine   'm' moving mine   '*' orb   'O' spinner
LEVELS = [
    {"name": "First Steps", "lives": 5, "grid": [
        ".........",
        "...S.....",
        ".........",
        "....x....",
        ".........",
        "...*..x..",
        ".........",
        "......x..",
        ".........",
        ".....G...",
        ".........",
    ]},
    {"name": "Detour", "lives": 5, "grid": [
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
    {"name": "Patrol", "lives": 5, "grid": [
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
    {"name": "The Maze", "lives": 6, "grid": [
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
    {"name": "Spikes & Halls", "lives": 6, "grid": [
        "#########",
        "#S....x.#",
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
    {"name": "Gauntlet", "lives": 7, "grid": [
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
]

PASSABLE = set(".SGxm*O")    # grid chars the bob may occupy (everything but '#')


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def solvable(grid):
    """BFS from S to G through non-wall cells (4-connected). Used at load+test."""
    rows, cols = len(grid), len(grid[0])
    start = goal = None
    for i, row in enumerate(grid):
        for j, ch in enumerate(row):
            if ch == "S":
                start = (i, j)
            elif ch == "G":
                goal = (i, j)
    if not start or not goal:
        return False
    seen = {start}
    q = deque([start])
    while q:
        i, j = q.popleft()
        if (i, j) == goal:
            return True
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < rows and 0 <= nj < cols and (ni, nj) not in seen \
                    and grid[ni][nj] in PASSABLE:
                seen.add((ni, nj))
                q.append((ni, nj))
    return False


class MovingMine:
    """Patrols along one axis, reversing at walls / bounds."""
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

        self.state = MENU
        self.level_idx = 0
        self.cur = None            # loaded level (cell data)
        self.held = set()
        self.steering = False
        self._steer_touch = None
        self.target = (0, 0)
        self.accum = 0.0
        self.shake = 0.0
        self._tex_cache = {}
        self._buttons = []
        self._ready = False

        Window.bind(on_key_down=self._key_down, on_key_up=self._key_up)
        Clock.schedule_interval(self.tick, 0)
        self.bind(size=lambda *a: self._on_size())

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
        if w > 1 and h > 1:
            self._ready = True

    def _layout_level(self):
        rows, cols = self.cur["rows"], self.cur["cols"]
        x0, y0 = self.margin, self.margin
        pw, ph = self.width - 2 * self.margin, self.height - 2 * self.margin
        # reserve a strip at the top for the HUD
        ph -= self.scale * 0.06
        cell = min(pw / cols, ph / cols if False else ph / rows)
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
        start = goal = None
        for i, row in enumerate(grid):
            for j, ch in enumerate(row):
                if ch == "#":
                    walls.add((i, j))
                elif ch == "S":
                    start = (i, j)
                elif ch == "G":
                    goal = (i, j)
                elif ch == "x":
                    statics.append((i, j))
                elif ch == "m":
                    movers.append((i, j))
                elif ch == "*":
                    orbs.append((i, j))
                elif ch == "O":
                    spinners.append((i, j))
        self.cur = {"name": spec["name"], "lives": spec["lives"], "grid": grid,
                    "rows": rows, "cols": cols, "walls": walls, "start": start,
                    "goal": goal, "statics": statics, "movers": movers,
                    "orbs": orbs, "spinners": spinners}
        self.level_idx = idx
        self._layout_level()

    def start_level(self, idx):
        self.load_level(idx)
        c = self.cur
        sx, sy = self.cell_center(*c["start"])
        self.ax, self.ay = sx, sy
        self.avx = self.avy = 0.0
        self.bx, self.by = sx, sy          # bob starts on the anchor (safe in-cell)
        self.bvx = self.bvy = 0.0
        self.trail = []
        self.lives = c["lives"]
        self.iframes = 0
        self.flash = 0
        self.steps = 0
        self.collected = 0
        self.steering = False
        self._steer_touch = None

        # runtime hazards
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
        elif action == "menu":
            self.state = MENU
        elif action == "select":
            self.state = SELECT
        elif action == "resume":
            self.state = PLAYING
        elif action == "pause":
            self.state = PAUSED
        elif action == "retry":
            self.start_level(self.level_idx)
        elif action == "next":
            nxt = self.level_idx + 1
            if nxt < len(LEVELS):
                self.start_level(nxt)
            else:
                self.state = SELECT
        elif action.startswith("level:"):
            idx = int(action.split(":")[1])
            if idx < self.progress["unlocked"]:
                self.start_level(idx)

    def _key_down(self, win, key, scancode, codepoint, modifier):
        if key == 112 and self.state in (PLAYING, PAUSED):       # P
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
                self.physics_step()
                self.accum -= STEP
                n += 1
                if self.state != PLAYING:
                    break
        self.render()

    def physics_step(self):
        self.steps += 1
        x0 = self.gx0
        y0 = self.gy0
        x1 = self.gx0 + self.cell * self.cur["cols"]
        y1 = self.gy0 + self.cell * self.cur["rows"]

        # Anchor: keyboard + touch-seek.
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

        # Bob: damped spring toward anchor (velocity capped to avoid tunneling).
        self.bvx = (self.bvx + (self.ax - self.bx) * SPRING_K) * SPRING_DAMP
        self.bvy = (self.bvy + (self.ay - self.by) * SPRING_K) * SPRING_DAMP
        sp = math.hypot(self.bvx, self.bvy)
        if sp > self.bob_vmax:
            self.bvx *= self.bob_vmax / sp
            self.bvy *= self.bob_vmax / sp
        self.bx += self.bvx
        self.by += self.bvy

        # Outer bounds: harmless bounce (keeps the bob on screen).
        rb = self.r_bob
        if self.bx < x0 + rb:
            self.bx, self.bvx = x0 + rb, abs(self.bvx) * 0.5
        elif self.bx > x1 - rb:
            self.bx, self.bvx = x1 - rb, -abs(self.bvx) * 0.5
        if self.by < y0 + rb:
            self.by, self.bvy = y0 + rb, abs(self.bvy) * 0.5
        elif self.by > y1 - rb:
            self.by, self.bvy = y1 - rb, -abs(self.bvy) * 0.5

        # Walls: solid + damaging (check the bob's cell neighbourhood only).
        ci, cj = self.pixel_cell(self.bx, self.by)
        touched_wall = False
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if (ci + di, cj + dj) in self.cur["walls"]:
                    if self._collide_rect(self.cell_rect(ci + di, cj + dj)):
                        touched_wall = True
        if touched_wall:
            self._hurt()

        self.trail.append((self.bx, self.by))
        if len(self.trail) > TRAIL_LEN:
            self.trail.pop(0)

        # Static mines.
        for (i, j) in self.cur["statics"]:
            mx, my = self.cell_center(i, j)
            if math.hypot(mx - self.bx, my - self.by) < rb + self.r_mine:
                self._hurt(mx, my)

        # Moving mines.
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

        # Spinners.
        for s in self.spinners:
            s["ang"] += s["spd"]
            ex = s["cx"] + math.cos(s["ang"]) * s["len"]
            ey = s["cy"] + math.sin(s["ang"]) * s["len"]
            if self._point_seg(self.bx, self.by, s["cx"], s["cy"], ex, ey) \
                    < rb + self.cell * 0.10:
                self._hurt(s["cx"], s["cy"])

        # Orbs.
        for o in self.orbs:
            if not o["got"] and math.hypot(o["x"] - self.bx, o["y"] - self.by) < rb + self.r_orb:
                o["got"] = True
                self.collected += 1
                self.sounds.play("pickup", volume=0.7)

        # Goal.
        if math.hypot(self.goal_xy[0] - self.bx, self.goal_xy[1] - self.by) < self.r_goal:
            self._level_clear()

        if self.iframes > 0:
            self.iframes -= 1
        if self.flash > 0:
            self.flash -= 1
        if self.shake > 0:
            self.shake *= 0.85
            if self.shake < 0.5:
                self.shake = 0

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
            # reflect velocity along the contact normal
            nxn, nyn = dx / d, dy / d
            dot = self.bvx * nxn + self.bvy * nyn
            self.bvx -= 1.5 * dot * nxn
            self.bvy -= 1.5 * dot * nyn
        else:
            self.by += rb   # degenerate: nudge upward
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
            self.bvx += math.cos(ang) * 6 * self.sf
            self.bvy += math.sin(ang) * 6 * self.sf
        if self.lives <= 0:
            self.state = FAILED

    def _level_clear(self):
        self.state = CLEAR
        total = len(self.orbs)
        stars = 1
        if self.lives >= self.cur["lives"]:
            stars = 3
        elif self.lives >= max(2, self.cur["lives"] - 2):
            stars = 2
        if total and self.collected >= total and stars < 3:
            stars += 1
        stars = min(3, stars)
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
    def _btn(self, x, y, w, h, label, action, enabled=True, fs=None, locked=False):
        self._buttons.append({"x": x, "y": y, "w": w, "h": h, "label": label,
                              "action": action, "enabled": enabled,
                              "fs": fs or self.scale * 0.040, "locked": locked})

    def _draw_buttons(self):
        for b in self._buttons:
            fill = BTN_LOCK if b["locked"] else BTN_C
            Color(*fill)
            Rectangle(pos=(b["x"], b["y"]), size=(b["w"], b["h"]))
            Color(*(DIM_C if b["locked"] else BTN_EDGE))
            Line(rectangle=(b["x"], b["y"], b["w"], b["h"]), width=1.4)
            if b["label"]:
                self._text(b["label"], b["x"] + b["w"] / 2, b["y"] + b["h"] / 2,
                           b["fs"], DIM_C if b["locked"] else TEXT_C, bold=True)

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

            if self.state in (PLAYING, PAUSED, CLEAR, FAILED) and self.cur:
                self._draw_level()
            if self.state == MENU:
                self._draw_menu()
            elif self.state == SELECT:
                self._draw_select()
            elif self.state == PLAYING:
                self._draw_play_hud()
            elif self.state == PAUSED:
                self._overlay("PAUSED", None)
                self._stack_buttons(["Resume", "Retry", "Levels"],
                                    ["resume", "retry", "select"])
            elif self.state == CLEAR:
                self._overlay("LEVEL CLEAR", None, stars=getattr(self, "last_stars", 0))
                has_next = self.level_idx + 1 < len(LEVELS)
                labels = (["Next", "Retry", "Levels"] if has_next
                          else ["Retry", "Levels"])
                acts = (["next", "retry", "select"] if has_next
                        else ["retry", "select"])
                self._stack_buttons(labels, acts)
            elif self.state == FAILED:
                self._overlay("FAILED", "The bob couldn't make it.")
                self._stack_buttons(["Retry", "Levels"], ["retry", "select"])
            self._draw_buttons()

    # ----- world
    def _draw_level(self):
        ox = oy = 0.0
        if self.shake:
            ox = random.uniform(-self.shake, self.shake)
            oy = random.uniform(-self.shake, self.shake)
        s, cell = self.scale, self.cell

        # walls
        for (i, j) in self.cur["walls"]:
            rx, ry, c, _ = self.cell_rect(i, j)
            Color(*WALL_C)
            Rectangle(pos=(rx + ox, ry + oy), size=(c, c))
            Color(*WALL_EDGE)
            Line(rectangle=(rx + ox, ry + oy, c, c), width=1.2)

        # goal
        gx, gy = self.goal_xy
        pulse = 1 + 0.12 * math.sin(self.steps * 0.12)
        Color(*GOAL_DIM)
        self._disc(gx + ox, gy + oy, self.r_goal * 1.15 * pulse)
        Color(*GOAL_C)
        Line(circle=(gx + ox, gy + oy, self.r_goal * pulse), width=2.2)
        self._disc(gx + ox, gy + oy, self.r_goal * 0.30)

        # orbs
        for o in self.orbs:
            if o["got"]:
                continue
            Color(*ORB_DIM)
            self._disc(o["x"] + ox, o["y"] + oy, self.r_orb + s * 0.005)
            Color(*ORB_C)
            self._disc(o["x"] + ox, o["y"] + oy, self.r_orb)

        # static mines
        for (i, j) in self.cur["statics"]:
            mx, my = self.cell_center(i, j)
            self._mine(mx + ox, my + oy)

        # moving mines
        for m in self.mmines:
            self._mine(m.x + ox, m.y + oy)

        # spinners
        for sp in self.spinners:
            ex = sp["cx"] + math.cos(sp["ang"]) * sp["len"]
            ey = sp["cy"] + math.sin(sp["ang"]) * sp["len"]
            Color(*SPIN_C)
            Line(points=[sp["cx"] + ox, sp["cy"] + oy, ex + ox, ey + oy],
                 width=max(2, cell * 0.10))
            self._disc(ex + ox, ey + oy, cell * 0.12)
            Color(*MINE_CORE)
            self._disc(sp["cx"] + ox, sp["cy"] + oy, cell * 0.14)

        # tether + trail + bob + anchor
        Color(*TETHER_C)
        Line(points=[self.ax + ox, self.ay + oy, self.bx + ox, self.by + oy],
             width=max(1.2, s * 0.004))
        n = len(self.trail)
        for k, (tx, ty) in enumerate(self.trail):
            Color(*BOB_GLOW)
            self._disc(tx + ox, ty + oy, self.r_bob * (0.25 + 0.5 * (k / max(n, 1))))
        blink = self.iframes > 0 and (self.iframes // 5) % 2 == 0
        Color(*BOB_GLOW)
        self._disc(self.bx + ox, self.by + oy, self.r_bob + s * 0.008)
        Color(*(BOB_HIT if blink else BOB_C))
        self._disc(self.bx + ox, self.by + oy, self.r_bob)
        if self.flash > 0:
            Color(*MINE_C)
            Line(circle=(self.bx + ox, self.by + oy, self.r_bob + s * 0.012 + self.flash),
                 width=2)
        Color(*ANCHOR_C)
        Line(circle=(self.ax + ox, self.ay + oy, self.r_anchor), width=max(2, s * 0.006))

    def _disc(self, x, y, r):
        Ellipse(pos=(x - r, y - r), size=(2 * r, 2 * r))

    def _mine(self, x, y):
        Color(*MINE_CORE)
        self._disc(x, y, self.r_mine + self.scale * 0.004)
        Color(*MINE_C)
        self._disc(x, y, self.r_mine)
        Color(*MINE_CORE)
        self._disc(x, y, self.r_mine * 0.42)

    # ----- HUD / menus
    def _draw_play_hud(self):
        s, m = self.scale, self.margin
        self._text(self.cur["name"], self.width / 2, self.height - m - s * 0.02,
                   s * 0.034, TEXT_C, bold=True)
        # lives as bob-pips, top-left
        for i in range(self.lives):
            Color(*BOB_C)
            self._disc(m * 1.5 + i * s * 0.05, self.height - m - s * 0.03, s * 0.016)
        if self.orbs:
            self._text(f"orbs {self.collected}/{len(self.orbs)}", m * 1.3,
                       self.height - m - s * 0.07, s * 0.026, ORB_C, anchor="tl")
        # pause button (top-right)
        bs = s * 0.075
        x = self.width - m - bs
        y = self.height - m - bs
        self._btn(x, y, bs, bs, "II", "pause", fs=s * 0.035)

    def _draw_menu(self):
        w, h, s = self.width, self.height, self.scale
        self._text("TETHER", w / 2, h * 0.66, s * 0.13, TITLE_C, bold=True)
        self._text("Whip the jiggly bob to the exit.\nMind the walls.",
                   w / 2, h * 0.54, s * 0.032, TEXT_C, mw=w * 0.8)
        bw, bh = w * 0.5, s * 0.10
        self._btn(w / 2 - bw / 2, h * 0.36, bw, bh, "PLAY", "play", fs=s * 0.05)
        done = sum(self.progress["stars"].values())
        self._text(f"{self.progress['unlocked']}/{len(LEVELS)} levels  ·  "
                   f"{done}/{len(LEVELS) * 3} stars",
                   w / 2, h * 0.27, s * 0.026, DIM_C)

    def _draw_select(self):
        w, h, s = self.width, self.height, self.scale
        self._text("SELECT LEVEL", w / 2, h - self.margin - s * 0.06,
                   s * 0.055, TITLE_C, bold=True)
        cols = 3
        rows = (len(LEVELS) + cols - 1) // cols
        gap = w * 0.04
        bw = (w * 0.84 - gap * (cols - 1)) / cols
        bh = bw * 0.92
        x0 = w * 0.08
        ytop = h * 0.74
        for idx in range(len(LEVELS)):
            r, c = divmod(idx, cols)
            x = x0 + c * (bw + gap)
            y = ytop - r * (bh + gap) - bh
            unlocked = idx < self.progress["unlocked"]
            self._btn(x, y, bw, bh, "", f"level:{idx}", enabled=unlocked,
                      locked=not unlocked)
            cx = x + bw / 2
            if unlocked:
                self._text(str(idx + 1), cx, y + bh * 0.60, s * 0.06, TEXT_C, bold=True)
                self._stars(cx, y + bh * 0.26, self.progress["stars"].get(idx, 0),
                            s * 0.018)
            else:
                self._text("⚿", cx, y + bh * 0.5, s * 0.05, DIM_C)  # lock-ish glyph
        bw2 = w * 0.4
        self._btn(w / 2 - bw2 / 2, h * 0.08, bw2, s * 0.09, "Menu", "menu",
                  fs=s * 0.04)

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
            self._stars(w / 2, h * 0.56, stars, s * 0.03)
        if sub:
            self._text(sub, w / 2, h * 0.50, s * 0.032, TEXT_C, mw=w * 0.8)

    def _stack_buttons(self, labels, actions):
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
    # Validate every level is solvable before we ever show it.
    for _lv in LEVELS:
        assert solvable(_lv["grid"]), f"Level not solvable: {_lv['name']}"
    if platform not in ("android", "ios"):
        Window.size = (414, 736)
    TetherApp().run()
