"""
osu! mania Autoplayer - memory-based, maniac approach.
https://github.com/fs-c/maniac  (inspiration / memory layout)

Reads hit objects and game time directly from osu!'s process memory.
No .osu file parsing, no screen detection, no external tool required.

Humanization (on by default):
  - Gaussian timing jitter per note
  - Variable tap-hold duration
  - Chord splay: no two columns hit on the same exact ms
  - Slider release jitter

Usage:
    python main.py
    python main.py --offset -20
    python main.py --robot                 # perfect timing
    python main.py --stddev 12 --mean -2

Press Ctrl+C to stop.
"""

import argparse
import os
import random
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import List

from osu_memory import OsuMemory, HitObject, HitObjectStandard
from osu_parser import get_hit_objects_from_map, OsuHitObject, parse_osu_file, get_game_mode
from lazer_detect import get_current_beatmap_file, get_osu_window_title, wait_for_gameplay_start
from input_simulator import InputSimulator

# ---------------------------------------------------------------------------
# Mod definitions  (speed multipliers for timing adjustment)
# ---------------------------------------------------------------------------
MODS = {
    # Speed-affecting mods
    "DT": {"name": "Double Time", "speed": 1.5},
    "NC": {"name": "Nightcore", "speed": 1.5},
    "HT": {"name": "Half Time", "speed": 0.75},
    # Non-speed mods (don't affect timing, just difficulty/visibility)
    "HD": {"name": "Hidden", "speed": 1.0},
    "FL": {"name": "Flashlight", "speed": 1.0},
    "EZ": {"name": "Easy", "speed": 1.0},
    "HR": {"name": "Hard Rock", "speed": 1.0},
    "NF": {"name": "No Fail", "speed": 1.0},
    "SD": {"name": "Sudden Death", "speed": 1.0},
    "PF": {"name": "Perfect", "speed": 1.0},
    "FI": {"name": "Fade In", "speed": 1.0},
}

# ---------------------------------------------------------------------------
# Default key layouts  (same as maniac's key_subset logic)
# ---------------------------------------------------------------------------
DEFAULT_KEYS = {
    1:  ["space"],
    2:  ["f", "j"],
    3:  ["f", "space", "j"],
    4:  ["d", "f", "j", "k"],
    5:  ["d", "f", "space", "j", "k"],
    6:  ["s", "d", "f", "j", "k", "l"],
    7:  ["s", "d", "f", "space", "j", "k", "l"],
    8:  ["a", "s", "d", "f", "j", "k", "l", ";"],
    9:  ["a", "s", "d", "f", "space", "j", "k", "l", ";"],
}

# ---------------------------------------------------------------------------
# Humanization profiles  (preset configurations for different play styles)
# ---------------------------------------------------------------------------
PROFILES = {
    "robot": {
        "stddev": 0,
        "mean": 0,
        "tap_min": 20,
        "tap_max": 20,
        "chord_splay": 0,
        "slider_jitter": 0,
        "late_lapse_rate": 0.0,
        "late_lapse_range": [0, 0],
    },
    "streamy": {
        "stddev": 10,
        "mean": -1,
        "tap_min": 30,
        "tap_max": 60,
        "chord_splay": 5,
        "slider_jitter": 8,
        "late_lapse_rate": 0.03,
        "late_lapse_range": [3, 10],
    },
    "stamina": {
        "stddev": 6,
        "mean": 0,
        "tap_min": 60,
        "tap_max": 100,
        "chord_splay": 2,
        "slider_jitter": 4,
        "late_lapse_rate": 0.05,
        "late_lapse_range": [5, 15],
    },
    "aggressive": {
        "stddev": 4,
        "mean": 1,
        "tap_min": 35,
        "tap_max": 65,
        "chord_splay": 1,
        "slider_jitter": 2,
        "late_lapse_rate": 0.02,
        "late_lapse_range": [2, 8],
    },
}

# ---------------------------------------------------------------------------
# Humanization defaults  (loosely modelled on a strong human player)
# ---------------------------------------------------------------------------
DEFAULT_STDDEV        = 8     # ms - stddev on each press (tighter for fewer misses)
DEFAULT_MEAN          = 0     # ms - bias (0 = centered, -3 to -10 = more human-early)
DEFAULT_TAP_MIN       = 40    # ms - min tap-hold duration (mash-style)
DEFAULT_TAP_MAX       = 90    # ms - max tap-hold duration (mash-style)
DEFAULT_CHORD_SPLAY   = 3     # ms - max per-note offset within a chord
DEFAULT_SLIDER_JITTER = 6     # ms - stddev on slider release time

# Late lapses - occasional extra delay on random notes to add variance.
# Since the default mean is now 0 (centered), we don't need aggressive late
# lapses to balance an asymmetric distribution. Keep it subtle.
DEFAULT_LATE_LAPSE_RATE   = 0.05   # fraction of notes that get a late kick (more variance)
DEFAULT_LATE_LAPSE_MIN_MS = 5      # ms - min late kick
DEFAULT_LATE_LAPSE_MAX_MS = 15     # ms - max late kick

# Break tapping - random rhythm taps during long gaps between notes
DEFAULT_BREAK_TAP_INTERVAL = 0     # ms - 0 = off, >0 = tap every N ms during breaks
DEFAULT_BREAK_MIN_GAP      = 1000  # ms - minimum gap to trigger break tapping

_MIN_LN_MS = 15   # never let jitter invert a slider


# ---------------------------------------------------------------------------
# Action  (mirrors maniac's Action struct)
# ---------------------------------------------------------------------------
@dataclass
class Action:
    time:   int    # ms - when to fire
    column: int    # key index
    down:   bool   # True = press, False = release

    def __lt__(self, other):
        return self.time < other.time


# ---------------------------------------------------------------------------
# Standard Mode Action  (for osu! standard / circles / sliders)
# ---------------------------------------------------------------------------
@dataclass
class ActionStandard:
    time:           int    # ms - when to execute
    x:              float  # 0-512 game coordinates
    y:              float  # 0-384 game coordinates
    mouse_action:   str    # "move" | "click" | "hold_start" | "hold_end"

    def __lt__(self, other):
        return self.time < other.time


# ---------------------------------------------------------------------------
# Standard mode profiles  (for osu! standard - circles, sliders)
# ---------------------------------------------------------------------------
STANDARD_PROFILES = {
    "robot": {
        "click_stddev": 0,
        "click_mean": 0,
        "aim_accuracy_px": 0,
        "late_lapse_rate": 0.0,
        "late_lapse_range": [0, 0],
    },
    "precise": {
        "click_stddev": 3,
        "click_mean": -1,
        "aim_accuracy_px": 5,
        "late_lapse_rate": 0.02,
        "late_lapse_range": [2, 8],
    },
    "casual": {
        "click_stddev": 8,
        "click_mean": 0,
        "aim_accuracy_px": 15,
        "late_lapse_rate": 0.08,
        "late_lapse_range": [8, 20],
    },
    "tremolo": {
        "click_stddev": 6,
        "click_mean": -2,
        "aim_accuracy_px": 10,
        "late_lapse_rate": 0.05,
        "late_lapse_range": [5, 15],
    },
}

# ---------------------------------------------------------------------------
# Humanization
# ---------------------------------------------------------------------------
def humanize(
    objects: List[HitObject],
    timing_stddev_ms:         int   = DEFAULT_STDDEV,
    timing_mean_ms:           int   = DEFAULT_MEAN,
    chord_splay_ms:           int   = DEFAULT_CHORD_SPLAY,
    slider_release_stddev_ms: int   = DEFAULT_SLIDER_JITTER,
    late_lapse_rate:          float = DEFAULT_LATE_LAPSE_RATE,
    late_lapse_min_ms:        int   = DEFAULT_LATE_LAPSE_MIN_MS,
    late_lapse_max_ms:        int   = DEFAULT_LATE_LAPSE_MAX_MS,
) -> None:
    """
    Add human-like timing variation in four layers:

      1. Per-note Gaussian press jitter        (timing_stddev_ms, timing_mean_ms)
      2. Independent Gaussian slider releases  (slider_release_stddev_ms)
      3. Late lapses                           (late_lapse_rate)
         Small fraction of notes get an extra positive delay. Counters the
         one-sided latency floor so the hit histogram has a visible late tail.
      4. Chord splay                           (chord_splay_ms)
         Notes that share a press time get small per-note offsets so chords
         aren't all struck on the exact same millisecond.
    """
    if not objects:
        return

    # 1 + 2 - per-note jitter
    for obj in objects:
        if timing_stddev_ms > 0 or timing_mean_ms != 0:
            jitter = int(random.gauss(timing_mean_ms, max(timing_stddev_ms, 0)))
            obj.start_time += jitter
        if obj.is_slider:
            if slider_release_stddev_ms > 0:
                obj.end_time += int(random.gauss(0, slider_release_stddev_ms))
            if obj.end_time < obj.start_time + _MIN_LN_MS:
                obj.end_time = obj.start_time + _MIN_LN_MS

    # 3 - late lapses
    if late_lapse_rate > 0 and late_lapse_max_ms >= late_lapse_min_ms > 0:
        for obj in objects:
            if random.random() < late_lapse_rate:
                obj.start_time += random.randint(late_lapse_min_ms, late_lapse_max_ms)

    # 4 - chord splay
    if chord_splay_ms > 0:
        groups = defaultdict(list)
        for obj in objects:
            groups[obj.start_time].append(obj)
        for group in groups.values():
            if len(group) >= 2:
                for obj in group:
                    obj.start_time += random.randint(-chord_splay_ms, chord_splay_ms)


# ---------------------------------------------------------------------------
# Break rhythm tapping - pattern generator
# ---------------------------------------------------------------------------
def generate_break_pattern(
    break_duration_ms: int,
    tap_interval_ms: int,
    col_count: int,
) -> List[tuple[int, int]]:
    """
    Generate a human-like break tap pattern.

    Returns list of (column, hold_duration_ms) tuples to tap in sequence.
    Behavior varies by break length:
    - Short breaks (< 3s): Steady, continuous taps (stay engaged)
    - Medium breaks (3-8s): Regular taps with occasional rest gaps
    - Long breaks (>= 8s): Sparse taps with frequent rest periods

    Column selection alternates (avoids repeating same column).
    """
    if break_duration_ms <= 0 or tap_interval_ms <= 0 or col_count <= 0:
        return []

    pattern: List[tuple[int, int]] = []

    # Determine tap density based on break length
    if break_duration_ms < 3000:
        tap_density = 1.0  # Always tap (stay engaged during short breaks)
        rest_probability = 0.0
    elif break_duration_ms < 8000:
        tap_density = 0.85  # 85% chance to tap
        rest_probability = 0.15  # 15% chance to skip this interval
    else:
        tap_density = 0.65  # 65% chance to tap
        rest_probability = 0.35  # 35% chance to skip this interval

    # Generate alternating column pattern (realistic hand alternation)
    prev_col = None
    current_time = 0

    while current_time < break_duration_ms:
        # Occasionally take a rest period (skip 1-2 intervals)
        if random.random() < rest_probability:
            skip_intervals = random.randint(1, 2)
            current_time += tap_interval_ms * skip_intervals
            continue

        # Decide whether to tap at this interval
        if random.random() < tap_density:
            # Choose column, preferring to alternate hands
            cols_available = list(range(col_count))
            if prev_col is not None and col_count > 1:
                # Remove previous column from options to force alternation
                cols_available = [c for c in cols_available if c != prev_col]
            col = random.choice(cols_available)
            hold = random.randint(15, 40)  # Shorter, more realistic holds during breaks

            pattern.append((col, hold))
            prev_col = col

        current_time += tap_interval_ms

    return pattern


# ---------------------------------------------------------------------------
# Break rhythm tapping - action generation
# ---------------------------------------------------------------------------
def add_break_taps(
    objects:           List[HitObject],
    actions:           List[Action],
    col_count:         int,
    tap_interval_ms:   int = 400,
    min_break_ms:      int = 1000,
    tap_min_ms:        int = 20,
    tap_max_ms:        int = 40,
    debug:             bool = False,
) -> None:
    """
    During long gaps (>= min_break_ms), add human-like rhythm taps.

    Uses generate_break_pattern() to create a pattern that varies by break length:
    - Short breaks: Continuous taps (stay engaged)
    - Long breaks: Sparse taps with rest periods (realistic fidgeting)
    - Column alternation: Avoids tapping same column twice in a row
    """
    if not objects or col_count <= 0 or tap_interval_ms <= 0:
        return

    taps_added = 0
    breaks_found = 0

    for i in range(len(objects) - 1):
        break_start = objects[i].end_time
        break_end = objects[i + 1].start_time
        break_duration = break_end - break_start

        if break_duration < min_break_ms:
            continue

        breaks_found += 1

        # Generate a human-like tap pattern for this break
        pattern = generate_break_pattern(
            break_duration_ms=break_duration,
            tap_interval_ms=tap_interval_ms,
            col_count=col_count,
        )

        # Convert pattern to Action objects with proper timing
        current_time = break_start + tap_interval_ms
        pattern_idx = 0

        while current_time < break_end and pattern_idx < len(pattern):
            col, hold_duration = pattern[pattern_idx]

            # Clamp hold duration to configured bounds
            hold = max(tap_min_ms, min(tap_max_ms, hold_duration))

            actions.append(Action(int(current_time), col, True))
            actions.append(Action(int(current_time + hold), col, False))

            taps_added += 2
            pattern_idx += 1
            current_time += tap_interval_ms

    if debug and breaks_found > 0:
        print(f"[break-taps] Found {breaks_found} breaks, added {taps_added} tap actions")


# ---------------------------------------------------------------------------
# Standard mode humanization
# ---------------------------------------------------------------------------
def humanize_standard(
    objects: List,  # List[HitObjectStandard]
    click_stddev_ms: int = 3,
    click_mean_ms: int = -1,
    late_lapse_rate: float = 0.02,
) -> None:
    """Apply human-like timing variance to osu! standard hit objects."""
    for obj in objects:
        if click_stddev_ms > 0 or click_mean_ms != 0:
            jitter = int(random.gauss(click_mean_ms, click_stddev_ms))
            obj.start_time += jitter

        # Late lapses: occasionally add extra delay
        if late_lapse_rate > 0 and random.random() < late_lapse_rate:
            obj.start_time += random.randint(5, 20)


# ---------------------------------------------------------------------------
# Standard mode action generation
# ---------------------------------------------------------------------------
def to_actions_standard(
    objects: List,  # List[HitObjectStandard]
    offset_ms: int = 0,
    speed_multiplier: float = 1.0,
    aim_accuracy_px: int = 5,
) -> List[ActionStandard]:
    """
    Convert osu! standard hit objects to mouse actions.

    For circles: Move to position → Click
    For sliders: Move to start → Hold down → Move along curve → Release
    For spinners: Skipped (not implemented yet)
    """
    actions: List[ActionStandard] = []

    for obj in objects:
        start_time = int(obj.start_time / speed_multiplier) + offset_ms

        if obj.kind == 2:  # Spinner
            # Skip spinners for now
            continue

        if obj.kind == 0:  # Circle
            # Add aim inaccuracy (hit off-center)
            aim_offset_x = random.randint(-aim_accuracy_px, aim_accuracy_px)
            aim_offset_y = random.randint(-aim_accuracy_px, aim_accuracy_px)

            # Move to position (arrive early so click happens at the right time)
            actions.append(ActionStandard(
                time=start_time - 5,  # Move 5ms before click
                x=obj.x + aim_offset_x,
                y=obj.y + aim_offset_y,
                mouse_action="move"
            ))

            # Click at the exact hit time
            actions.append(ActionStandard(
                time=start_time,
                x=obj.x,
                y=obj.y,
                mouse_action="click"
            ))

        elif obj.kind == 1:  # Slider
            end_time = int(obj.end_time / speed_multiplier) + offset_ms

            # Move to start and hold down
            actions.append(ActionStandard(
                time=start_time,
                x=obj.x,
                y=obj.y,
                mouse_action="move"
            ))
            actions.append(ActionStandard(
                time=start_time,
                x=obj.x,
                y=obj.y,
                mouse_action="hold_start"
            ))

            # TODO: Generate curve path (Bézier) - for now just move to end
            # In a full implementation, would read slider curve points from memory
            # and generate smooth interpolated path
            step_ms = 10
            steps = max(1, (end_time - start_time) // step_ms)
            for i in range(1, steps):
                t = i / steps
                # Linear interpolation (simplified - full version needs Bézier)
                x = obj.x + (0 - obj.x) * t  # Placeholder: no end position
                y = obj.y + (0 - obj.y) * t
                actions.append(ActionStandard(
                    time=start_time + i * step_ms,
                    x=x,
                    y=y,
                    mouse_action="move"
                ))

            # Release mouse button at end
            actions.append(ActionStandard(
                time=end_time,
                x=obj.x,
                y=obj.y,
                mouse_action="hold_end"
            ))

    return sorted(actions)


# ---------------------------------------------------------------------------
# Convert hit objects to Action list (mirrors maniac's to_actions())
# ---------------------------------------------------------------------------
def to_actions(
    objects:           List[HitObject],
    tap_min_ms:        int = DEFAULT_TAP_MIN,
    tap_max_ms:        int = DEFAULT_TAP_MAX,
    offset_ms:         int = 0,
    speed_multiplier:  float = 1.0,
) -> List[Action]:
    """
    Build a sorted, deduplicated list of press/release actions.
    Tap notes:  release = start + random[tap_min_ms, tap_max_ms]
    Hold notes: release = end_time (already jittered by humanize())

    For speed mods (DT/NC = 1.5x, HT = 0.75x), times are scaled:
      adjusted_time = original_time / speed_multiplier
    """
    if tap_min_ms > tap_max_ms:
        tap_min_ms, tap_max_ms = tap_max_ms, tap_min_ms

    actions: List[Action] = []
    for obj in objects:
        # Scale times for speed mods
        start_time = obj.start_time / speed_multiplier

        if obj.is_slider:
            end_time = obj.end_time / speed_multiplier
            release_time = end_time
        else:
            release_time = start_time + random.randint(tap_min_ms, tap_max_ms)

        actions.append(Action(int(start_time) + offset_ms, obj.column, True))
        actions.append(Action(int(release_time) + offset_ms, obj.column, False))

    actions.sort()

    seen = set()
    unique: List[Action] = []
    for a in actions:
        key = (a.time, a.column, a.down)
        if key not in seen:
            seen.add(key)
            unique.append(a)

    return unique


# ---------------------------------------------------------------------------
# Play loop  (mirrors maniac's play())
# ---------------------------------------------------------------------------
def play(mem: OsuMemory, actions: List[Action], sim: InputSimulator, mode: str = "mania") -> None:
    """
    Execute actions timed against osu!'s internal game clock.

    The game clock is read from memory on every iteration so timing is
    perfectly synced with osu!'s own audio clock - no wall-clock drift.

    mode: "mania" for keyboard actions, "standard" for mouse actions.
    """
    if mode == "mania":
        # Release all keys before starting (mirrors maniac's reset_keys())
        for col in range(sim.key_count):
            try:
                sim.release_column(col)
            except Exception:
                pass
    else:
        # Standard mode: move cursor to center
        try:
            sim.move_cursor(256, 192)  # Center of 512x384
        except Exception:
            pass

    i     = 0
    total = len(actions)
    errors = 0

    while i < total:
        if not mem.is_playing():
            return

        cur_time = mem.get_game_time()

        # Fire every action whose time has been reached
        while i < total and actions[i].time <= cur_time:
            a = actions[i]
            try:
                if mode == "mania":
                    # Mania mode: keyboard actions
                    if a.down:
                        sim.press_column(a.column)
                    else:
                        sim.release_column(a.column)
                elif mode == "standard":
                    # Standard mode: mouse actions
                    if a.mouse_action == "move":
                        sim.move_cursor(a.x, a.y)
                    elif a.mouse_action == "click":
                        sim.click()
                    elif a.mouse_action == "hold_start":
                        sim.mouse_down()
                    elif a.mouse_action == "hold_end":
                        sim.mouse_up()
            except Exception as e:
                errors += 1
                if errors <= 10:  # Only print first 10 errors to avoid spam
                    print(f"[play] Input error at action {i}: {e}")
            i += 1

        # Sleep briefly - game clock is polled at ~1 kHz
        # maniac uses 100 ns; Python minimum is ~1 ms, which is fine
        # (the fastest osu! note spacing is ~10 ms at extreme BPM)
        if i < total:
            ms_to_next = actions[i].time - cur_time
            if ms_to_next > 5:
                time.sleep(0.001)

    if errors > 0:
        print(f"\n[play] Total input errors: {errors}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="osu! mania autoplayer - reads from process memory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--mode", type=str, choices=["mania", "standard"], default="mania",
                    metavar="MODE",
                    help="Game mode: mania (default) or standard (osu! classic)")
    ap.add_argument("--map", type=str, metavar="MAPFILE",
                    help="For standard mode: full path to .osu file to play")
    ap.add_argument("--offset", type=int, default=0, metavar="MS",
                    help="Global timing offset in ms (default: 0). "
                         "Negative = press earlier.")
    ap.add_argument("--mod", type=str, metavar="MOD",
                    help="Mod name: DT/NC (1.5x), HT (0.75x), HD, FL, EZ, HR, NF, SD, PF, FI. "
                         "Speed mods adjust timing.")
    # Combine both mania and standard profiles for choices
    all_profiles = list(PROFILES.keys()) + list(STANDARD_PROFILES.keys())
    ap.add_argument("--profile", type=str, metavar="NAME",
                    choices=all_profiles,
                    help=f"Mania profiles: {', '.join(PROFILES.keys())}. "
                         f"Standard profiles: {', '.join(STANDARD_PROFILES.keys())}.")
    ap.add_argument("--robot", action="store_true",
                    help="Disable all humanization - perfect timing.")
    ap.add_argument("--stddev", type=int, default=DEFAULT_STDDEV, metavar="MS",
                    help=f"Per-note Gaussian stddev in ms (default: {DEFAULT_STDDEV}, 0 = off).")
    ap.add_argument("--mean", type=int, default=DEFAULT_MEAN, metavar="MS",
                    help=f"Per-note timing bias in ms (default: {DEFAULT_MEAN}). "
                         "Negative = early, positive = late.")
    ap.add_argument("--tap-min", type=int, default=DEFAULT_TAP_MIN, metavar="MS",
                    help=f"Min tap-hold duration in ms (default: {DEFAULT_TAP_MIN}).")
    ap.add_argument("--tap-max", type=int, default=DEFAULT_TAP_MAX, metavar="MS",
                    help=f"Max tap-hold duration in ms (default: {DEFAULT_TAP_MAX}).")
    ap.add_argument("--chord-splay", type=int, default=DEFAULT_CHORD_SPLAY, metavar="MS",
                    help=f"Max per-note splay within chords in ms "
                         f"(default: {DEFAULT_CHORD_SPLAY}, 0 = off).")
    ap.add_argument("--slider-jitter", type=int, default=DEFAULT_SLIDER_JITTER, metavar="MS",
                    help=f"Slider-release stddev in ms (default: {DEFAULT_SLIDER_JITTER}, 0 = off).")
    ap.add_argument("--late-lapse-rate", type=float, default=DEFAULT_LATE_LAPSE_RATE,
                    metavar="P",
                    help=f"Fraction of notes that get an extra late delay "
                         f"(default: {DEFAULT_LATE_LAPSE_RATE}, 0 = off).")
    ap.add_argument("--late-lapse-range", type=int, nargs=2, metavar=("MIN", "MAX"),
                    default=[DEFAULT_LATE_LAPSE_MIN_MS, DEFAULT_LATE_LAPSE_MAX_MS],
                    help=f"Late-lapse delay range in ms "
                         f"(default: {DEFAULT_LATE_LAPSE_MIN_MS} {DEFAULT_LATE_LAPSE_MAX_MS}).")
    ap.add_argument("--break-tap-interval", type=int, default=DEFAULT_BREAK_TAP_INTERVAL,
                    metavar="MS",
                    help=f"Tap during breaks every N ms (default: {DEFAULT_BREAK_TAP_INTERVAL}, 0 = off). "
                         "Taps vary by break length with column alternation. e.g., 400 = tap every 400ms.")
    ap.add_argument("--keys", nargs="+", metavar="KEY",
                    help="Override key layout left-to-right "
                         "(e.g. --keys d f j k).")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    # Apply profile if specified (before other overrides like --robot)
    # Profiles can be mania or standard depending on which dict they're in
    if args.profile:
        if args.profile in PROFILES:
            # Mania profile
            profile = PROFILES[args.profile]
            args.stddev = profile["stddev"]
            args.mean = profile["mean"]
            args.tap_min = profile["tap_min"]
            args.tap_max = profile["tap_max"]
            args.chord_splay = profile["chord_splay"]
            args.slider_jitter = profile["slider_jitter"]
            args.late_lapse_rate = profile["late_lapse_rate"]
            args.late_lapse_range = profile["late_lapse_range"]
        elif args.profile in STANDARD_PROFILES:
            # Standard profile - store for later use
            args.standard_profile_data = STANDARD_PROFILES[args.profile]
        else:
            print(f"[main] Unknown profile: {args.profile}")
            sys.exit(1)

    # Validate and resolve mod
    speed_multiplier = 1.0
    if args.mod:
        if args.mod not in MODS:
            print(f"[main] Unknown mod: {args.mod}")
            print(f"[main] Available mods: {', '.join(sorted(MODS.keys()))}")
            sys.exit(1)
        speed_multiplier = MODS[args.mod]["speed"]
        mod_name = MODS[args.mod]["name"]
        print(f"[main] Mod: {mod_name}", end="")
        if speed_multiplier != 1.0:
            print(f" ({speed_multiplier}x speed)")
        else:
            print()

    if args.robot:
        args.stddev = 0
        args.mean = 0
        args.chord_splay = 0
        args.slider_jitter = 0
        args.late_lapse_rate = 0.0
        args.tap_min = args.tap_max = 20

    print("=" * 50)
    print("  osu! mania Autoplayer  (memory mode)")
    print("=" * 50)
    print()

    mem = OsuMemory()
    if not mem.connect():
        sys.exit(1)

    if args.robot:
        print("\n[main] ROBOT MODE - perfect timing\n")
    elif args.profile:
        print(f"\n[main] Profile: {args.profile.upper()}\n")
    else:
        lapse_min, lapse_max = args.late_lapse_range
        print(
            f"\n[main] humanize:  stddev={args.stddev}ms  mean={args.mean:+d}ms  "
            f"tap=[{args.tap_min},{args.tap_max}]ms  "
            f"splay=+/-{args.chord_splay}ms  slider_stddev={args.slider_jitter}ms  "
            f"late-lapse={args.late_lapse_rate:.0%}@[{lapse_min},{lapse_max}]ms\n"
        )

    print("Ready. Start a map in osu! - autoplay begins automatically.")
    print("Press Ctrl+C to quit.\n")

    try:
        # Use user-specified mode (no auto-detection)
        mode = args.mode
        print(f"[main] Mode: {mode}\n")

        while True:
            # Wait for a map to start
            while not mem.is_playing():
                time.sleep(0.25)

            # Read from memory based on user-specified mode
            if mode == "standard":
                # Parse .osu file instead of reading from memory (more reliable)
                parsed_objects = []
                map_file = ""

                if args.map:
                    # Use specified map file
                    if os.path.exists(args.map):
                        parsed_objects = parse_osu_file(args.map)
                        map_file = args.map
                    else:
                        print(f"[main] Map file not found: {args.map}")
                        time.sleep(1.0)
                        continue
                else:
                    # Auto-detect via window title (works with lazer)
                    detected_file = get_current_beatmap_file("D:\\gms\\osu!\\Songs")
                    if detected_file:
                        if get_game_mode(detected_file) != "standard":
                            print(f"[main] Map is not standard mode, waiting...")
                            time.sleep(1.0)
                            continue
                        parsed_objects = parse_osu_file(detected_file)
                        map_file = detected_file

                if not parsed_objects:
                    print("[main] No standard mode map detected - waiting...")
                    print("[main] Tip: Make sure osu! is showing a standard map, or use --map")
                    time.sleep(1.0)
                    continue

                print(f"[main] Loaded map: {os.path.basename(map_file)}")
                print(f"[main] {len(parsed_objects)} standard objects")

                # Convert OsuHitObject to HitObjectStandard
                # For sliders, we need to get end times - read from memory
                objects: List[HitObjectStandard] = []
                for pobj in parsed_objects:
                    # Start with just the parsed data
                    obj = HitObjectStandard(
                        start_time=pobj.time,
                        end_time=pobj.time,  # Will update for sliders
                        x=pobj.x,
                        y=pobj.y,
                        kind=pobj.kind,
                    )
                    objects.append(obj)

                # Create InputSimulator for standard mode
                sim = InputSimulator(key_count=4, mode="standard")

                # Get standard profile parameters (or use defaults)
                if hasattr(args, 'standard_profile_data'):
                    profile_data = args.standard_profile_data
                    click_stddev = profile_data["click_stddev"]
                    click_mean = profile_data["click_mean"]
                    aim_accuracy = profile_data["aim_accuracy_px"]
                    late_lapse_rate = profile_data["late_lapse_rate"]
                else:
                    # Defaults
                    click_stddev = 3
                    click_mean = -1
                    aim_accuracy = 5
                    late_lapse_rate = 0.02

                # Humanize standard hit objects
                humanize_standard(
                    objects,
                    click_stddev_ms=click_stddev,
                    click_mean_ms=click_mean,
                    late_lapse_rate=late_lapse_rate,
                )

                # Generate standard actions
                actions = to_actions_standard(
                    objects,
                    offset_ms=args.offset,
                    speed_multiplier=speed_multiplier,
                    aim_accuracy_px=aim_accuracy,
                )

                print(f"[main] Ready to play {len(actions)} actions")
                # Auto-detect when gameplay starts via CPU monitoring
                if wait_for_gameplay_start(timeout=60.0):
                    mem.reset_play_clock()  # Sync clock to gameplay start
                    play(mem, actions, sim, mode="standard")
                else:
                    print("[main] No gameplay detected, skipping...")
                print("[main] Map ended.\n")
                time.sleep(1.0)

            else:  # mania mode (default) - HYBRID: parse .osu file, use memory only for timing
                # Parse .osu file for mania mode
                parsed_objects = []
                map_file = ""

                if args.map:
                    # Use specified map file
                    if os.path.exists(args.map):
                        parsed_objects = parse_osu_file(args.map, mode="mania")
                        map_file = args.map
                    else:
                        print(f"[main] Map file not found: {args.map}")
                        time.sleep(1.0)
                        continue
                else:
                    # Auto-detect via window title (works with lazer)
                    detected_file = get_current_beatmap_file("D:\\gms\\osu!\\Songs")
                    if detected_file:
                        if get_game_mode(detected_file) != "mania":
                            print(f"[main] Map is not mania mode, waiting...")
                            time.sleep(1.0)
                            continue
                        parsed_objects = parse_osu_file(detected_file, mode="mania")
                        map_file = detected_file

                if not parsed_objects:
                    print("[main] No mania map detected - waiting...")
                    print("[main] Tip: Make sure osu! is showing a mania map, or use --map")
                    time.sleep(1.0)
                    continue

                print(f"[main] Loaded map: {os.path.basename(map_file)}")

                # Convert OsuHitObject to HitObject for mania
                objects: List[HitObject] = []
                for pobj in parsed_objects:
                    # x field contains column index for mania
                    column = int(pobj.x)
                    obj = HitObject(
                        start_time=pobj.time,
                        end_time=pobj.time,  # Will be updated for sliders
                        column=column,
                    )
                    objects.append(obj)

                # Derive column count from the hit-object data
                col_count = max((o.column for o in objects), default=3) + 1

                col_dist = {}
                for o in objects:
                    col_dist[o.column] = col_dist.get(o.column, 0) + 1
                print(
                    f"[main] {col_count}K mode  |  {len(objects)} objects  |  "
                    f"distribution={sorted(col_dist.items())}"
                )

                # Resolve key layout
                if args.keys:
                    if len(args.keys) != col_count:
                        print(f"[main] --keys has {len(args.keys)} entries but map is {col_count}K")
                        time.sleep(1.0)
                        continue
                    keys = args.keys
                else:
                    keys = DEFAULT_KEYS.get(col_count)
                    if not keys:
                        print(f"[main] No built-in key map for {col_count}K - use --keys")
                        time.sleep(1.0)
                        continue

                sim = InputSimulator(key_count=col_count, custom_keys=keys, mode="mania")

                print(
                    f"[main] {col_count}K  |  {len(objects)} objects  |  "
                    f"keys={keys}  |  offset={args.offset:+d}ms"
                )

                humanize(
                    objects,
                    timing_stddev_ms         = args.stddev,
                    timing_mean_ms           = args.mean,
                    chord_splay_ms           = args.chord_splay,
                    slider_release_stddev_ms = args.slider_jitter,
                    late_lapse_rate          = args.late_lapse_rate,
                    late_lapse_min_ms        = args.late_lapse_range[0],
                    late_lapse_max_ms        = args.late_lapse_range[1],
                )

                actions = to_actions(
                    objects,
                    tap_min_ms        = args.tap_min,
                    tap_max_ms        = args.tap_max,
                    offset_ms         = args.offset,
                    speed_multiplier  = speed_multiplier,
                )

                # Add break taps if enabled
                if args.break_tap_interval > 0:
                    actions_before = len(actions)
                    add_break_taps(
                        objects,
                        actions,
                        col_count,
                        tap_interval_ms = args.break_tap_interval,
                        min_break_ms    = DEFAULT_BREAK_MIN_GAP,
                        tap_min_ms      = args.tap_min,
                        tap_max_ms      = args.tap_max,
                        debug           = True,
                    )
                    actions.sort()  # Re-sort since we added new actions
                    actions_after = len(actions)
                    print(f"[main] break-taps:  {actions_before} actions -> {actions_after} actions")

                print(f"[main] Ready to play {len(actions)} actions")
                # Auto-detect when gameplay starts via CPU monitoring
                if wait_for_gameplay_start(timeout=60.0):
                    mem.reset_play_clock()  # Sync clock to gameplay start
                    play(mem, actions, sim, mode="mania")
                else:
                    print("[main] No gameplay detected, skipping...")

                print("[main] Map ended.\n")
                time.sleep(1.0)

    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
