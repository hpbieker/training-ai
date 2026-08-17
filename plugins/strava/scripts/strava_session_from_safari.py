#!/usr/bin/env python3
"""Bootstrap a private Strava Cookie header through curl-safari."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


STRAVA_URL = "https://www.strava.com/athlete/training"
REQUIRED_COOKIE = "_strava4_session"


def find_curl_safari(explicit: Path | None) -> Path:
    if explicit is not None:
        candidates = [explicit]
    else:
        on_path = shutil.which("curl-safari")
        candidates = [Path(on_path)] if on_path else []
        cache = Path.home() / ".codex/plugins/cache/curl-safari-local/curl-safari"
        candidates.extend(sorted(cache.glob("*/bin/curl-safari"), reverse=True))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    raise ValueError("Could not find an executable curl-safari; pass --curl-safari explicitly.")


def cookie_header_from_jar(path: Path, host: str = "www.strava.com") -> tuple[str, list[str]]:
    cookies: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line
        if line.startswith("#HttpOnly_"):
            line = line.removeprefix("#HttpOnly_")
        elif not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        domain, _include_subdomains, _path, _secure, _expires, name, value = fields
        normalized_domain = domain.lstrip(".").casefold()
        if host.casefold() == normalized_domain or host.casefold().endswith("." + normalized_domain):
            cookies[name] = value
    if REQUIRED_COOKIE not in cookies:
        raise ValueError(f"curl-safari did not provide the required {REQUIRED_COOKIE} cookie.")
    names = sorted(cookies)
    return "Cookie: " + "; ".join(f"{name}={cookies[name]}" for name in names), names


def write_private(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content + "\n")
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--curl-safari", type=Path, help="Explicit curl-safari executable")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/private/tmp/strava-cookie.headers"),
        help="Private output header file",
    )
    args = parser.parse_args()
    try:
        executable = find_curl_safari(args.curl_safari)
        with tempfile.TemporaryDirectory(prefix="strava-safari-") as temporary:
            jar = Path(temporary) / "cookies.txt"
            result = subprocess.run(
                [
                    str(executable),
                    "-sS",
                    "-L",
                    "--cookie-jar",
                    str(jar),
                    "--output",
                    "/dev/null",
                    "--write-out",
                    "%{http_code}\n%{url_effective}",
                    STRAVA_URL,
                ],
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
            if result.returncode != 0:
                raise ValueError(result.stderr.strip() or f"curl-safari failed with {result.returncode}.")
            lines = result.stdout.strip().splitlines()
            if (
                len(lines) < 2
                or lines[-2] != "200"
                or "/login" in lines[-1]
                or "/athlete/training" not in lines[-1]
            ):
                raise ValueError("curl-safari did not establish an authenticated Strava session.")
            header, names = cookie_header_from_jar(jar)
            write_private(args.output, header)
        print(json.dumps({
            "authenticated": True,
            "cookie_file": str(args.output.resolve()),
            "cookie_names": names,
            "mode": "0600",
            "source": "curl-safari",
        }))
        return 0
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
