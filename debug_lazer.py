"""
Memory debugger for osu!lazer.
Discovers memory offsets for hit objects, player state, and game time.

osu!lazer is a complete rewrite in C# with different memory layout than stable.
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

    print("\n[debug] Connected to osu!lazer. Start a map and press play.")
    print("[debug] This will help identify hit object memory offsets in lazer.\n")

    time.sleep(2)

    try:
        # Get player address
        player_addr = mem._uint(mem._player_pointer)
        if player_addr == 0:
            print("[debug] Player not loaded")
            return

        print(f"[debug] Player: {player_addr:#010x}")
        print(f"[debug] Scanning hit object structures...\n")

        # Try to find hit manager - lazer structure might be different
        # In stable it was: player + 0x48 -> hit_manager
        # Let's try similar offsets

        print("=== Trying hit manager at different offsets from player ===")
        for offset in [0x48, 0x50, 0x58, 0x60, 0x68, 0x70]:
            try:
                hit_manager_addr = mem._uint(player_addr + offset)
                if hit_manager_addr == 0 or hit_manager_addr > 0x7FFFFFFF:
                    continue
                print(f"Possible hit manager at player+{offset:#04x}: {hit_manager_addr:#010x}")
            except:
                pass

        # Try to find hit objects list
        # In stable: player + 0x48 -> hit_manager + 0x48 -> list_container
        # Let's scan more broadly

        print("\n=== Trying list container at different offsets ===")
        try:
            hit_manager_addr = mem._uint(player_addr + 0x48)
            if hit_manager_addr and hit_manager_addr < 0x7FFFFFFF:
                for offset in [0x40, 0x48, 0x50, 0x58, 0x60]:
                    try:
                        list_addr = mem._uint(hit_manager_addr + offset)
                        if list_addr == 0 or list_addr > 0x7FFFFFFF:
                            continue
                        size = mem._uint(list_addr + 0x0C)
                        if size > 0 and size < 100_000:
                            print(f"Found potential list at hit_manager+{offset:#04x}")
                            print(f"  List addr: {list_addr:#010x}, Size: {size}")
                    except:
                        pass
        except:
            pass

        # Try generic scan for hit object arrays
        print("\n=== Scanning executable memory for potential hit object lists ===")
        print("Looking for patterns that indicate object arrays...\n")

        # Get all executable regions
        regions = []
        addr = 0
        while addr < _MAX_ADDR:
            mbi = _MBI()
            if ctypes.windll.kernel32.VirtualQueryEx(
                mem._pm.process_handle,
                ctypes.c_void_p(addr),
                ctypes.byref(mbi),
                ctypes.sizeof(mbi)
            ) == 0:
                break

            if mbi.State == _MEM_COMMIT and mbi.Protect in _EXECUTABLE:
                regions.append((mbi.BaseAddress, mbi.RegionSize))

            addr = mbi.BaseAddress + mbi.RegionSize

        print(f"[debug] Found {len(regions)} executable regions")
        print("[debug] Note: Finding correct offsets for lazer requires testing")
        print("[debug] Lazer uses .NET managed memory with different layout than stable\n")

        print("=== Recommendations for lazer offset discovery ===")
        print("1. Run this script while a mania map is playing")
        print("2. Look for hit object pointer patterns")
        print("3. Try common memory analysis tools (Cheat Engine) to find:")
        print("   - Hit object count (usually small number like 10-100)")
        print("   - Individual hit object start times (milliseconds)")
        print("   - Column indices for mania (0-8)")
        print("4. Once offsets found, update osu_memory.py with new values\n")

    except Exception as e:
        print(f"[debug] Error: {e}")

if __name__ == "__main__":
    main()
