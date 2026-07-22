#!/usr/bin/env python3
"""Generate Safari-executable JavaScript for Strava route build/create/update.

Input waypoints JSON can be either:
  [{"lat": 59.9, "lng": 10.6, "title": "..."}, ...]
or:
  [[59.9, 10.6, "optional title"], ...]

Run the output JavaScript inside a logged-in Safari tab on www.strava.com.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_points(path: Path) -> list[dict]:
    raw = json.loads(path.read_text())
    points = []
    for idx, item in enumerate(raw):
        if isinstance(item, dict):
            lat = item["lat"]
            lng = item["lng"]
            title = item.get("title") or item.get("name") or f"Waypoint {idx + 1}"
        else:
            lat, lng = item[0], item[1]
            title = item[2] if len(item) > 2 else f"Waypoint {idx + 1}"
        points.append({"lat": float(lat), "lng": float(lng), "title": title})
    if len(points) < 2:
        raise SystemExit("Need at least two waypoints")
    return points


def element(point: dict) -> dict:
    return {
        "elementType": "Waypoint",
        "waypoint": {
            "point": {"lat": point["lat"], "lng": point["lng"]},
            "metadata": {"title": point["title"]},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("waypoints", type=Path)
    parser.add_argument("--mode", choices=["build", "create", "update"], default="build")
    parser.add_argument("--route-id", help="Required for update mode")
    parser.add_argument("--athlete-id", type=int, help="Required for create mode")
    parser.add_argument("--name", default="Codex Strava Route")
    parser.add_argument("--description", default="Created by Codex from Safari-authenticated Strava route-builder workflow.")
    parser.add_argument("--visibility", default="OnlyMe")
    parser.add_argument("--starred", action="store_true")
    parser.add_argument("--route-type", default="Ride")
    parser.add_argument("--surface-type", default="Paved")
    parser.add_argument("--popularity", type=float, default=0.0)
    parser.add_argument("--elevation", type=float, default=0.0)
    parser.add_argument("--straight-line", action="store_true")
    parser.add_argument("--window-var", default="__codexStravaRoute")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    points = load_points(args.waypoints)
    route_prefs = {
        "routeType": args.route_type,
        "surfaceType": args.surface_type,
        "popularity": args.popularity,
        "elevation": args.elevation,
        "straightLine": args.straight_line,
    }
    elements = [element(p) for p in points]
    requests = [
        {"elements": [elements[i], elements[i + 1]], "routePrefs": route_prefs}
        for i in range(len(elements) - 1)
    ]

    if args.mode == "update" and not args.route_id:
        raise SystemExit("--route-id is required for update mode")
    if args.mode == "create" and not args.athlete_id:
        raise SystemExit("--athlete-id is required for create mode")

    var = args.window_var
    props_extra = ""
    endpoint = None
    if args.mode == "create":
        endpoint = "/api/next/data/routes/create-route"
        props_extra = f"athleteId: {args.athlete_id},"
    elif args.mode == "update":
        endpoint = "/api/next/data/routes/update-route"
        props_extra = f"routeId: {json.dumps(args.route_id)},"

    if args.mode == "build":
        js = f"""
(async () => {{
  const requests = {json.dumps(requests, separators=(',', ':'))};
  const csrf = document.querySelector('meta[name="csrf"]')?.content;
  const res = await fetch('/api/next/data/routes/build-route', {{
    method: 'POST', credentials: 'include',
    headers: {{ 'Content-Type':'application/json', 'Accept':'application/json, text/plain, */*', 'X-CSRF-Token': csrf, 'X-Requested-With':'XMLHttpRequest' }},
    body: JSON.stringify({{ requests }})
  }});
  const data = await res.json();
  window.{var} = {{ status: res.status, ok: res.ok, data }};
  return JSON.stringify({{ status: res.status, ok: res.ok, count: data.buildRoute?.length, meters: data.buildRoute?.reduce((s,e)=>s+(e.legs?.[0]?.paths?.[0]?.length||0),0) }});
}})();
"""
    else:
        js = f"""
(async () => {{
  const built = window.{var}Build?.data?.buildRoute || window.{var}?.data?.buildRoute;
  if (!built || !Array.isArray(built)) throw new Error('Missing built route legs. Run build JS first or store result in window.{var}.');
  const elements = {json.dumps(elements, separators=(',', ':'))};
  const routePrefs = {json.dumps(route_prefs, separators=(',', ':'))};
  const legs = built.map((entry, idx) => {{
    const leg = entry.legs?.[0];
    if (!leg) throw new Error('Missing leg at ' + idx);
    return {{ ...leg, startElement: idx }};
  }});
  const props = {{
    {props_extra}
    name: {json.dumps(args.name)},
    description: {json.dumps(args.description)},
    visibility: {json.dumps(args.visibility)},
    starred: {str(bool(args.starred)).lower()},
    elements,
    legs,
    routePrefs
  }};
  const csrf = document.querySelector('meta[name="csrf"]')?.content;
  const res = await fetch({json.dumps(endpoint)}, {{
    method: 'POST', credentials: 'include',
    headers: {{ 'Content-Type':'application/json', 'Accept':'application/json, text/plain, */*', 'X-CSRF-Token': csrf, 'X-Requested-With':'XMLHttpRequest' }},
    body: JSON.stringify({{ props }})
  }});
  const text = await res.text();
  let data = null; try {{ data = JSON.parse(text); }} catch (_) {{}}
  window.{var}Write = {{ status: res.status, ok: res.ok, data, text, summary: {{ elements: elements.length, legs: legs.length, meters: legs.reduce((s,l)=>s+(l.paths?.[0]?.length||0),0) }} }};
  return JSON.stringify(window.{var}Write).slice(0, 1000);
}})();
"""
    args.out.write_text(js)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
