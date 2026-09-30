"""On-demand OSM tiles with an identified client and seven-day disk cache."""
import base64
import os
from pathlib import Path
import time
import httpx

CACHE = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'training-visuals' / 'osm'


def get_map_tile(z, x, y):
    if any(type(v) is not int for v in (z, x, y)) or not 0 <= z <= 19 or not (0 <= x < 2**z and 0 <= y < 2**z):
        raise ValueError('Invalid tile coordinates.')
    path = CACHE / str(z) / str(x) / f'{y}.png'
    if path.exists() and time.time() - path.stat().st_mtime < 7 * 86400:
        raw = path.read_bytes()
    else:
        response = httpx.get(f'https://tile.openstreetmap.org/{z}/{x}/{y}.png', headers={'User-Agent': 'TrainingVisuals/0.1 (personal desktop MCP route viewer)'}, timeout=20)
        response.raise_for_status()
        raw = response.content
        if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Tile provider did not return a PNG image.')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
