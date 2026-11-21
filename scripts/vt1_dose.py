"""Compare an aerobic prescription with reviewed rides of the same purpose."""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

from athlete_feedback import saved_context
from analysis import detect_stable_power_blocks, load_activity, load_activity_metadata
from physiological_evidence import matched_windows, numeric, timeline, vt1_power_band
from plan_state import (AEROBIC_ROLES, QUALITY_ROLES, DEFAULT_ARTIFACTS_DIR,
                        DEFAULT_STATE_PATH, load_plan_state, parse_datetime, parse_iso_datetime)


def recorded_work_intervals(metadata):
    """Return source-labelled work bouts, which can differ from time in a power band."""
    intervals = metadata.get("icu_intervals")
    if not isinstance(intervals, list):
        return None
    work = []
    for interval in intervals:
        if not isinstance(interval, dict) or interval.get("type") != "WORK":
            continue
        seconds = numeric(interval, "elapsed_time")
        if seconds is None or seconds <= 0:
            continue
        watts = None if metadata.get("icu_ignore_power") else numeric(interval, "average_watts")
        work.append({"seconds": seconds, "average_watts": watts})
    return work


def athlete_report_at(directory, cutoff):
    path = directory / "athlete-report.json" if directory else None
    if not path or not path.is_file():
        return {}
    report = json.loads(path.read_text())
    stamp = report.get("reported_at") or report.get("recorded_at")
    if stamp:
        return report if parse_datetime(stamp) <= cutoff else {}
    return {}


def longest_indoor_power_block(directory, metadata):
    """Summarize the longest detected plateau with sufficient valid power coverage."""
    if directory is None or not (directory / "streams.csv").is_file():
        return None
    if metadata.get("icu_ignore_power") or metadata.get("icu_ignore_time") or metadata.get("ignore_parts"):
        return None
    rows = load_activity(directory).streams
    clock = timeline(rows)
    if clock is None:
        return None
    times, widths, _ = clock
    longest = None
    longest_seconds = 0
    for block in detect_stable_power_blocks(rows):
        start, end = block.start_index, block.end_index
        elapsed = times[end - 1] + widths[end - 1] - times[start]
        valid_seconds = work = 0.0
        for i in range(start, end):
            power = numeric(rows[i], "watts")
            if power is not None:
                valid_seconds += widths[i]
                work += widths[i] * power
        if valid_seconds >= 0.95 * elapsed and elapsed > longest_seconds:
            longest_seconds = elapsed
            longest = {"minutes": round(elapsed / 60, 1), "mean_watts": round(work / valid_seconds, 1)}
    return longest


def measured_aerobic_references(history, directories):
    """Measure spacing rides on both sides of the reviewed quality sessions."""
    rides = list(history["latest_activities"])
    next_quality_starts = {}
    for sequence in history["quality_sequences"]:
        rides.extend((sequence.get("previous_activity"), sequence.get("activity_before_previous")))
        rides.extend(sequence["following_day"]["activities"])
        prior = sequence.get("previous_activity")
        if prior:
            next_quality_starts[prior["activity_id"]] = sequence["attempt"]["start"]
        following_quality = sequence.get("next_quality_session")
        if following_quality:
            for ride in sequence["following_day"]["activities"]:
                next_quality_starts[ride["activity_id"]] = following_quality["attempt"]["start"]
    candidates = {r["activity_id"]: (r["completed_role"], r["start"]) for r in rides if r}
    for sequence in history["long_finish_references"].values():
        for ride in sequence["intervening_activities"]:
            candidates[ride["activity_id"]] = (ride["role"], ride["started_at"])
            if sequence.get("next_quality_attempt"):
                next_quality_starts[ride["activity_id"]] = sequence["next_quality_attempt"]["started_at"]
    references = {}
    for key, (role, start) in candidates.items():
        directory = directories.get(key) or directories.get(key.removeprefix("i"))
        if role not in AEROBIC_ROLES or directory is None:
            continue
        metadata = load_activity_metadata(directory)
        if not (metadata.get("trainer") or metadata.get("type") == "VirtualRide"):
            continue
        block = longest_indoor_power_block(directory, metadata)
        if block:
            local_start = metadata.get("start_date_local") or start
            moving = numeric(metadata, "moving_time")
            references[key] = {"date": local_start[:10],
                               "moving_minutes": round(moving / 60, 1) if moving is not None else None,
                               "longest_detected_steady_power_block": block}
            elapsed = numeric(metadata, "elapsed_time")
            if key in next_quality_starts and elapsed is not None and elapsed > 0:
                finish = parse_datetime(start) + timedelta(seconds=elapsed)
                gap = (parse_datetime(next_quality_starts[key]) - finish).total_seconds()
                if gap >= 0:
                    references[key]["finish_to_next_quality_minutes"] = round(gap / 60, 1)
    return references


def long_finish_references(events, directories, roles, cutoff):
    """Find a longer recorded indoor finish per recent role, with its actual follow-up."""
    prior = [e for e in events if parse_datetime(e["started_at"]).astimezone(cutoff.tzinfo).date() < cutoff.date()]
    longest = {}
    for index, event in enumerate(prior):
        role = event.get("completed_role")
        key = event["activity_id"]
        folder = directories.get(key) or directories.get(key.removeprefix("i"))
        if role not in roles or not folder:
            continue
        ride = load_activity_metadata(folder)
        if (not (ride.get("trainer") or ride.get("type") == "VirtualRide") or
                ride.get("icu_ignore_time") or ride.get("icu_ignore_power") or ride.get("ignore_parts")):
            continue
        tail = 0
        for interval in reversed(ride.get("icu_intervals") or []):
            if not isinstance(interval, dict):
                break
            if interval.get("type") == "WORK":
                if tail > longest.get(role, (0,))[0]:
                    longest[role] = (tail, index)
                break
            if interval.get("type") != "RECOVERY":
                break
            duration = numeric(interval, "elapsed_time")
            if duration is None or duration < 0:
                break
            tail += duration

    def reviewed(event):
        return {"activity_id": event["activity_id"], "started_at": event["started_at"],
                "role": event["completed_role"], "review": event.get("reason"),
                "result": (event.get("progression_update") or {}).get("last_result")}

    result = {}
    for role, (seconds, index) in longest.items():
        between = []
        next_quality = None
        for later in prior[index + 1:]:
            if later.get("completed_role") in QUALITY_ROLES or later.get("planned_role") in QUALITY_ROLES:
                next_quality = reviewed(later)
                break
            between.append(reviewed(later))
        result[role] = {"ride": reviewed(prior[index]), "post_work_minutes_including_cooldown": round(seconds / 60, 1),
                        "intervening_activities": between, "next_quality_attempt": next_quality}
    return result


def prior_quality_sequences(state, cutoff, activities_dir=DEFAULT_ARTIFACTS_DIR, *, aerobic_references=False):
    """Show the lead-in and observed follow-up of recent reviewed quality attempts."""
    directories = {p.parent.name.split("_", 1)[-1]: p.parent
                   for p in activities_dir.glob("*/activity.json")}
    recent = []
    activities_by_day = {}
    next_quality_session = None
    awaiting_previous = False
    counts = {}
    pairs = []
    events = sorted(state["activity_events"], key=lambda e: parse_datetime(e["started_at"]))
    for event in reversed(events):
        started = parse_datetime(event["started_at"])
        if started >= cutoff:
            continue
        if started < cutoff - timedelta(days=28):
            break
        key = event["activity_id"]
        folder = directories.get(key) or directories.get(key.removeprefix("i"))
        metadata = load_activity_metadata(folder) if folder else {}
        local_start = event.get("start_date_local") or metadata.get("start_date_local")
        activity_day = (parse_iso_datetime(local_start).date() if local_start
                        else started.astimezone(cutoff.tzinfo).date())
        elapsed = numeric(metadata, "elapsed_time")
        if elapsed is None and started.astimezone(cutoff.tzinfo).date() == cutoff.date():
            continue
        if elapsed is not None and started + timedelta(seconds=elapsed) > cutoff:
            continue
        role = event.get("planned_role")
        if role not in QUALITY_ROLES:
            role = event.get("completed_role")
        row = {"activity_id": key, "start": event["started_at"], "completed_role": event.get("completed_role"),
               "moving_minutes": numeric(metadata, "moving_time"), "session_rpe": metadata.get("icu_rpe"),
               "feel": metadata.get("feel")}
        if elapsed is not None:
            row["end"] = (started + timedelta(seconds=elapsed)).isoformat()
        for field in ("type", "trainer"):
            if metadata.get(field) is not None:
                row[field] = metadata[field]
        if not metadata.get("icu_ignore_power"):
            for field in ("icu_average_watts", "icu_weighted_avg_watts"):
                if metadata.get(field) is not None:
                    row[field] = metadata[field]
        if row["moving_minutes"] is not None:
            row["moving_minutes"] = round(row["moving_minutes"] / 60, 1)
        row.update(saved_context(folder, cutoff))
        report = athlete_report_at(folder, cutoff)
        if report:
            row["athlete_report"] = {field: report[field] for field in
                ("report", "reports", "athlete_report", "during_activity", "after_activity",
                 "reported_at", "recorded_at", "actual_intent", "late_response", "last_rep_effort",
                 "legs", "breathing", "reason_no_vt1_extension", "subsequent_recovery",
                 "actual_intake", "pre_training_soreness") if report.get(field) is not None}
        if recent:
            for pair in pairs:
                previous = pair.get("previous_activity")
                if previous and previous["activity_id"] == recent[-1]["activity_id"]:
                    pair["activity_before_previous"] = row.copy()
        if awaiting_previous:
            pairs[-1]["previous_activity"] = row.copy()
        awaiting_previous = False
        if role in QUALITY_ROLES:
            quality = {"attempt": row, "work_intervals": recorded_work_intervals(metadata),
                       "role_fulfilled": event.get("quality_role_fulfilled"),
                       "full_workout_completed": event.get("planned_workout_completed")}
            if counts.get(role, 0) < 2:
                following_day = activity_day + timedelta(days=1)
                pairs.append({"role": role, **quality, "previous_activity": None,
                              "following_day": {"date": following_day.isoformat(),
                                                "activities": list(reversed(activities_by_day.get(following_day, [])))},
                              "next_quality_session": next_quality_session})
                counts[role] = counts.get(role, 0) + 1
                awaiting_previous = True
            if row["completed_role"] in QUALITY_ROLES:
                next_quality_session = {"role": row["completed_role"], **quality}
        activities_by_day.setdefault(activity_day, []).append(row)
        recent.append(row)
    history = {"latest_activities": recent[:3], "quality_sequences": pairs,
               "long_finish_references": long_finish_references(events, directories, counts.keys(), cutoff)}
    current_answers = []
    for ride in recent:
        for answer in ride.get("athlete_answers", []):
            observed = answer["observed_at"]
            day = (observed if len(observed) == 10 else
                   parse_datetime(observed).astimezone(cutoff.tzinfo).date().isoformat())
            if day == cutoff.date().isoformat():
                current_answers.append(answer)
    history["current_day_athlete_answers"] = sorted(current_answers, key=lambda a: a["reported_at"])
    if aerobic_references:
        history["measured_indoor_aerobic_references"] = measured_aerobic_references(history, directories)
    return history


def ride_observations(directory, metadata, watts, cutoff):
    moving = numeric(metadata, "moving_time")
    elapsed = numeric(metadata, "elapsed_time")
    result = {
        "elapsed_minutes": round(elapsed / 60, 1) if elapsed is not None else None,
        "moving_minutes": round(moving / 60, 1) if moving is not None else None,
        "observed_minutes_near_working_power": None,
        "valid_power_minutes": None,
        "recorded_work_intervals": recorded_work_intervals(metadata),
        "whole_session_rpe": metadata.get("icu_rpe"),
        "feel": metadata.get("feel"),
        "athlete_report": None,
    }
    if directory is None:
        return result
    result.update(saved_context(directory, cutoff))
    report = athlete_report_at(directory, cutoff)
    if report:
        result["athlete_report"] = {
            key: report[key] for key in ("report", "reports", "athlete_report", "context", "late_response",
                                         "last_rep_effort", "subsequent_recovery", "during_activity",
                                         "after_activity", "actual_intent") if key in report
        } or None
        for key in ("whole_session_rpe", "feel"):
            if result[key] is None:
                result[key] = report.get(key)
    if watts is None or not (directory / "streams.csv").is_file() or not metadata:
        return result
    rows = load_activity(directory).streams
    clock = timeline(rows)
    if clock:
        low, high = vt1_power_band(watts)
        valid = matched = 0.0
        for row, seconds in zip(rows, clock[1]):
            power = numeric(row, "watts")
            if power is not None:
                valid += seconds
                if low <= power <= high:
                    matched += seconds
        result["valid_power_minutes"] = round(valid / 60, 1)
        if valid:
            result["observed_minutes_near_working_power"] = round(matched / 60, 1)
        result["matched_power_hr_windows"] = matched_windows(
            rows, ["heartrate"], power_band=(low, high),
        )
    return result


def dose_comparisons(state, role, watts, cutoff, activities_dir=DEFAULT_ARTIFACTS_DIR, *, selected_id=None):
    directories = {}
    if activities_dir.is_dir():
        for path in sorted(activities_dir.iterdir()):
            if path.is_dir():
                directories[path.name.split("_", 1)[-1]] = path
    candidates = []
    next_quality = None
    for event in reversed(state["activity_events"]):
        actual_role = event["completed_role"]
        quality = actual_role in QUALITY_ROLES or event.get("planned_role") in QUALITY_ROLES
        include_ride = actual_role == role and (len(candidates) < 3 or event["activity_id"] == selected_id)
        if not quality and not include_ride:
            continue
        started = parse_datetime(event["started_at"])
        if started >= cutoff:
            continue
        activity_id = event["activity_id"]
        directory = directories.get(activity_id) or directories.get(activity_id.removeprefix("i"))
        metadata = (load_activity_metadata(directory)
                    if directory and (directory / "activity.json").is_file() else {})
        elapsed = numeric(metadata, "elapsed_time")
        if elapsed is not None and started + timedelta(seconds=elapsed) > cutoff:
            continue
        if elapsed is None and started.astimezone(cutoff.tzinfo).date() == cutoff.date():
            continue
        sport = str(metadata.get("type") or "").lower()
        if include_ride and (not sport or "ride" in sport or "cycling" in sport):
            candidates.append({
                "activity_id": activity_id, "started_at": event["started_at"],
                "review": event["reason"], "evidence": event.get("evidence", []),
                **ride_observations(directory, metadata, watts, cutoff),
                "next_quality_session": next_quality,
                "finish_to_next_quality_minutes": (
                    round((parse_datetime(next_quality["started_at"]) - started -
                           timedelta(seconds=elapsed)).total_seconds() / 60, 1)
                    if next_quality and elapsed is not None else None
                ),
            })
            if len(candidates) >= 3 and (not selected_id or any(ride["activity_id"] == selected_id for ride in candidates)):
                break
        if quality:
            next_quality = {key: event.get(key) for key in (
                "activity_id", "started_at", "planned_role", "completed_role",
                "quality_role_fulfilled", "planned_workout_completed", "reason")}
            answers = saved_context(directory, cutoff).get("athlete_answers", [])
            if answers:
                next_quality["athlete_answers"] = answers
                next_quality["prior_review"] = next_quality.pop("reason")

    return {"role": role, "as_of": cutoff.isoformat(), "working_power_w": watts,
            "observation_band_w": vt1_power_band(watts) if watts is not None else None,
            "status": "available" if candidates else "no_reviewed_same_role_ride",
            "candidates": candidates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--role", choices=sorted(AEROBIC_ROLES))
    mode.add_argument("--quality-sequences", action="store_true",
                      help="Show quality attempts, their lead-in, following day and next quality session")
    parser.add_argument("--aerobic-references", action="store_true",
                        help="Include measured steady blocks from comparable indoor rides with --quality-sequences")
    parser.add_argument("--as-of", required=True, help="Decision cutoff, with UTC offset")
    parser.add_argument("--activity-id", help="Also include this older same-role comparison when eligible")
    parser.add_argument("--watts", type=float, help="Use today's chosen working power")
    args = parser.parse_args()
    state = load_plan_state(args.state)
    cutoff = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        parser.error("--as-of requires a UTC offset")
    if args.quality_sequences:
        if args.watts is not None or args.activity_id:
            parser.error("--watts and --activity-id apply to --role")
        print(json.dumps(prior_quality_sequences(state, cutoff, aerobic_references=args.aerobic_references),
                         indent=2, ensure_ascii=False))
        return
    if args.aerobic_references:
        parser.error("--aerobic-references requires --quality-sequences")
    watts = args.watts if args.watts is not None else state["progression"].get("vt1", {}).get("target_power_w")
    if watts is not None and not 0 < watts < float("inf"):
        parser.error("Working power must be finite and positive")
    print(json.dumps(dose_comparisons(state, args.role, watts, cutoff, selected_id=args.activity_id), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
