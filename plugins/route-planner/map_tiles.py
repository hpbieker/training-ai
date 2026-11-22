"""On-demand OSM tiles with an identified client and seven-day disk cache."""
import base64
import os
from pathlib import Path
import tempfile
import time
import httpx

CACHE = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'route-planner' / 'osm'
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
PNG_END = b'\x00\x00\x00\x00IEND\xaeB\x60\x82'


def is_png(raw):
    return raw.startswith(PNG_SIGNATURE) and raw.endswith(PNG_END)


def get_map_tile(z, x, y):
    if any(type(v) is not int for v in (z, x, y)) or not 0 <= z <= 19 or not (0 <= x < 2**z and 0 <= y < 2**z):
        raise ValueError('Invalid tile coordinates.')
    path = CACHE / str(z) / str(x) / f'{y}.png'
    raw = b''
    try:
        if time.time() - path.stat().st_mtime < 7 * 86400:
            raw = path.read_bytes()
    except FileNotFoundError:
        pass
    if not is_png(raw):
        response = httpx.get(f'https://tile.openstreetmap.org/{z}/{x}/{y}.png', headers={'User-Agent': 'RoutePlanner/0.2 (personal desktop MCP route planner)'}, timeout=20)
        response.raise_for_status()
        raw = response.content
        if not is_png(raw):
            raise ValueError('Tile provider did not return a PNG image.')
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(raw)
                output.close()
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    return 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii')
