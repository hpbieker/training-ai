#!/usr/bin/env python3
"""Call authenticated Strava endpoints with Python and a private Cookie file."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


CREATE_URL = (
    "https://www.strava.com/maps/create?"
    "sport=Ride&style=standard&terrain=false&labels=true&poi=true&cPhotos=true&3d=false"
)
AUTH_CHECK_URL = "https://www.strava.com/athlete/training"
ENDPOINTS = {
    "build": "https://www.strava.com/api/next/data/routes/build-route",
    "create": "https://www.strava.com/api/next/data/routes/create-route",
    "update": "https://www.strava.com/api/next/data/routes/update-route",
}
DEFAULT_COOKIE_FILE = Path.home() / ".strava" / "session.headers"


def default_cookie_file() -> Path:
    """Resolve an explicit environment override before the persistent default."""
    value = os.environ.get("STRAVA_COOKIE_FILE")
    return Path(value).expanduser() if value else DEFAULT_COOKIE_FILE


class StravaError(RuntimeError):
    """A verified Strava transport or response failure."""


class StravaSession:
    def __init__(self, cookie_file: Path, header_file: Path | None = None):
        self.cookie_file = validate_cookie_file(cookie_file)
        self.header_file = validate_header_file(header_file) if header_file else None
        self.cookie_header = self.cookie_file.read_text(encoding="utf-8").strip().split(":", 1)[1].strip()
        self.base_headers = self._read_header_file(self.header_file)
        self._tmp = tempfile.TemporaryDirectory(prefix="strava-session-")
        self.tmp_dir = Path(self._tmp.name)
        self.csrf: str | None = None
        self.athlete_id: int | None = None

    def close(self) -> None:
        self._tmp.cleanup()

    def __enter__(self) -> "StravaSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _read_header_file(path: Path | None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if path is None:
            return headers
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            if ":" not in line:
                raise StravaError(f"Invalid header line in {path}.")
            name, value = line.split(":", 1)
            headers[name.strip()] = value.strip()
        return headers

    @staticmethod
    def _header_dict(headers: list[str] | None) -> dict[str, str]:
        result: dict[str, str] = {}
        for header in headers or []:
            if ":" not in header:
                raise StravaError(f"Invalid HTTP header: {header!r}")
            name, value = header.split(":", 1)
            result[name.strip()] = value.strip()
        return result

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: list[str] | None = None,
        data: bytes | None = None,
        secret_headers: list[str] | None = None,
        verbose_log: Path | None = None,
    ) -> tuple[bytes, int, str]:
        request_headers = {
            "Accept-Encoding": "identity",
            **self.base_headers,
            **self._header_dict(headers),
            **self._header_dict(secret_headers),
            "Cookie": self.cookie_header,
        }
        request = urllib.request.Request(
            url,
            data=data,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
                status = response.status
                effective_url = response.geturl()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            preview = body.decode("utf-8", errors="ignore")[:500].strip()
            detail = f": {preview}" if preview else ""
            if exc.code in {401, 403}:
                raise StravaError(f"Strava authentication failed with HTTP {exc.code}{detail}") from exc
            raise StravaError(f"Strava request failed with HTTP {exc.code}{detail}") from exc
        except urllib.error.URLError as exc:
            raise StravaError(f"Strava request failed: {exc.reason}") from exc
        if verbose_log is not None:
            verbose_log.write_text(
                json.dumps({"method": method, "url": url, "status": status, "effective_url": effective_url})
            )
        return body, status, effective_url

    def _run(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: list[str] | None = None,
        body_path: Path | None = None,
        out_path: Path,
        verbose_log: Path | None = None,
        secret_headers: list[str] | None = None,
    ) -> tuple[int, str]:
        body, status, effective_url = self.request(
            url,
            method=method,
            headers=headers,
            data=body_path.read_bytes() if body_path is not None else None,
            secret_headers=secret_headers,
            verbose_log=verbose_log,
        )
        out_path.write_bytes(body)
        return status, effective_url

    def authenticate(self) -> dict[str, Any]:
        training_page = self.tmp_dir / "training.html"
        _, effective_url = self._run(AUTH_CHECK_URL, out_path=training_page)
        if re.search(r"/login(?:[/?#]|$)", effective_url):
            raise StravaError(
                "Strava login is required. The Cookie header file did not provide an "
                "authenticated www.strava.com session."
            )
        training_text = training_page.read_text(encoding="utf-8", errors="ignore")
        athlete_matches = re.findall(r'href=["\']/athletes/(\d+)(?:[/?"\'])', training_text)
        if not athlete_matches:
            athlete_matches = re.findall(r'athleteId[\\":\s]+(\d+)', training_text)
        if not athlete_matches:
            raise StravaError("Authenticated Strava page did not expose an athlete ID.")

        builder_page = self.tmp_dir / "route-builder.html"
        self._run(CREATE_URL, out_path=builder_page)
        builder_text = builder_page.read_text(encoding="utf-8", errors="ignore")
        csrf_match = re.search(r'<meta name="csrf" content="([^"]+)"', builder_text)
        if not csrf_match:
            raise StravaError("Authenticated Strava Route Builder page did not expose a CSRF token.")
        self.csrf = html.unescape(csrf_match.group(1))
        self.athlete_id = int(athlete_matches[0])
        return {
            "authenticated": True,
            "athlete_id": self.athlete_id,
            "transport": "python-cookie-file",
        }

    def api(
        self,
        endpoint: str,
        body_path: Path,
        out_path: Path,
        verbose_log: Path | None = None,
    ) -> dict[str, Any]:
        if endpoint not in ENDPOINTS:
            raise StravaError(f"Unsupported Strava endpoint: {endpoint}")
        if self.csrf is None:
            self.authenticate()
        self._run(
            ENDPOINTS[endpoint],
            method="POST",
            headers=[
                "Content-Type: application/json",
                "Accept: application/json, text/plain, */*",
                "Accept-Encoding: identity",
                "Origin: https://www.strava.com",
                f"Referer: {CREATE_URL}",
                "X-Requested-With: XMLHttpRequest",
            ],
            secret_headers=[f"x-csrf-token: {self.csrf}"],
            body_path=body_path,
            out_path=out_path,
            verbose_log=verbose_log,
        )
        try:
            payload = json.loads(out_path.read_text())
        except json.JSONDecodeError as exc:
            raise StravaError(f"Strava returned non-JSON content in {out_path}.") from exc
        if not isinstance(payload, dict):
            raise StravaError("Strava returned an unexpected JSON response.")
        return payload

    def fetch_route_page(self, route_id: str, out_path: Path) -> str:
        self._run(f"https://www.strava.com/routes/{route_id}", out_path=out_path)
        return out_path.read_text(encoding="utf-8", errors="ignore")


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


def validate_private_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise StravaError(f"{label} does not exist: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise StravaError(f"{label} must not be accessible by group or others: {path}")
    return path.resolve()


def validate_cookie_file(path: Path) -> Path:
    path = validate_private_file(path, "Cookie file")
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1 or not re.fullmatch(r"Cookie:\s*\S.*", lines[0], re.IGNORECASE):
        raise StravaError("Cookie file must contain exactly one `Cookie: name=value; ...` header.")
    return path


def validate_header_file(path: Path) -> Path:
    path = validate_private_file(path, "Header file")
    text = path.read_text(encoding="utf-8")
    if re.search(r"(?im)^\s*(cookie|authorization|x-csrf-token)\s*:", text):
        raise StravaError("Header file must not contain Cookie, Authorization, or CSRF headers.")
    return path


def validate_json(path: Path) -> None:
    try:
        json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("endpoint", choices=("auth", *sorted(ENDPOINTS)))
    parser.add_argument("body", type=Path, nargs="?", help="Cookie-free JSON request body.")
    parser.add_argument(
        "--cookie-file",
        type=Path,
        default=default_cookie_file(),
        help="Mode-0600 Cookie header file (default: STRAVA_COOKIE_FILE or ~/.strava/session.headers).",
    )
    parser.add_argument(
        "--header-file",
        type=Path,
        help="Optional private file of additional non-secret browser headers.",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verbose-log", type=Path)
    args = parser.parse_args()

    if args.endpoint != "auth":
        if args.body is None or args.out is None:
            parser.error("body and --out are required for Route Builder API calls")
        validate_json(args.body)

    try:
        with StravaSession(args.cookie_file, args.header_file) as session:
            auth = session.authenticate()
            if args.endpoint == "auth":
                print(json.dumps(auth, ensure_ascii=False))
                return 0
            payload = session.api(args.endpoint, args.body, args.out, args.verbose_log)
            print(json.dumps({"out": str(args.out), "response": payload}, ensure_ascii=False))
            return 0
    except StravaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
