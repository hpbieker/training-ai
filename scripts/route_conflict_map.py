#!/usr/bin/env python3
"""Build an interactive OSM map for a saved route and inferred conflict points."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import route_recommendations as routes


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Leaflet route conflict map.")
    parser.add_argument("--activity-id", required=True)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--years", type=float, default=5.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    route = find_route(args.activity_id, day=routes.parse_date(args.date), years=args.years)
    routes.add_osm_junction_counts([route])
    yield_situations = route.get("map_yield_situations") or {}
    inferred = yield_situations.get("inferred_priority_yield_situations") or {}
    if not inferred.get("available"):
        reason = yield_situations.get("reason") or inferred.get("reason") or "missing_osm_conflicts"
        detail = yield_situations.get("detail") or inferred.get("detail")
        message = f"OSM conflict data unavailable: {reason}"
        if detail:
            message += f" ({detail})"
        raise SystemExit(message)

    output = args.output or Path("outputs/maps") / f"{args.activity_id}_route_conflicts.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_map(route), encoding="utf-8")
    print(output)


def find_route(activity_id: str, *, day: date, years: float) -> dict[str, Any]:
    result = routes.recommend_routes(
        day=day,
        years=years,
        target_minutes=None,
        target_load=None,
        xert_loads_json=None,
        target_distance_km=None,
        queries=[],
        max_results=10_000,
        artifacts_dir=routes.ARTIFACTS_DIR,
        start_anchor_name=None,
        start_anchor_lat=None,
        start_anchor_lng=None,
        start_radius_km=routes.DEFAULT_START_RADIUS_KM,
        allow_away=True,
        surface_preference="any",
        junction_source="none",
    )
    for route in result["recommendations"]:
        if route.get("id") == activity_id:
            return route
    raise SystemExit(f"route not found: {activity_id}")


def render_map(route: dict[str, Any]) -> str:
    activity_dir = Path(str(route["activity_dir"]))
    points = routes.route_gps_points(activity_dir / "streams.csv")
    line = simplify_route_line([[point["lat"], point["lng"]] for point in points], max_points=1800)
    yield_situations = route.get("map_yield_situations") or {}
    inferred = yield_situations.get("inferred_priority_yield_situations") or {}
    conflicts = inferred.get("events_preview") or []
    explicit = yield_situations.get("events_preview") or []
    title = f"{route.get('name')} ({route.get('id')})"
    payload = {
        "title": title,
        "distanceKm": route.get("distance_km"),
        "route": line,
        "conflicts": conflicts,
        "explicitEvents": explicit,
        "counts": {
            "inferredPriorityYield": yield_situations.get("inferred_priority_yield_count"),
            "explicitYieldOrStop": yield_situations.get("explicit_yield_or_stop_count"),
            "crossings": yield_situations.get("crossing_count"),
        },
    }
    return HTML_TEMPLATE.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))


def simplify_route_line(points: list[list[float]], *, max_points: int) -> list[list[float]]:
    if len(points) <= max_points:
        return points
    step = max(1, round(len(points) / max_points))
    simplified = points[::step]
    if simplified[-1] != points[-1]:
        simplified.append(points[-1])
    return simplified


HTML_TEMPLATE = """<!doctype html>
<html lang="no">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Route conflicts</title>
  <style>
    html, body { height: 100%; margin: 0; overflow: hidden; }
    #map { position: fixed; inset: 0; width: 100vw; height: 100vh; }
    body { font: 14px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .leaflet-container {
      overflow: hidden;
      background: #ddd;
      outline: 0;
      font: 12px/1.5 "Helvetica Neue", Arial, Helvetica, sans-serif;
    }
    .leaflet-pane,
    .leaflet-tile,
    .leaflet-marker-icon,
    .leaflet-marker-shadow,
    .leaflet-tile-container,
    .leaflet-pane > svg,
    .leaflet-pane > canvas,
    .leaflet-zoom-box,
    .leaflet-image-layer,
    .leaflet-layer {
      position: absolute;
      left: 0;
      top: 0;
    }
    .leaflet-tile,
    .leaflet-marker-icon,
    .leaflet-marker-shadow {
      user-select: none;
      -webkit-user-drag: none;
    }
    .leaflet-tile { width: 256px; height: 256px; }
    .leaflet-interactive {
      cursor: pointer;
      pointer-events: auto;
    }
    .leaflet-pane { z-index: 400; }
    .leaflet-tile-pane { z-index: 200; }
    .leaflet-overlay-pane { z-index: 400; }
    .leaflet-shadow-pane { z-index: 500; }
    .leaflet-marker-pane { z-index: 600; }
    .leaflet-tooltip-pane { z-index: 650; }
    .leaflet-popup-pane { z-index: 700; }
    .leaflet-control { position: relative; z-index: 800; pointer-events: auto; }
    .leaflet-top,
    .leaflet-bottom { position: absolute; z-index: 1000; pointer-events: none; }
    .leaflet-top { top: 0; }
    .leaflet-right { right: 0; }
    .leaflet-bottom { bottom: 0; }
    .leaflet-left { left: 0; }
    .leaflet-top .leaflet-control { margin-top: 12px; }
    .leaflet-right .leaflet-control { margin-right: 12px; }
    .leaflet-left .leaflet-control { margin-left: 12px; }
    .leaflet-bottom .leaflet-control { margin-bottom: 12px; }
    .leaflet-bar {
      border-radius: 4px;
      box-shadow: 0 2px 8px rgba(0,0,0,.25);
    }
    .leaflet-bar a {
      display: block;
      width: 30px;
      height: 30px;
      line-height: 30px;
      background: #fff;
      border-bottom: 1px solid #ccc;
      color: #111;
      text-align: center;
      text-decoration: none;
      font: 700 20px/30px Arial, sans-serif;
    }
    .leaflet-bar a:first-child { border-top-left-radius: 4px; border-top-right-radius: 4px; }
    .leaflet-bar a:last-child { border-bottom: 0; border-bottom-left-radius: 4px; border-bottom-right-radius: 4px; }
    .leaflet-bar a:hover { background: #f4f4f4; }
    .leaflet-bar a.leaflet-disabled {
      cursor: default;
      color: #bbb;
      background: #f4f4f4;
    }
    .leaflet-control-attribution {
      background: rgba(255,255,255,.8);
      margin: 0;
      padding: 0 5px;
      color: #333;
    }
    .leaflet-control-attribution a { color: #0078a8; text-decoration: none; }
    .leaflet-popup {
      position: absolute;
      text-align: center;
      margin-bottom: 20px;
    }
    .leaflet-popup-content-wrapper {
      padding: 1px;
      text-align: left;
      border-radius: 8px;
      background: white;
      box-shadow: 0 3px 14px rgba(0,0,0,.4);
    }
    .leaflet-popup-content { margin: 10px 12px; line-height: 1.35; }
    .leaflet-popup-tip-container { width: 40px; height: 20px; position: absolute; left: 50%; margin-left: -20px; overflow: hidden; pointer-events: none; }
    .leaflet-popup-tip { width: 14px; height: 14px; padding: 1px; margin: -8px auto 0; transform: rotate(45deg); background: white; box-shadow: 0 3px 14px rgba(0,0,0,.4); }
    .panel {
      position: absolute;
      top: 12px;
      left: 12px;
      z-index: 1000;
      max-width: 360px;
      padding: 10px 12px;
      background: rgba(255,255,255,.94);
      border: 1px solid rgba(0,0,0,.18);
      border-radius: 8px;
      box-shadow: 0 4px 14px rgba(0,0,0,.18);
    }
    .panel h1 { margin: 0 0 6px; font-size: 15px; }
    .panel p { margin: 3px 0; color: #333; }
    .tile-error {
      display: none;
      margin-top: 8px;
      color: #8a1f11;
      font-weight: 600;
    }
    .legend { display: flex; gap: 12px; margin-top: 8px; }
    .legend span { display: inline-flex; align-items: center; gap: 5px; }
    .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .red { background: #d71920; }
    .amber { background: #f29f05; }
    .blue { background: #1967d2; }
    .leaflet-popup-content { min-width: 220px; max-width: 340px; }
    .popup h2 { margin: 0 0 6px; font-size: 13px; line-height: 1.25; color: #555; }
    .popup p { margin: 5px 0; }
    .popup .issue { font-size: 15px; font-weight: 700; line-height: 1.25; color: #111; }
    .popup .route-line { color: #222; }
    .popup .side-line { color: #333; }
    .popup .muted { color: #555; }
    .popup details { margin-top: 8px; }
    .popup summary { cursor: pointer; color: #555; font-weight: 600; }
    .popup table { border-collapse: collapse; margin-top: 6px; }
    .popup td { padding: 2px 6px 2px 0; vertical-align: top; }
    .popup td:first-child { color: #555; white-space: nowrap; }
  </style>
</head>
<body>
<div id="map"></div>
<div class="panel">
  <h1 id="title"></h1>
  <p id="summary"></p>
  <p class="tile-error" id="tile-error">Kartfliser lastes ikke. Prøv lokal HTTP-lenke i stedet for file://.</p>
  <div class="legend">
    <span><i class="dot blue"></i>Rute</span>
    <span><i class="dot red"></i>Klassekonflikt</span>
    <span><i class="dot amber"></i>Fotgjengerovergang/vikeplikt</span>
  </div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
  integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
function popupTable(rows) {
  const body = rows.map(([key, value]) => `<tr><td>${escapeHtml(key)}</td><td>${escapeHtml(String(value ?? ''))}</td></tr>`).join('');
  return `<div class="popup"><table>${body}</table></div>`;
}

function describeWay(way) {
  if (!way) return '(ukjent vei)';
  const name = way.name || '(uten navn)';
  const highway = way.highway ? ` · ${way.highway}` : '';
  const rank = way.rank ? ` · klasse ${way.rank}` : '';
  return `${name}${highway}${rank}`;
}

function shortWayName(way) {
  if (!way) return '(ukjent vei)';
  const name = way.name || '(uten navn)';
  const highway = way.highway ? ` (${way.highway})` : '';
  return `${name}${highway}`;
}

function issueSummary(event) {
  const reason = event.reason || '';
  const parts = [];
  if (reason.includes('higher-priority OSM highway class')) {
    parts.push('Inn på høyere veiklasse');
  }
  if (reason.includes('higher road class than the incoming route')) {
    parts.push('Sidevei har høyere klasse');
  }
  if (reason.includes("rider's right")) {
    parts.push('Høyreregel');
  }
  return parts.length ? parts.join(' + ') : 'Mulig konflikt';
}

function describeSideWays(event) {
  return (event.same_or_higher_priority_side_ways || []).map((way) => {
    const angle = way.right_side_angle_deg == null ? '' : ` · ${way.right_side_angle_deg}° fra høyre`;
    const right = way.right_hand_rule_hit === true ? ' · høyre side' : '';
    return escapeHtml(`${describeWay(way)}${right}${angle}`);
  }).join('<br>');
}

function conflictPopup(event, index) {
  const sideWays = describeSideWays(event);
  const sideNames = (event.same_or_higher_priority_side_ways || [])
    .map(way => shortWayName(way))
    .join(', ');
  const rows = [
    ['km', event.route_distance_km],
    ['fra detalj', describeWay(event.route_before)],
    ['til detalj', describeWay(event.route_after)],
    ['kryssklasser', event.connected_highway_types?.join(', ')],
    ['høyeste klasse', event.highest_priority_highway],
    ['sving', `${event.route_turn_deg ?? '?'}°`],
    ['OSM node', event.node_id],
  ];
  const body = rows.map(([key, value]) => `<tr><td>${escapeHtml(key)}</td><td>${escapeHtml(String(value ?? ''))}</td></tr>`).join('');
  const sideHtml = sideNames ? `<p class="side-line">Sidevei: ${escapeHtml(sideNames)}</p>` : '';
  const sideDebugHtml = sideWays ? `<p><b>Sidearm:</b><br>${sideWays}</p>` : '';
  return `
    <div class="popup">
      <h2>Konflikt ${index + 1} · km ${escapeHtml(String(event.route_distance_km ?? '?'))}</h2>
      <p class="issue">${escapeHtml(issueSummary(event))}</p>
      <p class="route-line">${escapeHtml(shortWayName(event.route_before))} → ${escapeHtml(shortWayName(event.route_after))}</p>
      ${sideHtml}
      <details>
        <summary>More</summary>
        <p class="muted">OSM-veiklasse og geometri langs matchet rute, ikke veinavn.</p>
        ${sideDebugHtml}
        <table>${body}</table>
      </details>
    </div>`;
}

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[ch]));
}

function marker(lat, lng, color) {
  return L.circleMarker([lat, lng], {
    radius: 8,
    color: '#222',
    weight: 1,
    fillColor: color,
    fillOpacity: 0.9
  });
}

function bindHoverPopup(layer, html) {
  layer.bindPopup(html, {
    autoPan: false,
    closeButton: false,
    maxWidth: 360,
    offset: [0, -6],
  });
  layer.on('mouseover', () => layer.openPopup());
  layer.on('mousemove', () => layer.openPopup());
  layer.on('click', () => layer.openPopup());
  return layer;
}

const data = __PAYLOAD__;
window.routeConflictData = data;
let map;

function initMap() {
  document.getElementById('title').textContent = data.title;
  document.getElementById('summary').textContent =
    `${data.distanceKm} km · klassekonflikter ${data.counts.inferredPriorityYield ?? 0} · ` +
    `eksplisitt vikeplikt/stopp ${data.counts.explicitYieldOrStop ?? 0} · ` +
    `fotgjengeroverganger ${data.counts.crossings ?? 0}`;

  map = L.map('map', {
    preferCanvas: false,
    zoomControl: false,
    zoomAnimation: false,
    fadeAnimation: false,
    markerZoomAnimation: false,
    wheelPxPerZoomLevel: 120,
  });
  window.map = map;
  L.control.zoom({ position: 'topright' }).addTo(map);
  const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    tileSize: 256,
    updateWhenIdle: true,
    keepBuffer: 4,
    attribution: '&copy; OpenStreetMap contributors'
  });
  tiles.on('tileerror', () => {
    document.getElementById('tile-error').style.display = 'block';
  });
  tiles.addTo(map);

  const route = L.polyline(data.route, { color: '#1967d2', weight: 4, opacity: 0.85 }).addTo(map);
  window.routeLayer = route;
  data.conflicts.forEach((event, index) => {
    bindHoverPopup(marker(event.lat, event.lng, '#d71920'), conflictPopup(event, index)).addTo(map);
  });

  data.explicitEvents.forEach((event) => {
    bindHoverPopup(
      marker(event.lat, event.lng, '#f29f05'),
      popupTable([
        ['OSM-type', event.highway === 'crossing' ? 'fotgjengerovergang' : event.highway],
        ['avstand til rute', `${event.distance_to_route_m} m`],
        ['OSM node', event.node_id],
      ])
    ).addTo(map);
  });

  const fit = () => {
    map.invalidateSize(true);
    map.fitBounds(L.latLngBounds(data.route), {
      padding: [48, 48],
      maxZoom: 14,
    });
  };
  requestAnimationFrame(() => {
    fit();
    setTimeout(fit, 150);
  });
}

window.addEventListener('load', initMap);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
