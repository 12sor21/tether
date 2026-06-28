"""
TETHER  —  a one-thumb arcade game.

You don't control the thing that scores or dies. You drag the ANCHOR (the ring);
a heavy BOB hangs off it on a springy tether. The bob collects orbs and dies to
mines, but it swings, lags and overshoots. You score by *whipping* it.

Mobile build (Kivy). Touch-only: no keyboard is required (keys are an optional
desktop convenience). Package-able to an Android APK/AAB with Buildozer.

Robustness: EVERYTHING is drawn immediate-mode onto a single canvas that is
cleared every frame -- the world, the HUD, and all overlay text (menu / paused /
game over). There are no persistent text widgets, so a screen physically cannot
"stick" after a state change: if the state isn't GAMEOVER, the words are simply
never drawn that frame.
"""

import math
import random

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, Rectangle
from kivy.storage.jsonstore import JsonStore
from kivy.uix.widget import Widget
from kivy.utils import platform

# --- States -----------------------------------------------------------------
MENU, PLAYING, PAUSED, GAMEOVER = "menu", "playing", "paused", "gameover"

# --- Fixed-timestep physics -------------------------------------------------
STEP = 1.0 / 60.0
MAX_STEPS = 5
REF = 560.0                # reference short-edge; all sizes scale off this

# --- Tuning (dimensionless ratios are screen-independent) -------------------
ANCHOR_ACCEL = 0.9
ANCHOR_FRICTION = 0.88
ANCHOR_MAX = 9.0
SPRING_K = 0.045
SPRING_DAMP = 0.94
TRAIL_LEN = 16

ORB_MAX = 5
ORB_SPAWN_EVERY = 42
ORB_LIFETIME = 320
MINE_START = 2
MINE_MAX = 9
MINE_RAMP_EVERY = 600
COMBO_WINDOW = 150
LIVES = 3
IFRAMES = 70

R_ANCHOR = 0.016
R_BOB = 0.030
R_ORB = 0.022
R_MINE = 0.026
MINE_SPD_MIN, MINE_SPD_MAX = 0.6, 1.6
MARGIN_F = 0.025

# --- Palette ----------------------------------------------------------------
BG = (0.043, 0.055, 0.078)
GRIDLINE = (0.078, 0.098, 0.145)
ANCHOR_C = (0.60, 0.655, 0.74)
TETHER_C = (0.227, 0.29, 0.40)
BOB_C = (1.0, 0.82, 0.40)
BOB_GLOW = (0.48, 0.365, 0.07)
BOB_HIT = (1.0, 0.54, 0.54)
ORB_C = (0.204, 0.878, 0.878)
ORB_DIM = (0.11, 0.43, 0.43)
MINE_C = (1.0, 0.337, 0.439)
MINE_CORE = (0.478, 0.122, 0.18)
TITLE_C = (1.0, 0.82, 0.40, 1)
TEXT_C = (0.9, 0.9, 0.9, 1)
DIM_C = (0.66, 0.66, 0.66, 1)
COMBO_TXT = (0.204, 0.878, 0.878, 1)

Window.clearcolor = (*BG, 1)


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


class Orb:
    __slots__ = ("x", "y", "life")

    def __init__(self, x, y):
        self.x, self.y, self.life = x, y, ORB_LIFETIME


class Mine:
    __slots__ = ("x", "y", "vx", "vy")

    def __init__(self, x, y, spd_scale):
        self.x, self.y = x, y
        ang = random.uniform(0, math.tau)
        spd = random.uniform(MINE_SPD_MIN, MINE_SPD_MAX) * spd_scale
        self.vx, self.vy = math.cos(ang) * spd, math.sin(ang) * spd


class SoundBank:
    """Loads sfx from data/ (.wav or .ogg); silently no-ops if absent."""

    def __init__(self):
        self.sounds = {}
        try:
            from kivy.core.audio import SoundLoader
            from os.path import dirname, join, exists
            base = join(dirname(__file__), "data")
            for name in ("pickup", "hit", "start"):
                for ext in (".ogg", ".wav"):
                    path = join(base, name + ext)
                    if exists(path):
                        snd = SoundLoader.load(path)
                        if snd:
                            self.sounds[name] = snd
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
        self.high = store.get("hs")["v"] if store.exists("hs") else 0

        self.state = MENU
        self.held = set()
        self.steering = False
        self._steer_touch = None
        self.target = (0, 0)
        self.accum = 0.0
        self.shake = 0.0
        self._tex_cache = {}
        self._init_world_done = False

        Window.bind(on_key_down=self._key_down, on_key_up=self._key_up)
        Clock.schedule_interval(self.tick, 0)
        self.bind(size=lambda *a: self._recompute_scale())

    # --- Geometry -----------------------------------------------------------
    def _recompute_scale(self):
        w, h = self.size
        self.scale = max(1.0, min(w, h))
        self.sf = self.scale / REF
        self.margin = self.scale * MARGIN_F
        self.r_anchor = self.scale * R_ANCHOR
        self.r_bob = self.scale * R_BOB
        self.r_orb = self.scale * R_ORB
        self.r_mine = self.scale * R_MINE
        self.accel = ANCHOR_ACCEL * self.sf
        self.vmax = ANCHOR_MAX * self.sf
        self._tex_cache.clear()   # font sizes are scale-dependent
        if not self._init_world_done and w > 1 and h > 1:
            self.reset_world()
            self._init_world_done = True

    def bounds(self):
        return (self.margin, self.margin, self.width - self.margin, self.height - self.margin)

    # --- World setup --------------------------------------------------------
    def reset_world(self):
        cx, cy = self.width / 2, self.height / 2
        self.ax, self.ay = cx, cy
        self.avx = self.avy = 0.0
        self.bx, self.by = cx, cy - self.scale * 0.12
        self.bvx = self.bvy = 0.0
        self.trail = []
        self.orbs = []
        self.mines = [self._new_mine() for _ in range(MINE_START)]
        self.score = 0
        self.combo = 1
        self.combo_timer = 0
        self.lives = LIVES
        self.iframes = 0
        self.steps = 0
        self.orb_timer = 0
        self.flash = 0

    def start(self):
        self.reset_world()
        self.state = PLAYING
        self.steering = False
        self._steer_touch = None
        self.sounds.play("start")

    def _new_mine(self):
        x0, y0, x1, y1 = self.bounds()
        for _ in range(40):
            x = random.uniform(x0 + self.r_mine, x1 - self.r_mine)
            y = random.uniform(y0 + self.r_mine, y1 - self.r_mine)
            if math.hypot(x - self.bx, y - self.by) > self.scale * 0.23:
                return Mine(x, y, self.sf)
        return Mine(x, y, self.sf)

    def _spawn_orb(self):
        x0, y0, x1, y1 = self.bounds()
        for _ in range(30):
            x = random.uniform(x0 + self.r_orb, x1 - self.r_orb)
            y = random.uniform(y0 + self.r_orb, y1 - self.r_orb)
            if all(math.hypot(x - m.x, y - m.y) > self.scale * 0.11 for m in self.mines):
                self.orbs.append(Orb(x, y))
                return

    # --- Input (touch-first; keyboard optional on desktop) ------------------
    def _pause_btn_rect(self):
        s = self.scale * 0.08
        pad = self.scale * 0.03
        return (self.width - s - pad, self.height - s - pad, s, s)

    @staticmethod
    def _in_rect(px, py, rect):
        rx, ry, rw, rh = rect
        return rx <= px <= rx + rw and ry <= py <= ry + rh

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        px, py = touch.pos
        if self.state in (MENU, GAMEOVER):
            self.start()
            return True
        if self.state == PAUSED:
            self.state = PLAYING
            return True
        if self.state == PLAYING:
            if self._in_rect(px, py, self._pause_btn_rect()):
                self.state = PAUSED
                return True
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

    def _key_down(self, win, key, scancode, codepoint, modifier):
        if key in (32, 13):
            if self.state in (MENU, GAMEOVER):
                self.start()
            elif self.state == PAUSED:
                self.state = PLAYING
            return
        if key == 112:
            if self.state == PLAYING:
                self.state = PAUSED
            elif self.state == PAUSED:
                self.state = PLAYING
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
        if not hasattr(self, "scale"):
            self._recompute_scale()
            if not self._init_world_done:
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
        x0, y0, x1, y1 = self.bounds()

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

        self.bvx = (self.bvx + (self.ax - self.bx) * SPRING_K) * SPRING_DAMP
        self.bvy = (self.bvy + (self.ay - self.by) * SPRING_K) * SPRING_DAMP
        self.bx += self.bvx
        self.by += self.bvy
        rb = self.r_bob
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
        if self.orb_timer >= ORB_SPAWN_EVERY and len(self.orbs) < ORB_MAX:
            self.orb_timer = 0
            self._spawn_orb()

        if self.steps % MINE_RAMP_EVERY == 0 and len(self.mines) < MINE_MAX:
            self.mines.append(self._new_mine())

        for o in self.orbs:
            o.life -= 1
        self.orbs = [o for o in self.orbs if o.life > 0]

        if self.combo_timer > 0:
            self.combo_timer -= 1
            if self.combo_timer == 0:
                self.combo = 1

        kept = []
        for o in self.orbs:
            if math.hypot(o.x - self.bx, o.y - self.by) < rb + self.r_orb:
                self.combo = min(self.combo + 1, 9) if self.combo_timer > 0 else 2
                self.combo_timer = COMBO_WINDOW
                self.score += 10 * self.combo
                self.flash = 6
                self.sounds.play("pickup", volume=0.7)
            else:
                kept.append(o)
        self.orbs = kept

        for m in self.mines:
            m.x += m.vx
            m.y += m.vy
            if m.x < x0 + self.r_mine or m.x > x1 - self.r_mine:
                m.vx *= -1
                m.x = clamp(m.x, x0 + self.r_mine, x1 - self.r_mine)
            if m.y < y0 + self.r_mine or m.y > y1 - self.r_mine:
                m.vy *= -1
                m.y = clamp(m.y, y0 + self.r_mine, y1 - self.r_mine)

        if self.iframes > 0:
            self.iframes -= 1
        else:
            for m in self.mines:
                if math.hypot(m.x - self.bx, m.y - self.by) < rb + self.r_mine:
                    self.lives -= 1
                    self.iframes = IFRAMES
                    self.combo = 1
                    self.combo_timer = 0
                    self.shake = self.scale * 0.02
                    self.sounds.play("hit")
                    ang = math.atan2(self.by - m.y, self.bx - m.x)
                    self.bvx += math.cos(ang) * 6 * self.sf
                    self.bvy += math.sin(ang) * 6 * self.sf
                    if self.lives <= 0:
                        self.game_over()
                    break

        if self.flash > 0:
            self.flash -= 1
        if self.shake > 0:
            self.shake *= 0.85
            if self.shake < 0.5:
                self.shake = 0

    def game_over(self):
        self.state = GAMEOVER
        self.steering = False
        self._steer_touch = None
        if self.score > self.high:
            self.high = self.score
            try:
                self.store.put("hs", v=self.high)
            except Exception:
                pass

    # --- Overlay contract (single source of truth, used by render + tests) --
    def overlay(self):
        """(title, subtitle) for the current state, or (None, None) if none."""
        if self.state == MENU:
            return ("TETHER",
                    "Drag the ring. The heavy bob swings on the tether -\n"
                    "whip it through the cyan orbs, avoid the red mines.\n\n"
                    "Tap to start")
        if self.state == PAUSED:
            return ("PAUSED", "Tap to resume")
        if self.state == GAMEOVER:
            return ("GAME OVER",
                    f"Score {self.score}    Best {self.high}\n\nTap to play again")
        return (None, None)

    # --- Canvas text (cached textures; tinted via Color) --------------------
    def _tex(self, text, font_size, bold=False, max_width=None):
        key = (text, int(font_size), bold, int(max_width or 0))
        tex = self._tex_cache.get(key)
        if tex is None:
            kw = dict(text=text, font_size=int(font_size), bold=bold)
            if max_width:
                kw["text_size"] = (max_width, None)
                kw["halign"] = "center"
            cl = CoreLabel(**kw)
            cl.refresh()
            tex = cl.texture
            if len(self._tex_cache) > 400:
                self._tex_cache.clear()
            self._tex_cache[key] = tex
        return tex

    def _text(self, text, cx, cy, font_size, color, bold=False, max_width=None,
              anchor="center"):
        tex = self._tex(text, font_size, bold, max_width)
        if not tex:
            return
        w, h = tex.size
        if anchor == "center":
            pos = (cx - w / 2, cy - h / 2)
        elif anchor == "tl":      # cx,cy is top-left
            pos = (cx, cy - h)
        else:                     # tr: cx,cy is top-right
            pos = (cx - w, cy - h)
        Color(*color)
        Rectangle(texture=tex, pos=pos, size=(w, h))

    # --- Rendering (full redraw every frame -> nothing can stick) -----------
    def _disc(self, x, y, r, color):
        Color(*color)
        Ellipse(pos=(x - r, y - r), size=(2 * r, 2 * r))

    def _ring(self, x, y, r, color, width):
        Color(*color)
        Line(circle=(x, y, r), width=width)

    def render(self):
        self.canvas.clear()
        if not self._init_world_done:
            return
        ox = oy = 0.0
        if self.shake:
            ox = random.uniform(-self.shake, self.shake)
            oy = random.uniform(-self.shake, self.shake)
        w, h = self.width, self.height
        s = self.scale
        with self.canvas:
            Color(*BG)
            Rectangle(pos=(0, 0), size=(w, h))

            Color(*GRIDLINE)
            grid = s * 0.07
            gx = self.margin
            while gx < w:
                Line(points=[gx + ox, 0, gx + ox, h], width=1)
                gx += grid
            gy = self.margin
            while gy < h:
                Line(points=[0, gy + oy, w, gy + oy], width=1)
                gy += grid
            x0, y0, x1, y1 = self.bounds()
            Line(rectangle=(x0 + ox, y0 + oy, x1 - x0, y1 - y0), width=1.4)

            if self.state in (PLAYING, PAUSED, GAMEOVER):
                self._draw_world(ox, oy)
                self._draw_hud()

            title, sub = self.overlay()
            if title is not None:
                # dim scrim + text
                Color(*BG, 0.62)
                Rectangle(pos=(0, 0), size=(w, h))
                self._text(title, w / 2, h * 0.60, s * 0.11, TITLE_C, bold=True)
                self._text(sub, w / 2, h * 0.42, s * 0.034, TEXT_C,
                           max_width=w * 0.86)

    def _draw_world(self, ox, oy):
        s = self.scale
        for o in self.orbs:
            frac = o.life / ORB_LIFETIME
            pulse = 1 + 0.18 * math.sin(self.steps * 0.2)
            r = self.r_orb * (0.55 + 0.45 * frac) * pulse
            col = ORB_C if frac > 0.35 else ORB_DIM
            self._disc(o.x + ox, o.y + oy, r + s * 0.006, ORB_DIM)
            self._disc(o.x + ox, o.y + oy, r, col)

        for m in self.mines:
            self._disc(m.x + ox, m.y + oy, self.r_mine + s * 0.004, MINE_CORE)
            self._disc(m.x + ox, m.y + oy, self.r_mine, MINE_C)
            self._disc(m.x + ox, m.y + oy, self.r_mine * 0.45, MINE_CORE)

        Color(*TETHER_C)
        Line(points=[self.ax + ox, self.ay + oy, self.bx + ox, self.by + oy],
             width=max(1.2, s * 0.004))

        n = len(self.trail)
        for i, (tx, ty) in enumerate(self.trail):
            rr = self.r_bob * (0.25 + 0.5 * (i / max(n, 1)))
            self._disc(tx + ox, ty + oy, rr, BOB_GLOW)

        blink = self.iframes > 0 and (self.iframes // 5) % 2 == 0
        self._disc(self.bx + ox, self.by + oy, self.r_bob + s * 0.008, BOB_GLOW)
        self._disc(self.bx + ox, self.by + oy, self.r_bob, BOB_HIT if blink else BOB_C)
        if self.flash > 0:
            self._ring(self.bx + ox, self.by + oy,
                       self.r_bob + s * 0.012 + self.flash, ORB_C, 2)

        self._ring(self.ax + ox, self.ay + oy, self.r_anchor, ANCHOR_C, max(2, s * 0.006))

    def _draw_hud(self):
        s = self.scale
        m = self.margin
        # Score + best (top-left).
        self._text(f"{self.score}", m * 1.3, self.height - m, s * 0.05, TEXT_C,
                   bold=True, anchor="tl")
        self._text(f"best {self.high}", m * 1.3, self.height - m - s * 0.06,
                   s * 0.03, DIM_C, anchor="tl")
        # Combo (top-centre).
        if self.combo > 1:
            self._text(f"x{self.combo}", self.width / 2, self.height - m - s * 0.03,
                       s * 0.05, COMBO_TXT, bold=True)
        # Lives pips + pause button (top-right), only while actually playing.
        if self.state == PLAYING:
            rx, ry, rw, rh = self._pause_btn_rect()
            Color(*ANCHOR_C)
            bw = rw * 0.16
            Rectangle(pos=(rx + rw * 0.32, ry + rh * 0.28), size=(bw, rh * 0.44))
            Rectangle(pos=(rx + rw * 0.54, ry + rh * 0.28), size=(bw, rh * 0.44))
            pip = s * 0.018
            for i in range(self.lives):
                self._disc(rx - pip - i * pip * 2.6, ry + rh / 2, pip, BOB_C)


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
    if platform not in ("android", "ios"):
        Window.size = (414, 736)   # portrait phone window for desktop testing
    TetherApp().run()
