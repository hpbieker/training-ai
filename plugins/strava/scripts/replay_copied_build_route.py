#!/usr/bin/env python3
"""Replay browser-authenticated Strava route-builder requests without storing secrets.

The full copied cURL is read from the macOS clipboard at runtime as the auth
source. Cookie and CSRF are extracted in memory only. Request bodies can be read
from a file or extracted from the copied cURL because they do not contain auth
material.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ENDPOINTS = {
    "build": "https://www.strava.com/api/next/data/routes/build-route",
    "create": "https://www.strava.com/api/next/data/routes/create-route",
    "update": "https://www.strava.com/api/next/data/routes/update-route",
}


def pbpaste() -> str:
    result = subprocess.run(["pbpaste"], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise SystemExit("pbpaste failed; this script must run on macOS.")
    return result.stdout


def extract_single_quoted_arg(raw: str, flag_pattern: str) -> str | None:
    # Handles Safari/DevTools cURL where header/data args are single quoted.
    match = re.search(flag_pattern + r"\s+'((?:\\'|[^'])*)'", raw, re.S)
    if not match:
        match = re.search(flag_pattern + r'\s+"((?:\\"|[^"])*)"', raw, re.S)
    if not match:
        return None
    return bytes(match.group(1), "utf-8").decode("unicode_escape")


def extract_header(raw: str, name: str) -> str | None:
    pattern = rf"(?:-H|--header)\s+'{re.escape(name)}:\s*([^']*)'"
    match = re.search(pattern, raw, re.I | re.S)
    if not match:
        pattern = rf'(?:-H|--header)\s+"{re.escape(name)}:\s*([^"]*)"'
        match = re.search(pattern, raw, re.I | re.S)
    return match.group(1).strip() if match else None


def extract_body(raw: str) -> str:
    body = extract_single_quoted_arg(raw, r"(?:--data-raw|--data-binary|--data)")
    if body is None:
        raise SystemExit("Could not find --data-raw/--data-binary JSON body in clipboard cURL.")
    try:
        json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Copied cURL body is not valid JSON: {exc}") from exc
    return body


def redact(text: str) -> str:
    text = re.sub(r"(?im)^(> Cookie: ).*$", r"\1<redacted>", text)
    text = re.sub(r"(?im)^(\* \[HTTP/2\] \[\d+\] \[cookie: ).*(\])$", r"\1<redacted>\2", text)
    text = re.sub(r"(?im)^(> x-csrf-token: ).*$", r"\1<redacted>", text)
    text = re.sub(
        r"(?im)^(\* \[HTTP/2\] \[\d+\] \[x-csrf-token: ).*(\])$",
        r"\1<redacted>\2",
        text,
    )
    return text


def replay(
    raw: str,
    endpoint: str,
    out: Path,
    verbose_log: Path,
    body_out: Path | None,
    body_in: Path | None,
) -> dict:
    cookie = extract_header(raw, "Cookie")
    csrf = extract_header(raw, "x-csrf-token") or extract_header(raw, "X-CSRF-Token")
    body = body_in.read_text() if body_in else extract_body(raw)
    try:
        json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Request body is not valid JSON: {exc}") from exc
    if not cookie:
        raise SystemExit("Copied cURL does not contain a Cookie header.")
    if not csrf:
        raise SystemExit("Copied cURL does not contain an x-csrf-token header.")
    if body_out:
        body_out.write_text(body)

    with tempfile.TemporaryDirectory(prefix="strava-build-replay-") as tmp:
        body_file = Path(tmp) / "body.json"
        body_file.write_text(body)
        cmd = [
            "curl",
            ENDPOINTS[endpoint],
            "-X",
            "POST",
            "-H",
            "Content-Type: application/json",
            "-H",
            "Accept: application/json, text/plain, */*",
            "-H",
            "Accept-Encoding: identity",
            "-H",
            "Origin: https://www.strava.com",
            "-H",
            "Referer: https://www.strava.com/maps/create",
            "-H",
            "X-Requested-With: XMLHttpRequest",
            "-H",
            f"x-csrf-token: {csrf}",
            "-H",
            f"Cookie: {cookie}",
            "--data-binary",
            f"@{body_file}",
            "-v",
            "-o",
            str(out),
        ]
        result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    verbose_log.write_text(redact(result.stderr))
    if result.returncode != 0:
        raise SystemExit(f"curl failed: {result.returncode}")
    try:
        parsed = json.loads(out.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Strava response was not JSON. See {out} and {verbose_log}: {exc}") from exc
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", choices=sorted(ENDPOINTS), default="build")
    parser.add_argument("--body-in", type=Path, help="Use this JSON body instead of the copied cURL body.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verbose-log", type=Path, required=True)
    parser.add_argument("--body-out", type=Path)
    args = parser.parse_args()

    raw = pbpaste()
    if "strava.com" not in raw:
        raise SystemExit("Clipboard does not look like a Strava cURL request.")
    if not args.body_in and "build-route" not in raw:
        raise SystemExit("Clipboard does not contain a build-route body; pass --body-in.")
    parsed = replay(raw, args.endpoint, args.out, args.verbose_log, args.body_out, args.body_in)
    print(
        json.dumps(
            {
                "endpoint": args.endpoint,
                "buildRoute": len(parsed.get("buildRoute", [])),
                "createRoute": parsed.get("createRoute"),
                "updateRoute": parsed.get("updateRoute"),
                "out": str(args.out),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
