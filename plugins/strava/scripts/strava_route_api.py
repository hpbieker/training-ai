#!/usr/bin/env python3
"""Call Strava route-builder APIs with Safari-authenticated curl.

This intentionally does not accept or store Cookie headers. Authentication is
provided by curl-safari at runtime, and CSRF is fetched from a fresh Strava page.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CURL_SAFARI = Path("/Users/hanspetterbieker/sources/curl-safari/bin/curl-safari")
CREATE_URL = (
    "https://www.strava.com/maps/create?"
    "sport=Ride&style=standard&terrain=false&labels=true&poi=true&cPhotos=true&3d=false"
)
ENDPOINTS = {
    "build": "https://www.strava.com/api/next/data/routes/build-route",
    "create": "https://www.strava.com/api/next/data/routes/create-route",
    "update": "https://www.strava.com/api/next/data/routes/update-route",
}


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def fetch_csrf() -> str:
    with tempfile.TemporaryDirectory(prefix="strava-csrf-") as tmp:
        page = Path(tmp) / "create.html"
        result = run([str(CURL_SAFARI), "-L", CREATE_URL, "-o", str(page)])
        if result.returncode != 0:
            sys.stderr.write(result.stderr)
            raise SystemExit(f"curl-safari failed while fetching CSRF: {result.returncode}")
        html = page.read_text(errors="ignore")
    match = re.search(r'<meta name="csrf" content="([^"]+)"', html)
    if not match:
        raise SystemExit("Could not find Strava CSRF meta tag. Is Safari logged into Strava?")
    return match.group(1)


def call_api(endpoint: str, body_path: Path, out_path: Path, verbose_log: Path | None) -> None:
    csrf = fetch_csrf()
    cmd = [
        str(CURL_SAFARI),
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
        f"Referer: {CREATE_URL}",
        "-H",
        "X-Requested-With: XMLHttpRequest",
        "-H",
        f"x-csrf-token: {csrf}",
        "--data-binary",
        f"@{body_path}",
        "-o",
        str(out_path),
    ]
    if verbose_log:
        cmd.extend(["-v"])
    result = run(cmd)
    if verbose_log:
        redacted = redact_secrets(result.stderr)
        verbose_log.write_text(redacted)
    if result.returncode != 0:
        sys.stderr.write(redact_secrets(result.stderr))
        raise SystemExit(f"Strava API call failed: {result.returncode}")


def redact_secrets(text: str) -> str:
    text = re.sub(r"(?im)^(> Cookie: ).*$", r"\1<redacted>", text)
    text = re.sub(r"(?im)^(\* \[HTTP/2\] \[\d+\] \[cookie: ).*(\])$", r"\1<redacted>\2", text)
    text = re.sub(r"(?im)^(> x-csrf-token: ).*$", r"\1<redacted>", text)
    text = re.sub(
        r"(?im)^(\* \[HTTP/2\] \[\d+\] \[x-csrf-token: ).*(\])$",
        r"\1<redacted>\2",
        text,
    )
    return text


def validate_json(path: Path) -> None:
    try:
        json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("endpoint", choices=sorted(ENDPOINTS))
    parser.add_argument("body", type=Path, help="Cookie-free JSON request body.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verbose-log", type=Path)
    args = parser.parse_args()

    validate_json(args.body)
    call_api(args.endpoint, args.body, args.out, args.verbose_log)
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
