"""
Memory debugger for osu! standard mode.
Shows hit object data at different offsets to help identify correct memory layout.
"""

import struct
import time
from osu_memory import OsuMemory, _MBI, _MEM_COMMIT, _EXECUTABLE, _MAX_ADDR
import ctypes

def main():
    mem = OsuMemory()
    if not mem.connect():
        print("[debug] Failed to connect to osu!")
        return

    print("\n[debug] Connected to osu!. Start a standard map and press play.")
    print("[debug] This will show hit object memory data to help identify offsets.\n")

    time.sleep(2)

    try:
        # Get player and hit manager addresses
        player_addr = mem._uint(mem._player_pointer)
        if player_addr == 0:
            print("[debug] Player not loaded")
            return

        hit_manager_addr = mem._uint(player_addr + 0x48)
        list_addr = mem._uint(hit_manager_addr + 0x48)
        size = mem._uint(list_addr + 0x0C)
        content_addr = mem._uint(list_addr + 0x04)

        print(f"[debug] Player: {player_addr:#010x}")
        print(f"[debug] HitManager: {hit_manager_addr:#010x}")
        print(f"[debug] ListAddr: {list_addr:#010x}")
        print(f"[debug] ContentAddr: {content_addr:#010x}")
        print(f"[debug] HitObject count: {size}\n")

        if size == 0 or size > 100_000:
            print("[debug] Invalid object count")
            return

        # Examine first few hit objects - check kind values
        print("[debug] First 10 hit objects (checking kind field offsets):\n")

        # First, show current kind offset
        print("=== Current offsets: @+90 (x), @+8C (y), @+9C (kind) ===")
        print(f"{'Idx':<4} {'@+90(x)':<12} {'@+8C(y)':<12} {'@+9C(kind)':<8}")
        print("-" * 45)

        for i in range(min(10, size)):
            obj_ptr = mem._uint(content_addr + 0x08 + i * 4)
            if obj_ptr == 0:
                continue
            try:
                x = mem._float(obj_ptr + 0x90)
                y = mem._float(obj_ptr + 0x8C)
                kind = mem._int(obj_ptr + 0x9C)
                print(f"{i:<4} {x:<12.2f} {y:<12.2f} {kind:<8}")
            except Exception as e:
                print(f"{i:<4} ERROR: {e}")

        # Try alternative offsets for kind
        print("\n=== Trying alternative kind offsets (x at +90, y at +8C) ===")
        for kind_offset in [0x94, 0x98, 0x9C, 0xA0, 0xA4, 0xA8, 0xAC]:
            print(f"\nOffset +{kind_offset:#04x} (kind):")
            print(f"{'Idx':<4} {'kind':<8}")
            print("-" * 15)
            for i in range(min(10, size)):
                obj_ptr = mem._uint(content_addr + 0x08 + i * 4)
                if obj_ptr == 0:
                    continue
                try:
                    kind = mem._int(obj_ptr + kind_offset)
                    # Check if kind is 0, 1, or 2
                    validity = "✓" if kind in [0, 1, 2] else "✗"
                    print(f"{i:<4} {kind:<8} {validity}")
                except Exception as e:
                    print(f"{i:<4} ERROR")

        print("\n[debug] If kind values are 0 (circle), 1 (slider), or 2 (spinner), offset is correct!")
        print("[debug] If most values are garbage numbers, the +0x9C offset needs adjustment.\n")

    except Exception as e:
        print(f"[debug] Error: {e}")

if __name__ == "__main__":
    main()
