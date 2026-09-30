# Training Visuals

A Python MCP server for general training visualizations. `show_route` displays an
existing planned or completed route, independent of Garmin, Strava, Xert or Intervals.

## Run

Install Python dependencies with `python3 -m pip install -r requirements.txt`.
The plugin runs `python3 -B training_visuals_mcp.py` over stdio. No Node runtime
or API key is needed to run the installed plugin.

Supply exactly one of `route_file` (absolute GPX/GeoJSON/training-ai route JSON
path) or `geojson` (LineString/MultiLineString or line Features). Optional title,
date, status, distance_km, moving_time_s, elevation_gain_m and source_url describe
the route. Missing metrics are omitted. Route segments remain separate.

The MCP App uses the standard ui.resourceUri metadata and MCP Apps SDK. Full
geometry is in tool-result _meta, while model-visible output is a compact summary.
The browser uses Leaflet. `get_map_tile` is an app-only tool: Python fetches only
requested tiles with an identifying User-Agent and caches them for seven days in
~/.cache/training-visuals/osm (or XDG_CACHE_HOME). OSM attribution stays visible.
No route is uploaded to the tile provider, but requested tile coordinates reveal
the viewed map area. Follow https://operations.osmfoundation.org/policies/tiles/.

## Develop and test

Server, validation, file import, tile loading, build orchestration and local preview
are Python (`mcp`, `anyio`, `httpx`, standard library). Browser interaction requires
JavaScript: Leaflet and the official MCP Apps SDK. Their compiled code is bundled
in web/dist/show-route.html, with no CDN script dependencies.

```sh
python3 -m unittest discover -s tests -v
cd web
npm ci
npm run build
cd ..
python3 scripts/preview.py --arguments /absolute/path/to/arguments.json
```

The local preview checks stdio discovery, show_route and resource reading, then
uses the official AppBridge in a sandboxed iframe. Tile calls in this test host
use the same Python tile function over a loopback-only HTTP endpoint. Test the
installed tool in a new Codex task to verify the actual host's MCP Apps support.

Limits: 100,000 points, 20 MB local files, Web Mercator latitude bounds;
antimeridian crossings are rejected. This is a viewer, not a routing engine.
