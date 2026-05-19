# osu! Autoplayer 🎵

A **memory-based rhythm game autoplayer** for osu! that reads hit objects and timing directly from the game's process memory, then simulates human-like input with configurable humanization profiles.

## What This Does

Instead of reading beatmap files (like most bots), this plays maps by:
1. **Memory scanning** the running osu! process to extract real-time game state
2. **Hit object detection** with sub-millisecond timing precision
3. **Humanized input generation** — no robotic perfection, but realistic variance
4. **Dual-mode support** for both **mania** (keys) and **standard** (mouse) modes

Think of it as a "perfect player with flaws" — it hits notes accurately but with natural timing jitter, late lapses, and aim inaccuracy.

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

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│ osu! process running                                    │
│  ├─ Game memory (hit objects, timing, status)          │
│  └─ .osu file (map metadata, coordinates)              │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Memory Scanning (VirtualQueryEx signature scanning)     │
│  ├─ Find hit object list in executable regions         │
│  ├─ Read timing: obj + 0x10 (start_time), 0x14 (end)   │
│  └─ Mania: obj + 0x9C (column), Standard: 0x90 (x), 0x8C (y) │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Humanization (timing variance, aim error, late lapses) │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Action Generation (press/release/click/move events)    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ Input Simulation (pydirectinput: keys or mouse)        │
│  ├─ Mania: keyDown(key), keyUp(key)                    │
│  └─ Standard: moveTo(x, y), click()                    │
└─────────────────────────────────────────────────────────┘
```

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

### Memory Layout (osu! stable)
**Hit Object Structure:**
```
offset   type      meaning
0x10     int32     start_time (milliseconds)
0x14     int32     end_time (ms) — equals start for circles/taps
0x88     float32   [mania] x position? [standard] unused
0x90     float32   [standard] x coordinate (0-512)
0x8C     float32   y coordinate (0-384)
0x9C     int32     kind (0=circle, 1=slider, 2=spinner, [mania] column)
```

**Player State Chain:**
```
player_pointer
  ↓ + 0x48
hit_manager
  ↓ + 0x48
list_container
  ├─ + 0x04 → content_ptr (array of hit object pointers)
  ├─ + 0x0C → size (number of objects)
  └─ + 0x08 → content[i] (individual object pointer)
```

### Signature Scanning
Uses regex-based pattern matching to find memory addresses across all JIT-compiled executable regions, surviving osu! updates that shuffle .NET heap addresses.

### .osu File Parsing
Standard beatmap file format:
```
[HitObjects]
x,y,time,type,hitSound,objectParams
256,192,1000,1,0,B|300|200|200|150,2,50
```
- `type & 1` = circle
- `type & 2` = slider  
- `type & 8` = spinner

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
- **osu! stable only** (lazer uses different memory layout)
- **Fullscreen required** (for accurate mouse coordinates)
- **No slider curve simulation yet** (standard mode)
- **No spinner handling** (skipped)

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
