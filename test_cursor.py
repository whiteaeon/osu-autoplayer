"""Test if cursor movement actually works."""
import ctypes
import time

# Make DPI aware
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    ctypes.windll.user32.SetProcessDPIAware()

print("Moving cursor to test positions...")
print("Watch your cursor on screen!")
time.sleep(2)

positions = [
    (960, 600, "Center"),
    (200, 200, "Top-left"),
    (1700, 200, "Top-right"),
    (1700, 1000, "Bottom-right"),
    (200, 1000, "Bottom-left"),
    (960, 600, "Back to center"),
]

for x, y, name in positions:
    print(f"  Moving to {name}: ({x}, {y})")
    ctypes.windll.user32.SetCursorPos(x, y)
    time.sleep(1)

print("\nDone! Did the cursor visibly move to each position?")
