"""Dated athlete instructions shared by interactive and scheduled coaching."""
import argparse
from contextlib import closing
from datetime import date, datetime, timezone
import json
import sqlite3

from plan_state import DEFAULT_STATE_PATH, QUALITY_ROLES, parse_datetime


DATABASE = DEFAULT_STATE_PATH.with_name("day-constraints.sqlite3")
GOALS = {"vt1", "recovery"} | QUALITY_ROLES


def timestamp(value):
    return parse_datetime(value, require_offset=True).isoformat(timespec="microseconds")


def required_text(value):
    if not value.strip():
        raise ValueError("Evidence and source references must contain text")
    return value.strip()


def record(db, day, quote, source, reported_at, exclude=(), release_condition=None):
    quote, source = required_text(quote), required_text(source)
    reported_at = timestamp(reported_at)
    goals = set(exclude)
    if "quality" in goals:
        goals = (goals - {"quality"}) | QUALITY_ROLES
    if goals - GOALS:
        raise ValueError("Unknown excluded training goal")
    if release_condition is not None:
        release_condition = required_text(release_condition)
    values = (day.isoformat(), quote, source, reported_at, json.dumps(sorted(goals)), release_condition)
    db.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS constraints_by_day (
            id INTEGER PRIMARY KEY, day TEXT NOT NULL, quote TEXT NOT NULL, source TEXT NOT NULL,
            reported_at TEXT NOT NULL, excluded TEXT NOT NULL, release_condition TEXT,
            released_at TEXT, release_kind TEXT, release_evidence TEXT, release_source TEXT,
            UNIQUE(day, source, reported_at, quote))""")
        conn.execute("""INSERT INTO constraints_by_day(day, quote, source, reported_at, excluded, release_condition)
            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(day, source, reported_at, quote) DO NOTHING""", values)
        key, excluded, condition = conn.execute("""SELECT id, excluded, release_condition FROM constraints_by_day
            WHERE day=? AND quote=? AND source=? AND reported_at=?""", values[:4]).fetchone()
        if (excluded, condition) != values[4:]:
            raise ValueError("This statement is already recorded with different terms")
        return key


def release(db, key, kind, evidence, source, reported_at):
    evidence, source = required_text(evidence), required_text(source)
    reported_at = timestamp(reported_at)
    if not db.exists():
        raise ValueError("Unknown constraint")
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""SELECT reported_at, quote, release_condition, released_at,
            release_kind, release_evidence, release_source FROM constraints_by_day WHERE id=?""", (key,)).fetchone()
        if not row:
            raise ValueError("Unknown constraint")
        if kind not in {"athlete", "condition"} or (kind == "condition" and not row[2]):
            raise ValueError("This constraint needs a later statement from the athlete")
        if reported_at <= row[0] or evidence == row[1]:
            raise ValueError("Provide new evidence dated after the original statement")
        proof = (reported_at, kind, evidence, source)
        if row[3:] == proof:
            return
        if row[3] is not None:
            raise ValueError("Already released with different evidence")
        conn.execute("""UPDATE constraints_by_day SET released_at=?, release_kind=?, release_evidence=?,
            release_source=? WHERE id=?""", (*proof, key))


def for_day(db, day, as_of):
    if not db.exists():
        return []
    cutoff = timestamp(as_of)
    with closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM constraints_by_day WHERE day=? AND reported_at<=? ORDER BY reported_at, id",
                            (day.isoformat(), cutoff))
        result = []
        for row in rows:
            item = {field: row[field] for field in ("id", "day", "quote", "source", "reported_at", "release_condition")}
            item["excluded_goals"] = json.loads(row["excluded"])
            item["active"] = row["released_at"] is None or row["released_at"] > cutoff
            if not item["active"]:
                item["release"] = {field: row["release_" + field] for field in ("kind", "source", "evidence")}
                item["release"]["reported_at"] = row["released_at"]
            result.append(item)
        return result


def check_candidate(entries, goal, planned_quality=False):
    goal = {"easy_vt1": "vt1", "active_recovery": "recovery"}.get(goal, goal)
    for entry in entries:
        excluded = set(entry["excluded_goals"])
        if entry["active"] and (goal in excluded or (planned_quality and QUALITY_ROLES <= excluded)):
            raise ValueError(f"Dated athlete constraint #{entry['id']} for {entry['day']}: {entry['quote']} "
                             f"({entry['source']}). Choose a permitted workout or record evidence of a change.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    show = commands.add_parser("show", help="Read the athlete's instructions before choosing a workout")
    add = commands.add_parser("record", help="Capture an explicit dated constraint from the athlete")
    lift = commands.add_parser("release", help="Record evidence that one specific constraint has ended")
    for command in (show, add):
        command.add_argument("--date", type=date.fromisoformat, required=True)
    show.add_argument("--as-of", default=datetime.now(timezone.utc).isoformat())
    for command in (add, lift):
        command.add_argument("--source", required=True)
        command.add_argument("--reported-at", required=True)
    add.add_argument("--quote", required=True)
    add.add_argument("--exclude", nargs="+", choices=sorted(GOALS | {"quality"}), default=[])
    add.add_argument("--release-condition", help="Verifiable condition explicitly specified by the athlete")
    lift.add_argument("--id", type=int, required=True)
    lift.add_argument("--kind", choices=("athlete", "condition"), required=True)
    lift.add_argument("--evidence", required=True)
    args = parser.parse_args()
    try:
        if args.command == "show":
            print(json.dumps(for_day(DATABASE, args.date, args.as_of), ensure_ascii=False, indent=2))
        elif args.command == "record":
            print(record(DATABASE, args.date, args.quote, args.source, args.reported_at, args.exclude,
                         args.release_condition))
        else:
            release(DATABASE, args.id, args.kind, args.evidence, args.source, args.reported_at)
    except (ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
