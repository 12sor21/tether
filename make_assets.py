"""
Generates the app icon (512x512) and presplash (1024x1024) for Tether,
drawn to match the in-game art so the store listing is consistent.

Run once:  python make_assets.py     (requires Pillow)
"""

import math
from os.path import dirname, join

from PIL import Image, ImageDraw

BG = (11, 14, 20)
GRID = (20, 25, 37)
TETHER = (58, 74, 102)
ANCHOR = (153, 167, 189)
BOB = (255, 209, 102)
BOB_GLOW = (122, 93, 18)
ORB = (52, 224, 224)
MINE = (255, 86, 112)

HERE = join(dirname(__file__), "data")


def disc(d, cx, cy, r, color):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def ring(d, cx, cy, r, color, w):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)


def render(size):
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    s = size / 512.0

    # faint grid
    step = int(48 * s)
    for x in range(0, size, step):
        d.line([(x, 0), (x, size)], fill=GRID, width=1)
    for y in range(0, size, step):
        d.line([(0, y), (size, y)], fill=GRID, width=1)

    # an orb and a mine for context
    disc(d, 0.78 * size, 0.30 * size, 26 * s, ORB)
    disc(d, 0.24 * size, 0.74 * size, 30 * s, MINE)
    disc(d, 0.24 * size, 0.74 * size, 13 * s, (122, 31, 46))

    # anchor (upper-left) tethered to bob (center), mid whip
    ax, ay = 0.34 * size, 0.34 * size
    bx, by = 0.56 * size, 0.60 * size
    d.line([(ax, ay), (bx, by)], fill=TETHER, width=int(7 * s))

    # bob trail
    for i in range(8):
        t = i / 8.0
        tx = ax + (bx - ax) * (0.4 + 0.6 * t)
        ty = ay + (by - ay) * (0.4 + 0.6 * t)
        disc(d, tx, ty, (10 + 18 * t) * s, BOB_GLOW)

    disc(d, bx, by, 58 * s, BOB_GLOW)
    disc(d, bx, by, 44 * s, BOB)
    ring(d, ax, ay, 26 * s, ANCHOR, int(9 * s))

    return img


def main():
    render(512).save(join(HERE, "icon.png"))
    render(1024).save(join(HERE, "presplash.png"))
    print("wrote data/icon.png (512) and data/presplash.png (1024)")


if __name__ == "__main__":
    main()
