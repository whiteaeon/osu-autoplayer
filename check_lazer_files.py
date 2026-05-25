"""Check recently accessed files in lazer's storage."""
import os
import time

lazer_files_dir = os.path.expandvars(r"%APPDATA%\osu\files")
now = time.time()
recent_files = []

print(f"Scanning {lazer_files_dir}...")
for root, dirs, files in os.walk(lazer_files_dir):
    for file in files:
        full_path = os.path.join(root, file)
        try:
            atime = os.path.getatime(full_path)
            size = os.path.getsize(full_path)
            # Files accessed in last 5 minutes
            if now - atime < 300:
                recent_files.append((atime, size, full_path))
        except:
            pass

recent_files.sort(reverse=True)
print(f"Found {len(recent_files)} files accessed in last 5 minutes")

# Try to identify .osu files by reading the first few bytes
for atime, size, path in recent_files[:20]:
    try:
        with open(path, 'rb') as f:
            header = f.read(200)
        # .osu files start with "osu file format v..."
        if b'osu file format' in header:
            seconds_ago = int(now - atime)
            print(f"  [{seconds_ago}s ago] {size} bytes: {path}")
    except:
        pass
