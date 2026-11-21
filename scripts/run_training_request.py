"""Run one saved coaching request using previously collected plugin inputs."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import recommend_training
from recommendation_binding import instant


JSON_INPUTS = ("plan_selection", "training_target", "quality_workout", "endurance_workout",
               "illness_return", "route_options")


def build_arguments(path, now):
    request = json.loads(path.read_text())
    if not isinstance(request, dict):
        raise ValueError("The request must be a JSON object")
    unknown = request.keys() - {"planning_context", "sources", *JSON_INPUTS}
    if unknown:
        raise ValueError(f"Unknown request fields: {sorted(unknown)}")

    planning = dict(request["planning_context"])
    local_zone = recommend_training.parse_timezone(planning["local_timezone"])
    planning["now"] = now.astimezone(local_zone).isoformat()
    start = instant(planning["planned_at"], "planned_at")
    calendar = planning.get("calendar") or {}
    if calendar.get("events") and "open_training_subjects" not in calendar:
        raise ValueError(
            "Resolve calendar.open_training_subjects from the current coaching preferences "
            "before reusing calendar classifications. Supply the configured titles, or [] if none. "
            "Review timing and dose if a former blocker is open."
        )
    setup = timedelta(minutes=calendar.get("setup_buffer_minutes", 0))
    if start - setup < now:
        raise ValueError("The setup window has passed; reassess the workout start")
    if calendar.get("day_start") and instant(calendar["day_start"], "day_start") < now:
        planning["calendar"] = dict(calendar, day_start=planning["now"])

    sources = request["sources"]
    if not isinstance(sources, dict):
        raise ValueError("sources must map plugin source names to path and read_at")
    paths = {}
    expired = []
    for name, source in sources.items():
        if name not in recommend_training.SOURCE_REFRESH_POLICY:
            raise ValueError(f"Unknown source: {name}")
        if not isinstance(source, dict):
            raise ValueError(f"{name} requires path and read_at")
        checked = instant(source.get("read_at"), f"{name}.read_at")
        ttl = recommend_training.SOURCE_REFRESH_POLICY[name][1]
        if checked > now or now - checked > timedelta(minutes=ttl):
            expired.append(name)
        paths[name] = str((path.parent / source["path"]).resolve())
    if expired:
        raise ValueError("Refresh through the source plugins and update read_at: " + ", ".join(expired))

    if "xert_recommended_training" in paths:
        raw = json.loads(Path(paths["xert_recommended_training"]).read_text())
        if not isinstance(raw, dict):
            raise ValueError("Expected a JSON object for Xert planned advice")
        advice = recommend_training.normalize_source_override_payload("xert_recommended_training", raw)
        if instant(advice.get("at"), "Xert planned advice at") != start:
            raise ValueError("Get Xert advice for the updated workout start")
    args = ["--planning-context-json", json.dumps(planning), "--source-overrides-json", json.dumps(paths),
            "--refresh-json", '{"mode":"none"}', "--output-dir", str(path.parent), "--summary"]
    for field in JSON_INPUTS:
        if field in request:
            args.extend(["--" + field.replace("_", "-") + "-json", json.dumps(request[field])])
    return args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--as-of", help="Offset-aware decision time for a historical replay (default: now)")
    args = parser.parse_args()
    try:
        now = instant(args.as_of, "as_of") if args.as_of else datetime.now(timezone.utc)
        arguments = build_arguments(args.request.resolve(), now)
        recommend_training.main(arguments, require_finish_review=True)
    except (OSError, ValueError, KeyError, TypeError, argparse.ArgumentTypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
