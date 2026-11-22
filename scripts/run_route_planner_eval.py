#!/usr/bin/env python3
"""Run and score the Hurum Route Planner task with a fresh Codex session."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/route-planner"
SKILL = PLUGIN / "skills/route-planner/SKILL.md"
CASE_FILE = ROOT / "evals/route-planner/hurum.json"
sys.path.insert(0, str(PLUGIN))
from route_geometry import distance


def completed_calls(events):
    return [
        event["item"] for line in events.read_text().splitlines()
        if (event := json.loads(line)).get("type") == "item.completed"
        and event.get("item", {}).get("type") == "mcp_tool_call"
    ]


def track(saved):
    return json.loads(Path(saved["geojson_file"]).read_text())["features"][0]["geometry"]["coordinates"]


def corridor_checks(coords, case):
    chain = [0.0]
    for start, end in zip(coords, coords[1:]):
        chain.append(chain[-1] + distance(start, end))
    nearest = {}
    (start_name, start), *checkpoints = case["checkpoints"]
    nearest[start_name] = {"distance_m": round(distance(start, coords[0]), 1), "progress_m": 0.0}
    for name, point in checkpoints:
        gap, index = min((distance(point, vertex), i) for i, vertex in enumerate(coords))
        nearest[name] = {"distance_m": round(gap, 1), "progress_m": round(chain[index], 1)}
    east_names = [name for name, _ in case["checkpoints"][:-1]]
    east = [nearest[name] for name in east_names]
    west = nearest[case["checkpoints"][-1][0]]
    progress = [row["progress_m"] for row in (*east, west)]
    east_ok = all(row["distance_m"] <= 35 for row in east)
    direction_ok = east_ok and west["distance_m"] <= 650 and progress == sorted(set(progress))
    excess_m = round(east[-1]["progress_m"] - east[0]["progress_m"] - case["east_leg_km"] * 1000, 1)
    # An exact reversed edge near Tofte detects a guide-induced out-and-back
    # after the east-leg checkpoint as well as before it.
    tofte = case["checkpoints"][-2][1]
    nearby_edges = set()
    repeated = 0.0
    for a, b in zip(coords, coords[1:]):
        if distance(a, tofte) > 850 or distance(b, tofte) > 850:
            continue
        edge = tuple(a[:2]), tuple(b[:2])
        if edge[::-1] in nearby_edges:
            repeated += distance(a, b)
        nearby_edges.add(edge)
    return {
        "start_and_end": all(distance(start, p) <= 35 for p in (coords[0], coords[-1])),
        "checkpoints": nearest,
        "clockwise": direction_ok,
        "east_leg_excess_m": excess_m if east_ok else None,
        "tofte_retraced_m": round(repeated, 1),
        "east_leg_without_spur": east_ok and abs(excess_m) <= 100 and repeated <= 25,
    }


def score(out, case):
    calls = completed_calls(out / "events.jsonl")
    shown_routes = [
        route_id for call in calls
        if call["tool"] == "show_route" and call["status"] == "completed"
        and (route_id := call["arguments"].get("route_id"))
    ]
    report = {"mcp_available": bool(calls), "shown_routes": shown_routes, "route_passed": False}
    saved_paths = sorted(
        (out / "routes").glob("*/current.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True,
    )
    for path in saved_paths:
        saved = json.loads(path.read_text())
        if shown_routes and saved["route_id"] != shown_routes[-1]:
            continue
        checks = corridor_checks(track(saved), case)
        report.update(route_id=saved["route_id"], revision=saved["revision"], **checks)
        report["route_passed"] = all(
            checks[name] for name in ("start_and_end", "clockwise", "east_leg_without_spur")
        )
        break
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--effort", default="medium")
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True)
    case = json.loads(CASE_FILE.read_text())
    skill = SKILL.read_bytes()
    (out / "skill.md").write_bytes(skill)
    lon, lat = case["checkpoints"][0][1]
    prompt = (
        "Read SKILL.md and use the Route Planner MCP tools in this workspace.\n\n"
        f'{case["prompt"]} Start og mål er ved Storsand ({lat}, {lon}).'
    )
    mcp = (
        f'command={json.dumps(sys.executable)}, '
        f'args=["-B",{json.dumps(str(PLUGIN / "route_planner_mcp.py"))}], '
        f'env={{ROUTE_PLANNER_ROUTES={json.dumps(str(out / "routes"))}}}, tool_timeout_sec=95'
    )
    with tempfile.TemporaryDirectory(prefix="route-planner-eval-") as directory:
        trial = Path(directory).resolve()
        (trial / "SKILL.md").write_bytes(skill)
        command = [
            shutil.which("codex") or "codex", "exec", "--ignore-user-config", "--ephemeral",
            "--skip-git-repo-check", "--approve-for-me", "--model", args.model,
            "-c", f'projects.{json.dumps(str(trial))}.trust_level="trusted"',
            "-c", f'model_reasoning_effort={json.dumps(args.effort)}', "-c", f"mcp_servers.route-planner={{{mcp}}}",
            "--cd", str(trial), "--json", "--output-last-message", str(out / "answer.md"), "-",
        ]
        with (out / "events.jsonl").open("w") as events, (out / "stderr.log").open("w") as errors:
            result = subprocess.run(command, input=prompt, text=True, stdout=events, stderr=errors, timeout=480)
    report = {
        "model": args.model,
        "effort": args.effort,
        "cli_exit_code": result.returncode,
        "skill_sha256": hashlib.sha256(skill).hexdigest(),
        "case_sha256": hashlib.sha256(CASE_FILE.read_bytes()).hexdigest(),
        **score(out, case),
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    (out / "result.json").write_text(rendered + "\n")
    print(rendered, flush=True)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
