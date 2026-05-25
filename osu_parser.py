"""
Parse osu! .osu beatmap files to extract hit objects for standard mode.

The .osu file format is a text-based format. The [HitObjects] section contains:
  x,y,time,type,hitSound,objectParams

where:
  x, y: coordinates (0-512, 0-384)
  time: milliseconds from start
  type: 1=circle, 2=slider, 8=spinner (use bit flags)
  objectParams: optional slider curve data
"""

import re
import os
from typing import List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class OsuHitObject:
    """A hit object from a parsed .osu file."""
    x: float
    y: float
    time: int  # milliseconds
    kind: int  # 0=circle, 1=slider, 2=spinner
    duration: int = 0  # for sliders/spinners


def find_current_map_file(songs_dir: str) -> Optional[str]:
    """
    Find the currently playing .osu file by checking access time.
    When osu! loads a map, it reads the .osu file, updating its access time.
    """
    try:
        osu_files = []
        for root, dirs, files in os.walk(songs_dir):
            for file in files:
                if file.endswith(".osu"):
                    full_path = os.path.join(root, file)
                    # Use access time (when file was last read)
                    atime = os.path.getatime(full_path)
                    osu_files.append((atime, full_path))

        if not osu_files:
            return None

        # Return the most recently accessed .osu file
        osu_files.sort(reverse=True)
        return osu_files[0][1]
    except Exception as e:
        print(f"[osu_parser] Error finding map file: {e}")
        return None


def get_game_mode(filepath: str) -> str:
    """Extract the game mode from the .osu file.
    Returns: 'standard', 'taiko', 'catch', 'mania'
    """
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Find Mode in [General] section
        match = re.search(r'Mode\s*:\s*(\d+)', content)
        if match:
            mode_id = int(match.group(1))
            modes = {0: "standard", 1: "taiko", 2: "catch", 3: "mania"}
            return modes.get(mode_id, "standard")
    except:
        pass
    return "standard"


def get_key_count(filepath: str) -> int:
    """Extract the key count from the Difficulty section of a mania beatmap."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Find CircleSize (CS) - for mania, this is the key count
        match = re.search(r'CircleSize\s*:\s*(\d+(?:\.\d+)?)', content)
        if match:
            cs = float(match.group(1))
            return int(cs)
    except:
        pass

    return 4  # Default to 4K if not found


def parse_osu_file(filepath: str, mode: str = "standard") -> List[OsuHitObject]:
    """
    Parse a .osu file and extract hit objects.

    For standard mode: Returns x, y coordinates (0-512, 0-384)
    For mania mode: Returns column index and time
    """
    objects = []

    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except Exception as e:
        print(f"[osu_parser] Error reading {filepath}: {e}")
        return []

    # Get key count for mania mode
    key_count = get_key_count(filepath) if mode == "mania" else 0

    # Find the [HitObjects] section
    match = re.search(r'\[HitObjects\](.*?)(?:\[|$)', content, re.DOTALL | re.IGNORECASE)
    if not match:
        print(f"[osu_parser] No [HitObjects] section found in {filepath}")
        return []

    hit_objects_section = match.group(1).strip()

    for line in hit_objects_section.split('\n'):
        line = line.strip()
        if not line or line.startswith('//'):
            continue

        try:
            parts = line.split(',')
            if len(parts) < 4:
                continue

            x = float(parts[0])
            y = float(parts[1])
            time = int(parts[2])
            type_flags = int(parts[3])

            # Determine object type from flags
            # Bit 0 (1): circle
            # Bit 1 (2): slider
            # Bit 3 (8): spinner
            if type_flags & 8:  # spinner
                kind = 2
            elif type_flags & 2:  # slider
                kind = 1
            elif type_flags & 1:  # circle
                kind = 0
            else:
                continue

            # For mania mode, convert x coordinate to column
            if mode == "mania":
                # Mania column ranges: 0-51 = col0, 52-103 = col1, etc.
                # 512 / key_count pixels per column
                pixels_per_column = 512.0 / key_count if key_count > 0 else 512.0
                column = int(x / pixels_per_column)
                column = max(0, min(column, key_count - 1))  # Clamp to valid range

                # For mania, store column in x field (will be used as HitObject.column)
                obj = OsuHitObject(x=float(column), y=y, time=time, kind=kind, duration=0)
            else:
                # Standard mode: keep x, y as coordinates
                obj = OsuHitObject(x=x, y=y, time=time, kind=kind, duration=0)

            objects.append(obj)

        except (ValueError, IndexError) as e:
            print(f"[osu_parser] Error parsing line: {line[:50]}... ({e})")
            continue

    return objects


def get_hit_objects_from_map(songs_dir: str) -> Tuple[List[OsuHitObject], str]:
    """
    Get hit objects from the currently playing map.

    Returns:
        (list of OsuHitObject, filepath of the map)
    """
    map_file = find_current_map_file(songs_dir)
    if not map_file:
        return [], ""

    objects = parse_osu_file(map_file)
    return objects, map_file
