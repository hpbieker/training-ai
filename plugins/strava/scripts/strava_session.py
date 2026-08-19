#!/usr/bin/env python3
"""Inspect, verify, or clear the persistent Strava browser session cache."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

from strava_cookie_from_curl import copied_curl_cookie
from strava_route_api import StravaError, StravaSession, default_cookie_file, validate_cookie_file


def metadata_path(cookie_file: Path) -> Path:
    return cookie_file.with_name("session.json")


def write_metadata(cookie_file: Path, **values: object) -> None:
    path = metadata_path(cookie_file)
    current: dict[str, object] = {}
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
    current.update(values)
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def import_curl(cookie_file: Path) -> dict[str, object]:
    result = subprocess.run(["pbpaste"], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise StravaError(result.stderr.strip() or "Could not read the clipboard.")
    cookie = copied_curl_cookie(result.stdout)
    cookie_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(cookie_file.parent, 0o700)
    temporary = cookie_file.with_name(cookie_file.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(cookie + "\n")
    os.replace(temporary, cookie_file)
    os.chmod(cookie_file, 0o600)
    with StravaSession(cookie_file) as session:
        auth = session.authenticate()
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    write_metadata(cookie_file, imported_at=now, last_verified_at=now, source="safari-copy-as-curl")
    return {"stored": True, "verified": True, "cookie_file": str(cookie_file), **auth}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("import-curl", "status", "clear"))
    parser.add_argument("--cookie-file", type=Path, default=default_cookie_file())
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="For status, validate the file and permissions without contacting Strava.",
    )
    args = parser.parse_args()
    args.cookie_file = args.cookie_file.expanduser()

    if args.command == "clear":
        existed = args.cookie_file.exists()
        args.cookie_file.unlink(missing_ok=True)
        metadata_path(args.cookie_file).unlink(missing_ok=True)
        print(json.dumps({"cleared": existed, "cookie_file": str(args.cookie_file.expanduser())}))
        return 0

    try:
        if args.command == "import-curl":
            print(json.dumps(import_curl(args.cookie_file), ensure_ascii=False))
            return 0
        cookie_file = validate_cookie_file(args.cookie_file)
        if args.local_only:
            payload = {"stored": True, "verified": False, "cookie_file": str(cookie_file), "mode": "0600"}
        else:
            with StravaSession(cookie_file) as session:
                payload = {"stored": True, "verified": True, **session.authenticate()}
            write_metadata(cookie_file, last_verified_at=dt.datetime.now(dt.timezone.utc).isoformat())
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    except (OSError, StravaError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
