"""
Generates the three sound effects for Tether as 16-bit mono WAV files,
using only the standard library (math, struct, wave). No numpy required.

    pickup.wav  - bright two-note blip when the bob eats an orb
    hit.wav     - low noise-thump when the bob hits a mine
    start.wav   - short rising sweep on (re)start

Run once:  python make_sounds.py
The game (SoundBank in main.py) loads these automatically from data/.
"""

import math
import random
import struct
import wave
from os.path import dirname, join

RATE = 22050
HERE = join(dirname(__file__), "data")


def _save(name, samples):
    path = join(HERE, name)
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frames = bytearray()
        for s in samples:
            v = int(clamp(s, -1.0, 1.0) * 32767)
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    return path


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def adsr(i, n, attack=0.005, release=0.6):
    """Simple attack/exponential-release envelope, 0..1."""
    t = i / n
    a = attack
    if t < a:
        return t / a
    return math.exp(-(t - a) / release * 5.0)


def sine(freq, i):
    return math.sin(2 * math.pi * freq * i / RATE)


def pickup():
    dur = int(RATE * 0.16)
    out = []
    f1, f2 = 880.0, 1318.5   # A5 -> E6
    for i in range(dur):
        freq = f1 if i < dur * 0.45 else f2
        # sine + a touch of its octave for sparkle
        s = 0.7 * sine(freq, i) + 0.2 * sine(freq * 2, i)
        out.append(s * adsr(i, dur, 0.004, 0.5) * 0.6)
    return out


def hit():
    dur = int(RATE * 0.28)
    out = []
    for i in range(dur):
        t = i / dur
        freq = 180.0 * (1.0 - 0.6 * t)          # descending rumble
        noise = (random.uniform(-1, 1)) * math.exp(-t * 9)  # initial crack
        s = 0.7 * sine(freq, i) + 0.5 * noise
        out.append(s * adsr(i, dur, 0.002, 0.5) * 0.8)
    return out


def start():
    dur = int(RATE * 0.22)
    out = []
    for i in range(dur):
        t = i / dur
        freq = 320.0 + 520.0 * t                # rising sweep
        s = 0.6 * sine(freq, i) + 0.15 * sine(freq * 1.5, i)
        out.append(s * adsr(i, dur, 0.01, 0.7) * 0.5)
    return out


def win():
    # cheerful three-note arpeggio C-E-G-C
    notes = [523.25, 659.25, 783.99, 1046.5]
    seg = int(RATE * 0.10)
    out = []
    for n, f in enumerate(notes):
        for i in range(seg):
            s = 0.6 * sine(f, i) + 0.2 * sine(f * 2, i)
            out.append(s * adsr(i, seg, 0.005, 0.6) * 0.55)
    return out


def main():
    random.seed(7)
    for name, fn in (("pickup.wav", pickup), ("hit.wav", hit),
                     ("start.wav", start), ("win.wav", win)):
        p = _save(name, fn())
        print("wrote", p)


if __name__ == "__main__":
    main()
