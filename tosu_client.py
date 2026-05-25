"""
Tosu client - provides game state for osu!lazer (and stable) via HTTP API.

Tosu (https://github.com/tosuapp/tosu) is a community memory reader that
supports both osu! stable AND lazer. We use its API instead of doing our
own memory scanning, which is much more reliable.

Usage:
    1. Download tosu from https://github.com/tosuapp/tosu/releases
    2. Run tosu.exe (it stays in background, listens on port 24050)
    3. Use this client to query game state
"""

import os
import requests
from typing import Optional


# Tosu game state values (menu.state)
STATE_MENU = 0
STATE_EDITOR = 1
STATE_PLAYING = 2
STATE_EXIT = 3
STATE_SELECT_EDIT = 4
STATE_SELECT_PLAY = 5
STATE_RESULTS = 7
STATE_GAME_SHUTDOWN = 11
STATE_REPLAY = 14

# Tosu game modes (menu.gameMode)
MODE_STD = 0
MODE_TAIKO = 1
MODE_CATCH = 2
MODE_MANIA = 3

MODE_NAMES = {
    MODE_STD: "standard",
    MODE_TAIKO: "taiko",
    MODE_CATCH: "catch",
    MODE_MANIA: "mania",
}


class TosuClient:
    """Client for tosu's HTTP API."""

    def __init__(self, base_url: str = "http://localhost:24050"):
        self.base_url = base_url
        self._cache = None
        self._songs_folder = None

    def is_available(self) -> bool:
        """Check if tosu is running and responding."""
        try:
            r = requests.get(f"{self.base_url}/json", timeout=1.0)
            return r.status_code == 200
        except:
            return False

    def fetch(self) -> Optional[dict]:
        """Fetch full game state from tosu."""
        try:
            r = requests.get(f"{self.base_url}/json", timeout=1.0)
            if r.status_code == 200:
                self._cache = r.json()
                return self._cache
        except Exception as e:
            pass
        return None

    def get_game_time(self) -> int:
        """Current playback position in milliseconds."""
        data = self.fetch()
        if data:
            return data.get('menu', {}).get('bm', {}).get('time', {}).get('current', 0)
        return 0

    def is_playing(self) -> bool:
        """True if in gameplay state."""
        data = self.fetch()
        if data:
            return data.get('menu', {}).get('state', 0) == STATE_PLAYING
        return False

    def get_state(self) -> int:
        """Get current game state."""
        data = self.fetch()
        if data:
            return data.get('menu', {}).get('state', 0)
        return 0

    def get_game_mode(self) -> str:
        """Get current game mode as string ('standard', 'mania', etc)."""
        data = self.fetch()
        if data:
            mode_id = data.get('menu', {}).get('gameMode', 0)
            return MODE_NAMES.get(mode_id, "standard")
        return "standard"

    def get_first_object_time(self) -> int:
        """Time of the first hit object in milliseconds."""
        data = self.fetch()
        if data:
            return data.get('menu', {}).get('bm', {}).get('time', {}).get('firstObj', 0)
        return 0

    def get_songs_folder(self) -> Optional[str]:
        """Get the songs folder path from tosu settings."""
        if self._songs_folder:
            return self._songs_folder
        data = self.fetch()
        if data:
            self._songs_folder = data.get('settings', {}).get('folders', {}).get('songs')
            return self._songs_folder
        return None

    def get_current_map_file(self) -> Optional[str]:
        """Get the full path to the currently loaded .osu file."""
        data = self.fetch()
        if not data:
            return None

        bm = data.get('menu', {}).get('bm', {})
        path_info = bm.get('path', {})

        # Get songs folder
        songs_folder = data.get('settings', {}).get('folders', {}).get('songs')
        if not songs_folder:
            return None

        # The 'file' field contains the relative path
        file_rel = path_info.get('file')
        if not file_rel:
            return None

        full_path = os.path.join(songs_folder, file_rel)
        if os.path.exists(full_path):
            return full_path
        return None

    def get_map_metadata(self) -> Optional[dict]:
        """Get artist/title/difficulty of the current map."""
        data = self.fetch()
        if data:
            return data.get('menu', {}).get('bm', {}).get('metadata')
        return None

    def get_client_type(self) -> str:
        """Returns 'stable' or 'lazer'."""
        data = self.fetch()
        if data:
            return data.get('client', 'unknown')
        return 'unknown'

    def get_status(self) -> int:
        """Compat with OsuMemory: get game status."""
        return self.get_state()

    def get_column_count(self) -> int:
        """Compat with OsuMemory: get mania key count."""
        data = self.fetch()
        if data:
            return int(data.get('menu', {}).get('bm', {}).get('stats', {}).get('CS', 4))
        return 4

    def reset_play_clock(self):
        """Compat with OsuMemory: no-op, tosu provides real game time."""
        pass


if __name__ == '__main__':
    # Test
    client = TosuClient()
    if not client.is_available():
        print("[X] Tosu not running. Start tosu.exe first.")
    else:
        print("[OK] Tosu is running")
        print(f"   Client: {client.get_client_type()}")
        print(f"   State: {client.get_state()}")
        print(f"   Mode: {client.get_game_mode()}")
        print(f"   Game time: {client.get_game_time()}ms")
        meta = client.get_map_metadata()
        if meta:
            print(f"   Map: {meta.get('artist')} - {meta.get('title')} [{meta.get('difficulty')}]")
        path = client.get_current_map_file()
        print(f"   File: {path}")
