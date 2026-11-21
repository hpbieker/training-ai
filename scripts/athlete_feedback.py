"""Save a verbatim observation for an existing activity and read it as of a decision."""
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from plan_state import DEFAULT_ARTIFACTS_DIR, parse_datetime


def save_answer(directory, activity_id, *, observed_at, reported_at, question, answer, context):
    metadata = json.loads((directory / "activity.json").read_text())
    if str(metadata["id"]) != activity_id:
        raise ValueError("Activity ID does not match the saved activity")
    reported = parse_datetime(reported_at, require_offset=True)
    if len(observed_at) == 10:
        if date.fromisoformat(observed_at) > datetime.fromisoformat(reported_at.replace("Z", "+00:00")).date():
            raise ValueError("Observation date follows the answer")
    elif parse_datetime(observed_at, require_offset=True) > reported:
        raise ValueError("Observation time follows the answer")
    if not all(value.strip() for value in (question, answer, context)):
        raise ValueError("Question, answer and observation context must be nonempty")
    entry = dict(activity_id=activity_id, observed_at=observed_at,
                 reported_at=reported.isoformat(), context=context, question=question, answer=answer)
    payload = json.dumps(entry, ensure_ascii=False, indent=2) + "\n"
    folder = directory / "athlete-answers"
    folder.mkdir(exist_ok=True)
    path = folder / (hashlib.sha256(payload.encode()).hexdigest() + ".json")
    with NamedTemporaryFile(dir=folder, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            tmp.write(payload.encode())
            tmp.flush()
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)
    return path


def saved_context(directory, cutoff):
    if directory is None:
        return {}
    answers = []
    for path in (directory / "athlete-answers").glob("*.json"):
        entry = json.loads(path.read_text())
        if parse_datetime(entry["reported_at"], require_offset=True) <= cutoff:
            answers.append(entry)
    evidence = {}
    if answers:
        evidence["athlete_answers"] = sorted(answers, key=lambda entry: entry["reported_at"])
    legacy_report = directory / "athlete-report.json"
    if legacy_report.is_file() and datetime.fromtimestamp(legacy_report.stat().st_mtime, timezone.utc) <= cutoff:
        report = json.loads(legacy_report.read_text())
        if not (report.get("recorded_at") or report.get("reported_at")):
            evidence["undated_athlete_report_file"] = str(legacy_report)
    analysis = directory / "analysis.md"
    if analysis.is_file() and datetime.fromtimestamp(analysis.stat().st_mtime, timezone.utc) <= cutoff:
        evidence["reviewed_analysis_file"] = str(analysis)
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activity-id", required=True)
    parser.add_argument("--observed-at", required=True, help="Observation date or timestamp with offset")
    parser.add_argument("--reported-at", required=True, help="Actual answer timestamp with offset")
    parser.add_argument("--context", required=True, help="What the observation refers to, e.g. second interval")
    parser.add_argument("--question", required=True)
    parser.add_argument("--answer", required=True)
    args = parser.parse_args()
    directories = [p.parent for p in DEFAULT_ARTIFACTS_DIR.glob("*/activity.json")
                   if p.parent.name.split("_", 1)[-1] == args.activity_id]
    if len(directories) != 1:
        parser.error("Expected exactly one saved activity for this ID")
    print(save_answer(directories[0], **vars(args)))
