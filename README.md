# osu! Autoplayer 🎵

A **memory-based rhythm game autoplayer** for osu! that reads hit objects and timing directly from the game's process memory, then simulates human-like input with configurable humanization profiles.

## What This Does

**Hybrid approach for maximum compatibility:**
1. **Hit objects from .osu files** — Parse beatmap files for 100% reliable hit detection (works in osu!lazer)
2. **Game timing from memory** — Sync playback with actual game clock for perfect timing
3. **Humanized input generation** — No robotic perfection, but realistic variance
4. **Dual-mode support** for both **mania** (keys) and **standard** (mouse) modes

Think of it as a "perfect player with flaws" — it hits notes accurately but with natural timing jitter, late lapses, and aim inaccuracy.

**Works with:**
- ✅ **osu!lazer** (main focus)
- ✅ **osu! stable** (legacy support)

## Features

### 🎮 Mania Mode (osu!mania)
- **Memory-based hit object reading** from any key count (1K-9K)
- **4 humanization profiles:**
  - `robot` — Perfect timing, no variance
  - `streamy` — High variance, fast presses (6-10ms jitter)
  - `stamina` — Medium variance, realistic holds
  - `aggressive` — Low variance, tight 40-90ms taps

### ⭕ Standard Mode (osu! classic)
- **`.osu` file parsing** for circles, sliders, spinners
- **Mouse movement + click** simulation with pydirectinput
- **3 standard profiles:**
  - `robot` — Perfect clicks, no aim error
  - `precise` — 5px aim accuracy, -1ms timing bias
  - `casual` — 15px aim error, 8ms click variance

### 🎛️ Humanization Engine
- **Per-note Gaussian timing jitter** (configurable stddev)
- **Chord splay** — prevents simultaneous key presses
- **Slider release jitter** — realistic hold release timing
- **Late lapses** — occasional 10-24ms delays (simulates human fatigue)
- **Speed mod support** — DT/NC (1.5x), HT (0.75x)

## How It Works (Hybrid Approach)

```
┌──────────────────────────────────────┐         ┌──────────────────────────────┐
│ .osu File (beatmap)                  │         │ osu! Game Process            │
│  ├─ [Difficulty] → key count (mania) │         │  ├─ Game memory              │
│  ├─ [HitObjects] → coordinates       │         │  └─ Current playback time    │
│  └─ [TimingPoints] → BPM             │         └──────────────────────────────┘
└──────────────────────────────────────┘                      ↓
         ↓                                      ┌──────────────────────────────┐
┌──────────────────────────────────────┐       │ Memory Scanning              │
│ .osu File Parser                     │       │  ├─ Find game time address   │
│  ├─ Parse [HitObjects] section       │       │  └─ Poll current playback ms │
│  ├─ Extract x,y (standard) or x→col  │       └──────────────────────────────┘
│  │  (mania)                          │                      ↓
│  └─ Get timing (always from file)    │       ┌──────────────────────────────┐
└──────────────────────────────────────┘       │ Sync Hit Objects with Time   │
         ↓                                      │  ├─ Match file times to      │
┌──────────────────────────────────────┐       │  │  game clock              │
│ Humanization (timing variance)       │       │  └─ Convert to actions      │
│  ├─ Gaussian jitter                  │       └──────────────────────────────┘
│  ├─ Late lapses                      │                      ↓
│  └─ Chord splay                      │       ┌──────────────────────────────┐
└──────────────────────────────────────┘       │ Input Simulation            │
         ↓                                      │  ├─ Key presses (mania)     │
┌──────────────────────────────────────┐       │  └─ Mouse moves (standard)  │
│ Action Generation                    │       └──────────────────────────────┘
│  ├─ Press/release actions (mania)    │
│  └─ Move/click actions (standard)    │
└──────────────────────────────────────┘
```

**Why Hybrid?**
- **File parsing**: 100% reliable, works across game updates, no memory scanning needed
- **Memory timing**: Ensures playback sync with game's actual audio clock
- **Best of both**: No more memory offset hunting!

## Installation

### Requirements
- **Python 3.8+**
- **osu! stable** (32-bit, not lazer) running fullscreen
- **Windows** (64-bit Python on 32-bit osu!)

### Setup
```bash
git clone https://github.com/whiteaeon/osu-autoplayer.git
cd osu-autoplayer
pip install -r requirements.txt
```

### Dependencies
- `pymem` — Process memory reading
- `pydirectinput` — Low-latency input simulation

## Usage

### Interactive Menu
```bash
python run.bat
```
Select mode (mania/standard) and profile from the menu.

### Command Line
```bash
# Mania mode with streamy profile
python main.py --mode mania --profile streamy

# Standard mode with custom map
python main.py --mode standard --map "D:\path\to\map.osu" --profile precise

# Robot mode (perfect timing)
python main.py --mode mania --robot

# Custom humanization
python main.py --stddev 15 --mean -5 --tap-min 50 --tap-max 100

# With timing offset
python main.py --offset -20  # Press 20ms earlier
```

### Arguments
```
--mode {mania,standard}      Game mode (default: mania)
--profile NAME               Humanization profile (robot/streamy/stamina/aggressive)
--map FILE                   For standard mode: path to .osu file
--offset MS                  Timing offset in milliseconds
--mod MOD                    Speed mod (DT/NC/HT)
--robot                      Perfect timing (no humanization)
--stddev MS                  Per-note timing jitter (default: 11ms)
--mean MS                    Timing bias (default: 0ms)
--tap-min MS                 Min tap duration (default: 40ms)
--tap-max MS                 Max tap duration (default: 90ms)
```

## Technical Details

### Hybrid Architecture

**1. .osu File Parsing (Hit Objects)**
Standard beatmap file format:
```
[HitObjects]
x,y,time,type,hitSound,objectParams
256,192,1000,1,0,B|300|200|200|150,2,50
```
- **Standard mode**: x,y = screen coordinates (0-512, 0-384)
- **Mania mode**: x → column index (based on key count from CircleSize)
- `type & 1` = circle, `type & 2` = slider, `type & 8` = spinner

**2. Memory Scanning (Game Time Only)**
For osu!lazer and stable, we scan for:
- Game time address (current playback position in ms)
- Game status (playing/stopped/paused)

Signature scanning handles game updates automatically — no hardcoded offsets.

### Why Not Pure Memory Reading?
Memory layout is different between osu! stable and lazer, and lazer changes frequently. The hybrid approach:
- ✅ Works with both stable and lazer
- ✅ Survives game updates  
- ✅ No memory offset hunting
- ❌ Requires .osu files (always present when playing)

## Debugging

### View Memory Offsets
```bash
python debug_memory.py
```
Displays raw hit object memory data while a map plays. Useful for verifying offsets after osu! updates.

### Enable Verbose Output
Add this to `main.py` in the `play()` function to log every action:
```python
print(f"[play] Action {i}: {a}")
```

## Limitations

- **Windows only** (memory reading is OS-specific)
- **Fullscreen mode** required (for accurate cursor positioning in standard mode)
- **No slider curve simulation yet** (standard mode uses linear interpolation)
- **No spinner handling** (spinners are skipped in both modes)
- **Requires .osu files** (beatmaps must be downloaded/cached)

## Disclaimer

⚠️ **This is for fun/research only.** Using autoplayers in ranked osu! is against ToS and will result in account restrictions. Use only on unranked maps or private servers.

## Contributing

Found a memory offset that's wrong? New game mode? Submit an issue or PR!

```bash
git checkout -b feature/something-cool
git commit -m "Add xyz"
git push origin feature/something-cool
```

## License

MIT — Do whatever you want with this code.

---

**Made with frustration and rhythm games** 🎵
