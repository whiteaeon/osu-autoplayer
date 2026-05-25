"""
osu!lazer map detection via window title and storage scanning.

Lazer stores beatmaps as hashed files in AppData\Roaming\osu\files\
The window title shows the current map: "osu! - Artist - Title [Difficulty]"
"""

import os
import re
import ctypes
from ctypes import wintypes
from typing import Optional, Tuple
import psutil


# Windows API for getting window titles
EnumWindows = ctypes.windll.user32.EnumWindows
GetWindowText = ctypes.windll.user32.GetWindowTextW
GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)


def get_osu_window_title() -> Optional[str]:
    """Get the title of the osu! window. Returns None if not found."""
    osu_pid = None
    for proc in psutil.process_iter(['name', 'pid']):
        if 'osu' in proc.info['name'].lower():
            osu_pid = proc.info['pid']
            break

    if not osu_pid:
        return None

    title = [None]  # Use list for closure

    def foreach_window(hwnd, lParam):
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == osu_pid:
            length = GetWindowTextLength(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                GetWindowText(hwnd, buf, length + 1)
                if buf.value and buf.value.startswith('osu!'):
                    title[0] = buf.value
                    return False  # Stop enumeration
        return True

    EnumWindows(EnumWindowsProc(foreach_window), 0)
    return title[0]


def parse_window_title(title: str) -> Optional[Tuple[str, str, str]]:
    """
    Parse osu! window title.
    Format: "osu! - Artist - Title [Difficulty]"
    Returns (artist, title, difficulty) or None.
    """
    if not title or not title.startswith('osu!'):
        return None

    # Remove "osu! - " prefix
    content = title[len('osu!'):].strip()
    if content.startswith('-'):
        content = content[1:].strip()

    # Extract difficulty in brackets
    diff_match = re.search(r'\[([^\]]+)\]\s*$', content)
    if not diff_match:
        return None

    difficulty = diff_match.group(1)
    main_part = content[:diff_match.start()].strip()

    # Split artist - title
    parts = main_part.rsplit(' - ', 1)
    if len(parts) == 2:
        artist, song_title = parts
        return (artist.strip(), song_title.strip(), difficulty.strip())

    return None


def find_lazer_beatmap(title_info: Tuple[str, str, str]) -> Optional[str]:
    """
    Find the .osu file matching the given title info in lazer's storage.
    Returns the file path or None.
    """
    artist, title, difficulty = title_info
    lazer_files_dir = os.path.expandvars(r"%APPDATA%\osu\files")

    if not os.path.exists(lazer_files_dir):
        return None

    # Scan all files in lazer's storage looking for matching .osu content
    for root, dirs, files in os.walk(lazer_files_dir):
        for file in files:
            full_path = os.path.join(root, file)
            try:
                with open(full_path, 'rb') as f:
                    header = f.read(2048)

                # Skip non-.osu files quickly
                if b'osu file format' not in header:
                    continue

                # Decode and check metadata
                try:
                    text = header.decode('utf-8', errors='ignore')
                except:
                    continue

                # Check if metadata matches
                title_match = re.search(r'Title\s*:\s*(.+)', text)
                artist_match = re.search(r'Artist\s*:\s*(.+)', text)
                version_match = re.search(r'Version\s*:\s*(.+)', text)

                if title_match and artist_match and version_match:
                    t = title_match.group(1).strip()
                    a = artist_match.group(1).strip()
                    v = version_match.group(1).strip()
                    if t == title and a == artist and v == difficulty:
                        return full_path
            except:
                pass

    return None


def find_stable_beatmap(title_info: Tuple[str, str, str], songs_dir: str) -> Optional[str]:
    """Find matching .osu file in stable's Songs directory."""
    artist, title, difficulty = title_info

    if not os.path.exists(songs_dir):
        return None

    for root, dirs, files in os.walk(songs_dir):
        for file in files:
            if not file.endswith('.osu'):
                continue
            # Quick filter by filename
            if difficulty not in file:
                continue

            full_path = os.path.join(root, file)
            try:
                with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read(2048)

                title_match = re.search(r'Title\s*:\s*(.+)', text)
                artist_match = re.search(r'Artist\s*:\s*(.+)', text)
                version_match = re.search(r'Version\s*:\s*(.+)', text)

                if title_match and artist_match and version_match:
                    t = title_match.group(1).strip()
                    a = artist_match.group(1).strip()
                    v = version_match.group(1).strip()
                    if t == title and a == artist and v == difficulty:
                        return full_path
            except:
                pass

    return None


def get_current_beatmap_file(stable_songs_dir: str = None) -> Optional[str]:
    """
    Get the .osu file path of the currently active osu! beatmap.
    Tries lazer storage first, then stable songs directory.
    """
    title = get_osu_window_title()
    if not title:
        return None

    title_info = parse_window_title(title)
    if not title_info:
        return None

    print(f"[lazer_detect] Current map: {title_info[0]} - {title_info[1]} [{title_info[2]}]")

    # Try lazer first
    path = find_lazer_beatmap(title_info)
    if path:
        print(f"[lazer_detect] Found in lazer storage: {path}")
        return path

    # Try stable songs folder
    if stable_songs_dir:
        path = find_stable_beatmap(title_info, stable_songs_dir)
        if path:
            print(f"[lazer_detect] Found in stable songs: {path}")
            return path

    print("[lazer_detect] Beatmap file not found in any location")
    return None


def wait_for_gameplay_start(timeout: float = 30.0) -> bool:
    """
    Wait for osu! to enter gameplay state by detecting CPU usage spike.
    Returns True if gameplay detected, False on timeout.

    Lazer uses more CPU during gameplay vs menu/select screens.
    """
    osu_proc = None
    for proc in psutil.process_iter(['name', 'pid']):
        if 'osu' in proc.info['name'].lower():
            osu_proc = psutil.Process(proc.info['pid'])
            break

    if not osu_proc:
        return False

    # Baseline CPU usage from current state (presumably menu/select)
    baseline_samples = []
    for _ in range(5):
        cpu = osu_proc.cpu_percent(interval=0.2)
        baseline_samples.append(cpu)

    baseline = sum(baseline_samples) / len(baseline_samples)
    threshold = baseline + 15.0  # Gameplay typically uses 15%+ more CPU
    print(f"[lazer_detect] Baseline CPU: {baseline:.1f}%, threshold: {threshold:.1f}%")
    print(f"[lazer_detect] Waiting for gameplay (press PLAY in osu! now)...")

    import time
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        cpu = osu_proc.cpu_percent(interval=0.1)
        if cpu > threshold:
            print(f"[lazer_detect] Gameplay detected! (CPU: {cpu:.1f}%)")
            return True

    print("[lazer_detect] Timeout waiting for gameplay")
    return False


if __name__ == '__main__':
    # Test
    print("Window title:", get_osu_window_title())
    path = get_current_beatmap_file(r"D:\gms\osu!\Songs")
    if path:
        print(f"Found beatmap: {path}")
    else:
        print("No beatmap found")
