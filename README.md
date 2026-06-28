# Tether — mobile arcade game (Kivy)

You drag the **ring** (anchor). A heavy **bob** hangs off it on a springy tether
and swings, lags and overshoots. You can't place the bob — you *whip* it: flick
the anchor and let momentum sling the bob where you want it.

Two modes from the start menu:
- **Levels** — 20 numbered levels; thread the jiggly bob to the green **exit**.
  Tiles show locks, unlocks and earned **stars**, saved between runs. Every level
  is guaranteed beatable on a **single life** (a no-hit route is BFS-verified).
- **Survival** — endless arena: whip the bob through orbs for score + combo while
  the mine swarm keeps growing. The high score is tracked **per difficulty**.

**Difficulty** sets your lives and applies to both modes:
**Easy 5 · Medium 3 · Hard 1** (chosen on the menu, saved between runs).

**Obstacles**
- **Walls** — solid *and* dangerous: touching one costs a life and bounces the bob.
- **Static mines** — fixed red spikes.
- **Moving mines** — patrol back and forth along corridors.
- **Spinners** — rotating bars that sweep an area; time your passage.
- **Orbs** (cyan) — optional collectibles that help your star rating.

Levels are authored as ASCII grids in `LEVELS` (top of `main.py`) — `#` wall,
`S` start, `G` goal, `x`/`m` static/moving mine, `O` spinner, `*` orb. Every grid
is BFS-checked for solvability before it loads, so a new level can't be a dead end.


## Run on desktop (to test)

```bash
pip install kivy
python main.py
```

Drag with the mouse to steer. The game is **fully touch-driven — no keyboard is
required**: tap the on-screen buttons (Play, level tiles, Resume/Retry/Next),
drag to steer, tap the ⏸ button to pause. Keyboard input is an optional desktop
convenience only: arrows / WASD steer, `P` pauses.

## Regenerate art + sound

Art — `data/icon.png` (512²) and `data/presplash.png` (1024²):

```bash
pip install pillow
python make_assets.py
```

Sound — `data/pickup.wav`, `data/hit.wav`, `data/start.wav` (stdlib only, no deps):

```bash
python make_sounds.py
```

The game loads the sfx automatically; if the files are absent it runs silently.

## Build the Android app (APK / AAB)

Buildozer runs on **Linux or WSL2** (not native Windows). On Windows 11:

```bash
# in WSL2 Ubuntu
sudo apt update && sudo apt install -y git zip unzip openjdk-17-jdk python3-pip \
    autoconf libtool pkg-config zlib1g-dev libncurses-dev libffi-dev libssl-dev
pip install --user buildozer cython

cd /mnt/c/Users/User/testApp/tether_app
buildozer -v android debug        # -> bin/tether-1.0.0-debug.apk
```

Install the debug APK on a connected device:

```bash
buildozer android deploy run
```

For a Play Store upload, build a signed release bundle:

```bash
buildozer android release         # -> bin/tether-1.0.0-release.aab
```

Then sign the `.aab` with your upload key (`jarsigner` / Android `apksigner`) and
upload it in the Play Console. The first build downloads the Android SDK/NDK and
takes a while; later builds are incremental.

## Play Store checklist (beyond this repo)

The code, icon, splash, versioning, package id (`com.sorbor.tether`) and AAB
target are set in `buildozer.spec`. Still required in the Play Console:

- Developer account (one-time fee) and an **upload key**.
- Store listing: short + full description, feature graphic (1024×500),
  2–8 screenshots, category (Arcade), content rating questionnaire.
- A **privacy policy URL** (the app requests no sensitive data; INTERNET
  permission can be removed in `buildozer.spec` if you add no networking).
- Target API level compliance (currently API 34).

## Files

| File | Purpose |
|------|---------|
| `main.py` | The game (Kivy). All text drawn on a per-frame-cleared canvas — screens cannot stick. |
| `buildozer.spec` | Android packaging config. |
| `make_assets.py` | Generates icon + presplash. |
| `make_sounds.py` | Generates the three .wav sfx (stdlib only). |
| `data/` | Icon, splash, and `pickup.wav` / `hit.wav` / `start.wav`. |

Sound files are bundled. To swap in your own, drop `pickup`/`hit`/`start` as
`.ogg` (preferred) or `.wav` into `data/`; absent, the game runs silently.
