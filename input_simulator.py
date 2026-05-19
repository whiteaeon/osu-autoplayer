"""
Input simulation for osu! mania autoplayer.

Maps mania columns to keyboard keys and simulates key presses
using pydirectinput for low-latency, reliable input.
"""

import time
from typing import Optional

try:
    import pydirectinput
    _HAS_PYDIRECTINPUT = True
except ImportError:
    _HAS_PYDIRECTINPUT = False

# Default key mappings for various mania modes
# Keys are chosen to match standard osu! mania layouts
KEY_MAPS: dict[int, list[str]] = {
    1: ["space"],
    2: ["d", "k"],
    3: ["d", "space", "k"],
    4: ["d", "f", "j", "k"],
    5: ["d", "f", "space", "j", "k"],
    6: ["s", "d", "f", "j", "k", "l"],
    7: ["s", "d", "f", "space", "j", "k", "l"],
    8: ["s", "d", "f", "v", "b", "j", "k", "l"],
    9: ["s", "d", "f", "v", "space", "b", "j", "k", "l"],
}


class InputSimulator:
    """Simulates keyboard input for osu! mania and mouse input for osu! standard."""

    def __init__(self, key_count: int = 4, custom_keys: Optional[list[str]] = None, mode: str = "mania"):
        if not _HAS_PYDIRECTINPUT:
            raise ImportError(
                "pydirectinput is required. Install with: pip install pydirectinput"
            )

        self.key_count = key_count
        self.mode = mode  # "mania" or "standard"

        if custom_keys:
            if len(custom_keys) != key_count:
                raise ValueError(
                    f"custom_keys length ({len(custom_keys)}) must match "
                    f"key_count ({key_count})"
                )
            self._key_map = [k.lower() for k in custom_keys]
        else:
            if key_count not in KEY_MAPS:
                supported = ", ".join(str(k) for k in sorted(KEY_MAPS.keys()))
                raise ValueError(
                    f"Unsupported key count: {key_count}. Supported: {supported}"
                )
            self._key_map = KEY_MAPS[key_count].copy()

        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False

    @property
    def key_map(self) -> list[str]:
        return self._key_map

    def get_key_for_column(self, column: int) -> str:
        """Get the keyboard key for a given mania column."""
        if column < 0 or column >= self.key_count:
            raise ValueError(
                f"Column {column} out of range for {self.key_count}K mode"
            )
        return self._key_map[column]

    def press_column(self, column: int):
        """Press the key for a specific column."""
        key = self.get_key_for_column(column)
        pydirectinput.keyDown(key)

    def release_column(self, column: int):
        """Release the key for a specific column."""
        key = self.get_key_for_column(column)
        pydirectinput.keyUp(key)

    def tap_column(self, column: int, hold_duration_s: float = 0.005):
        """Press and release a column key with a brief hold."""
        self.press_column(column)
        time.sleep(hold_duration_s)
        self.release_column(column)

    def get_column_from_key(self, key: str) -> Optional[int]:
        """Get the column index for a given keyboard key."""
        key = key.lower()
        try:
            return self._key_map.index(key)
        except ValueError:
            return None

    # -----------------------------------------------------------------------
    # Mouse input methods (for osu! standard)
    # -----------------------------------------------------------------------
    def move_cursor(self, x: float, y: float) -> None:
        """
        Move cursor to position (x, y) in game coordinates (0-512, 0-384).
        Converts to screen coordinates assuming 1920x1440 resolution.
        """
        screen_x, screen_y = self._game_to_screen_coords(x, y)
        # Debug: print first few moves
        import sys
        if not hasattr(sys, '_osu_move_count'):
            sys._osu_move_count = 0
        sys._osu_move_count += 1
        if sys._osu_move_count <= 5:
            print(f"[input] Move: game({x:.1f}, {y:.1f}) -> screen({screen_x}, {screen_y})")
        pydirectinput.moveTo(screen_x, screen_y, duration=0)

    def click(self) -> None:
        """Single mouse click (press and immediately release)."""
        pydirectinput.click()

    def mouse_down(self) -> None:
        """Press mouse button down (for slider holds)."""
        pydirectinput.mouseDown()

    def mouse_up(self) -> None:
        """Release mouse button."""
        pydirectinput.mouseUp()

    def _game_to_screen_coords(self, gx: float, gy: float) -> tuple[int, int]:
        """
        Convert osu! game coordinates (0-512, 0-384) to screen pixels.

        For fullscreen osu!, we need to know the actual monitor resolution.
        """
        # Try to get the primary monitor's actual resolution
        try:
            import ctypes

            # Get the monitor info for the primary display
            hdc = ctypes.windll.user32.GetDC(0)

            # HORZRES = physical width, VERTRES = physical height
            screen_width = ctypes.windll.gdi32.GetDeviceCaps(hdc, 8)    # HORZRES
            screen_height = ctypes.windll.gdi32.GetDeviceCaps(hdc, 10)   # VERTRES

            ctypes.windll.user32.ReleaseDC(0, hdc)

            if screen_width <= 0 or screen_height <= 0:
                raise Exception("Invalid resolution")
        except:
            # Fallback: use common resolution
            screen_width = 1920
            screen_height = 1200

        screen_x = int(gx * screen_width / 512)
        screen_y = int(gy * screen_height / 384)
        return (screen_x, screen_y)

    def __repr__(self) -> str:
        return f"InputSimulator({self.key_count}K, keys={self._key_map}, mode={self.mode})"
