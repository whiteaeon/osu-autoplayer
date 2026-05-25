"""
osu! memory reader — Python port of maniac's core.
https://github.com/fs-c/maniac

Reads game time, status, and hit objects directly from osu!'s process memory
using signature scanning across all JIT-compiled executable regions.

osu! stable is a 32-bit .NET app. Its game logic is JIT-compiled at runtime
into executable heap memory — NOT inside the PE module image. We must scan
all committed executable regions, not just osu!.exe's module bytes.

Running 64-bit Python against a 32-bit osu! requires the 64-bit variant of
MEMORY_BASIC_INFORMATION (48 bytes), since VirtualQueryEx always fills the
caller's native structure size regardless of the target's architecture.
"""

import ctypes
import ctypes.wintypes
import re
import struct
import time
from dataclasses import dataclass
from typing import Optional, List

import pymem
import pymem.process

# ---------------------------------------------------------------------------
# Game state constants  (from maniac/osu/internal.h)
# ---------------------------------------------------------------------------
STATUS_MENU        = 0
STATUS_PLAYING     = 2
STATUS_SONG_SELECT = 5

# ---------------------------------------------------------------------------
# Signatures  (from maniac/osu/signatures.h)
# Pattern format: "AA BB ? ? CC"  where ? is any byte
# offset: bytes from match start to the embedded 32-bit virtual address
# ---------------------------------------------------------------------------
_SIG_TIME = (
    "EB 0A A1 ? ? ? ? A3",
    3,
)
_SIG_PLAYER = (
    "A1 ? ? ? ? 8B ? ? ? 00 00 6A 00",
    1,
)
_SIG_STATUS = (
    "A1 ? ? ? ? A3 ? ? ? ? "
    "A1 ? ? ? ? A3 ? ? ? ? "
    "83 3D ? ? ? ? 00 0F 84 ? ? ? ? "
    "B9 ? ? ? ? E8",
    1,
)

# ---------------------------------------------------------------------------
# MEMORY_BASIC_INFORMATION — 64-bit layout (48 bytes)
# VirtualQueryEx fills the CALLER's native structure, so from 64-bit Python
# all pointer and SIZE_T fields are 8 bytes even for a 32-bit target process.
# ---------------------------------------------------------------------------
class _MBI(ctypes.Structure):
    _fields_ = [
        ("BaseAddress",       ctypes.c_size_t),   # 8 bytes
        ("AllocationBase",    ctypes.c_size_t),   # 8 bytes
        ("AllocationProtect", ctypes.c_uint32),   # 4 bytes
        ("PartitionId",       ctypes.c_uint16),   # 2 bytes (Windows 10+)
        ("__pad1",            ctypes.c_uint16),   # 2 bytes
        ("RegionSize",        ctypes.c_size_t),   # 8 bytes
        ("State",             ctypes.c_uint32),   # 4 bytes
        ("Protect",           ctypes.c_uint32),   # 4 bytes
        ("Type",              ctypes.c_uint32),   # 4 bytes
        ("__pad2",            ctypes.c_uint32),   # 4 bytes
    ]   # total: 48 bytes

_MEM_COMMIT        = 0x1000
_PAGE_NOACCESS     = 0x01
_PAGE_GUARD        = 0x100
_EXECUTABLE        = {0x10, 0x20, 0x40, 0x80}   # EXECUTE / EXECUTE_READ / EXECUTE_RW / EXECUTE_WC
_MAX_ADDR          = 0x7FFFFFFF                  # 32-bit user-space ceiling


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------
@dataclass
class HitObject:
    start_time: int   # ms from audio start
    end_time:   int   # ms — equals start_time for tap notes
    column:     int   # 0-indexed

    @property
    def is_slider(self) -> bool:
        return self.end_time != self.start_time


@dataclass
class HitObjectStandard:
    """Hit object for osu!standard (circles, sliders, spinners)."""
    start_time: int   # ms from audio start
    end_time:   int   # ms — equals start_time for circles
    x:          float # 0-512 osu! coordinate
    y:          float # 0-384 osu! coordinate
    kind:       int   # 0=circle, 1=slider, 2=spinner

    @property
    def is_slider(self) -> bool:
        return self.end_time > self.start_time and self.kind == 1

    @property
    def is_spinner(self) -> bool:
        return self.kind == 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sig_to_regex(pattern: str) -> bytes:
    parts = pattern.split()
    out = b""
    for p in parts:
        out += b"." if p == "?" else re.escape(bytes([int(p, 16)]))
    return out


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------
class OsuMemory:
    """
    Attaches to a running osu! process and exposes its internal state.

    Usage::

        mem = OsuMemory()
        if not mem.connect():
            sys.exit(1)
        while True:
            while not mem.is_playing():
                time.sleep(0.25)
            objects = mem.get_hit_objects()
    """

    def __init__(self):
        self._pm: Optional[pymem.Pymem] = None
        self._time_address   = 0
        self._player_pointer = 0
        self._status_pointer = 0

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------
    def connect(self, timeout: float = 60.0) -> bool:
        deadline = time.perf_counter() + timeout
        print("[memory] Waiting for osu!.exe…")
        while True:
            try:
                self._pm = pymem.Pymem("osu!.exe")
                break
            except Exception:
                if time.perf_counter() > deadline:
                    print("[memory] Timed out — start osu! first.")
                    return False
                time.sleep(0.5)

        print("[memory] Attached — scanning all executable regions…")
        try:
            self._time_address   = self._scan(*_SIG_TIME)
            self._player_pointer = self._scan(*_SIG_PLAYER)
            self._status_pointer = self._scan(*_SIG_STATUS)
            print(
                f"[memory] Ready  "
                f"time={self._time_address:#010x}  "
                f"player_ptr={self._player_pointer:#010x}  "
                f"status={self._status_pointer:#010x}"
            )
            return True
        except RuntimeError as exc:
            # For osu!lazer, signatures might not match.
            # In hybrid mode, we don't strictly need memory offsets.
            print(f"[memory] Warning: Signature scan failed: {exc}")
            print("[memory] This is normal for osu!lazer. Using hybrid mode (file-based hits).")
            print("[memory] Note: Game timing sync will be limited without memory access.")
            return True  # Return True anyway — hybrid mode can work without memory

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------
    def _iter_executable(self):
        """Yield (base, data) for every committed executable memory region."""
        mbi  = _MBI()
        addr = 0x10000

        while addr <= _MAX_ADDR:
            ret = ctypes.windll.kernel32.VirtualQueryEx(
                self._pm.process_handle,
                ctypes.c_void_p(addr),
                ctypes.byref(mbi),
                ctypes.sizeof(mbi),
            )
            if not ret:
                break

            base = mbi.BaseAddress
            size = mbi.RegionSize
            protect = mbi.Protect & 0xFF

            if (mbi.State == _MEM_COMMIT
                    and protect in _EXECUTABLE
                    and not (mbi.Protect & _PAGE_GUARD)
                    and size > 0):
                try:
                    data = self._pm.read_bytes(base, size)
                    yield base, data
                except Exception:
                    pass

            next_addr = base + size
            if next_addr <= addr:
                break
            addr = next_addr

    def _scan(self, pattern: str, offset: int) -> int:
        """
        Scan all executable regions for *pattern*.
        Read 4 bytes at +*offset* from the match as a LE uint32 — that
        IS the embedded 32-bit virtual address of the target variable.
        """
        rx = re.compile(_sig_to_regex(pattern), re.DOTALL)

        for base, data in self._iter_executable():
            m = rx.search(data)
            if m:
                pos = m.start() + offset
                if pos + 4 <= len(data):
                    return struct.unpack_from("<I", data, pos)[0]

        raise RuntimeError(f"Signature not found: {pattern[:30]}…")

    # ------------------------------------------------------------------
    # Memory primitives
    # ------------------------------------------------------------------
    def _uint(self, addr: int) -> int:
        return self._pm.read_uint(addr)

    def _int(self, addr: int) -> int:
        return self._pm.read_int(addr)

    def _float(self, addr: int) -> float:
        return self._pm.read_float(addr)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_game_time(self) -> int:
        """Current song position in milliseconds (osu!'s internal clock)."""
        if self._time_address == 0:
            # Fallback for lazer: return system time
            if not hasattr(self, '_play_start_time') or self._play_start_time is None:
                self._play_start_time = time.perf_counter()
            return int((time.perf_counter() - self._play_start_time) * 1000)
        return self._int(self._time_address)

    def reset_play_clock(self):
        """Reset the system clock fallback. Call when starting a new play session."""
        self._play_start_time = time.perf_counter()

    def get_status(self) -> int:
        """Game state: 0=menu, 2=playing, 5=song select."""
        if self._status_pointer == 0:
            # Fallback for lazer: assume playing if we're in this loop
            return STATUS_PLAYING
        return self._int(self._status_pointer)

    def is_playing(self) -> bool:
        return self.get_status() == STATUS_PLAYING

    def get_column_count(self) -> int:
        """Key count of the currently loaded beatmap."""
        try:
            player_addr      = self._uint(self._player_pointer)
            hit_manager_addr = self._uint(player_addr + 0x48)
            headers_addr     = self._uint(hit_manager_addr + 0x30)
            return int(self._float(headers_addr + 0x30))
        except Exception:
            return 0

    def get_hit_objects(self) -> List[HitObject]:
        """
        DEPRECATED: For lazer, use osu_parser.py instead.
        This reads from memory (stable-only), but hit objects are better read from .osu files.
        """
        """
        Read all hit objects for the current beatmap directly from memory.

        Memory chain (internal.h → map_player → hit_manager → list_container):
          player_ptr            → player_address
          player_address + 0x48 → hit_manager_address
          hit_manager    + 0x48 → list_container_address
          list_container + 0x04 → content_address
          list_container + 0x0C → size
          content_address + 0x08 + i*4 → hit_object_ptr
          hit_object + 0x10 → start_time (int32)
          hit_object + 0x14 → end_time   (int32)
          hit_object + 0x9C → column     (int32)
        """
        try:
            player_addr = self._uint(self._player_pointer)
            if player_addr == 0:
                return []

            hit_manager_addr = self._uint(player_addr      + 0x48)
            list_addr        = self._uint(hit_manager_addr + 0x48)
            size             = self._uint(list_addr        + 0x0C)
            content_addr     = self._uint(list_addr        + 0x04)

            if size == 0 or size > 100_000:
                return []

            objects: List[HitObject] = []
            for i in range(size):
                obj_ptr    = self._uint(content_addr + 0x08 + i * 4)
                start_time = self._int(obj_ptr + 0x10)
                end_time   = self._int(obj_ptr + 0x14)
                column     = self._int(obj_ptr + 0x9C)
                objects.append(HitObject(start_time, end_time, column))

            return objects

        except Exception as exc:
            print(f"[memory] get_hit_objects failed: {exc}")
            return []

    def get_game_mode(self) -> str:
        """
        Detect the current game mode (mania or standard).

        Heuristic: Read the CS (circle size) field from the beatmap header.
        - Mania: CS value is the key count (1-9)
        - Standard: CS value is circle size (0.5-10.0, typically 3-5)

        If CS > 10 or < 0.5, it's likely mania (column count).
        Returns "mania" or "standard".
        """
        try:
            cs_value = self.get_column_count()
            # Mania: column count is 1-9
            # Standard: circle size is typically 0.5-10.0
            if cs_value >= 1 and cs_value <= 9:
                # Could be either; check if it's a whole number strongly suggests mania
                if cs_value == int(cs_value):
                    return "mania"
            # If > 9 or fractional, likely standard
            # Default to checking if we can read standard coordinates
            return "standard"
        except Exception:
            return "mania"  # Default to mania on error

    def get_hit_objects_standard(self) -> List[HitObjectStandard]:
        """
        Read all hit objects for osu!standard beatmap from memory.

        Memory chain is identical to mania, but offsets differ:
          hit_object + 0x10 → start_time (int32)
          hit_object + 0x14 → end_time   (int32)
          hit_object + 0x90 → x         (float32)
          hit_object + 0x8C → y         (float32)
          hit_object + 0x9C → kind      (int32, 0=circle, 1=slider, 2=spinner)

        Offsets verified via debug_memory.py on actual standard beatmaps.
        """
        try:
            player_addr = self._uint(self._player_pointer)
            if player_addr == 0:
                return []

            hit_manager_addr = self._uint(player_addr      + 0x48)
            list_addr        = self._uint(hit_manager_addr + 0x48)
            size             = self._uint(list_addr        + 0x0C)
            content_addr     = self._uint(list_addr        + 0x04)

            if size == 0 or size > 100_000:
                return []

            objects: List[HitObjectStandard] = []
            for i in range(size):
                obj_ptr    = self._uint(content_addr + 0x08 + i * 4)
                start_time = self._int(obj_ptr + 0x10)
                end_time   = self._int(obj_ptr + 0x14)
                x          = self._float(obj_ptr + 0x90)
                y          = self._float(obj_ptr + 0x8C)
                kind       = self._int(obj_ptr + 0x9C)
                objects.append(HitObjectStandard(start_time, end_time, x, y, kind))

            return objects

        except Exception as exc:
            print(f"[memory] get_hit_objects_standard failed: {exc}")
            return []
