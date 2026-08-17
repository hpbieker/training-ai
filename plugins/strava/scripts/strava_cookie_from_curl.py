#!/usr/bin/env python3
"""Extract a Strava Cookie header from browser "Copy as cURL" input safely."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def copied_curl_cookie(command: str) -> str:
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"Could not parse copied cURL: {exc}") from exc
    if not tokens or Path(tokens[0]).name != "curl":
        raise ValueError("Input must be a browser-copied curl command.")
    headers: list[str] = []
    cookie_values: list[str] = []
    for index, token in enumerate(tokens[:-1]):
        option = token.strip()
        if option in {"-H", "--header"}:
            headers.append(tokens[index + 1])
        elif option in {"-b", "--cookie"}:
            cookie_values.append(tokens[index + 1])
    cookies = [header for header in headers if re.match(r"(?i)^cookie\s*:", header)]
    cookies.extend(f"Cookie: {value}" for value in cookie_values)
    if len(cookies) != 1:
        raise ValueError(f"Expected exactly one Cookie header or --cookie value, found {len(cookies)}.")
    cookie = re.sub(r"(?i)^cookie\s*:\s*", "Cookie: ", cookies[0], count=1)
    if not re.fullmatch(r"Cookie:\s*\S.*", cookie):
        raise ValueError("The copied Cookie header is empty or invalid.")
    return cookie


def read_input(args: argparse.Namespace) -> str:
    if args.clipboard:
        result = subprocess.run(["pbpaste"], text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise ValueError(result.stderr.strip() or "Could not read the clipboard.")
        return result.stdout
    if args.input_file:
        return args.input_file.read_text(encoding="utf-8")
    return sys.stdin.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--clipboard", action="store_true", help="Read copied cURL from the macOS clipboard")
    source.add_argument("--input-file", type=Path, help="Read copied cURL from a file")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/private/tmp/strava-cookie.headers"),
        help="Private output file (default: /private/tmp/strava-cookie.headers)",
    )
    args = parser.parse_args()
    try:
        cookie = copied_curl_cookie(read_input(args))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(cookie + "\n")
        os.chmod(args.output, 0o600)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"cookie_file": str(args.output.resolve()), "mode": "0600"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
