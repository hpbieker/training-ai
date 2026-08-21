"""Shared Xert authentication, request, parsing, and formatting helpers."""

from __future__ import annotations

import base64
import http.cookiejar
import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


XERT_API_BASE_URL = "https://www.xertonline.com"
XERT_FORECAST_PATH = "/calendar/training-forecast"
LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo
DEFAULT_XERT_OAUTH_CLIENT_ID = "xert_public"
DEFAULT_XERT_OAUTH_CLIENT_SECRET = "xert_public"


class CsrfTokenParser(HTMLParser):
    """Extract the Laravel CSRF token from Xert's login form."""

    def __init__(self) -> None:
        super().__init__()
        self.token: str | None = None

    @classmethod
    def from_html(cls, html: str) -> str | None:
        parser = cls()
        parser.feed(html)
        return parser.token

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        values = dict(attrs)
        if values.get("name") == "_token":
            self.token = values.get("value")

class ScriptTextParser(HTMLParser):
    """Collect script bodies from an HTML document."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self._in_script = False
        self._current: list[str] = []

    @classmethod
    def from_html(cls, html: str) -> list[str]:
        parser = cls()
        parser.feed(html)
        return parser.scripts

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self._in_script = True
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            self.scripts.append("".join(self._current))
            self._in_script = False
            self._current = []


@dataclass(frozen=True)

class XertCredentials:
    """Credentials for Xert API calls."""

    username: str | None = None
    password: str | None = None
    oauth_client_id: str = DEFAULT_XERT_OAUTH_CLIENT_ID
    oauth_client_secret: str = DEFAULT_XERT_OAUTH_CLIENT_SECRET

    def bearer_token(self) -> str:
        if self.username and self.password:
            token = request_xert_token(
                self.username,
                self.password,
                client_id=self.oauth_client_id,
                client_secret=self.oauth_client_secret,
            )
            return token["access_token"]
        raise ValueError("Set XERT_USERNAME and XERT_PASSWORD")

def request_xert_token(
    username: str,
    password: str,
    *,
    client_id: str = DEFAULT_XERT_OAUTH_CLIENT_ID,
    client_secret: str = DEFAULT_XERT_OAUTH_CLIENT_SECRET,
) -> dict[str, Any]:
    """Request an OAuth token from Xert."""

    client_auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode(
        "ascii"
    )
    body = urlencode(
        {
            "grant_type": "password",
            "username": username,
            "password": password,
        }
    ).encode("utf-8")
    request = Request(
        f"{XERT_API_BASE_URL}/oauth/token",
        data=body,
        headers={
            "Authorization": f"Basic {client_auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "xert-plugin/0.1 (+https://www.xertonline.com/API.html)",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert token request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise TypeError("Expected Xert token endpoint to return an access_token")
    return payload

def xert_web_login(*, username: str, password: str):
    """Return an opener with an authenticated xertonline.com web session."""

    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    auth_request = Request(
        f"{XERT_API_BASE_URL}/auth",
        headers={
            "User-Agent": "xert-plugin/0.1 (+Xert web login)",
        },
    )
    try:
        with opener.open(auth_request, timeout=60) as response:
            auth_html = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert auth page request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc

    token = CsrfTokenParser.from_html(auth_html)
    if not token:
        raise RuntimeError("Could not find Xert CSRF token on auth page")

    body = urlencode(
        {
            "_token": token,
            "username": username,
            "password": password,
        }
    ).encode("utf-8")
    login_request = Request(
        f"{XERT_API_BASE_URL}/auth/login",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "x-requested-with": "XMLHttpRequest",
            "User-Agent": "xert-plugin/0.1 (+Xert web login)",
        },
        method="POST",
    )
    try:
        with opener.open(login_request, timeout=60) as response:
            response.read()
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert web login failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc
    return opener

def _parse_xert_datetime(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None

def _coerce_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)

def _xert_calendar_date_iso(day: date) -> str:
    local_midnight = datetime.combine(day, time.min, tzinfo=LOCAL_TIMEZONE)
    return local_midnight.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00",
        "Z",
    )

def _open_text(opener, request: Request, label: str) -> str:
    try:
        with opener.open(request, timeout=60) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"{label} request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc

def _extract_script_json(
    html: str,
    key: str,
    *,
    additional_key: str | None = None,
) -> Any:
    for script in ScriptTextParser.from_html(html):
        if key not in script:
            continue
        if additional_key and additional_key not in script:
            continue
        json_text = _find_json_object(script, key)
        if json_text:
            return json.loads(json_text)
    return None

def _find_json_object(text: str, key: str) -> str | None:
    key_index = text.find(key)
    if key_index < 0:
        return None
    start = text.find("{", key_index)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None

def _nested_float(payload: dict[str, Any], *keys: str) -> float | None:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if isinstance(current, int | float):
        return float(current)
    return None

def _required_float(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, int | float):
        return float(value)
    raise TypeError(f"Expected numeric value for {key}")

def load_xert_credentials(env_path: str | Path = ".env") -> XertCredentials:
    """Load Xert credentials from a local dotenv-style file."""

    values = _load_env_values(env_path)
    return XertCredentials(
        username=values.get("XERT_USERNAME"),
        password=values.get("XERT_PASSWORD"),
        oauth_client_id=values.get("XERT_OAUTH_CLIENT_ID") or DEFAULT_XERT_OAUTH_CLIENT_ID,
        oauth_client_secret=(
            values.get("XERT_OAUTH_CLIENT_SECRET") or DEFAULT_XERT_OAUTH_CLIENT_SECRET
        ),
    )

def _request_json(
    path: str,
    access_token: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    query = f"?{urlencode(params)}" if params else ""
    request = Request(
        f"{XERT_API_BASE_URL}{path}{query}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "xert-plugin/0.1 (+https://www.xertonline.com/API.html)",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Xert request failed: HTTP {exc.code} {exc.reason}: {message}"
        ) from exc

def _extract_html_input_value(html_text: str, name: str) -> str | None:
    pattern = rf'<input\b[^>]*\bname="{re.escape(name)}"[^>]*>'
    match = re.search(pattern, html_text)
    if not match:
        return None
    value_match = re.search(r'\bvalue="([^"]*)"', match.group(0))
    if not value_match:
        return None
    return html.unescape(value_match.group(1))

def _extract_html_textarea_value(html_text: str, name: str) -> str | None:
    pattern = rf'<textarea\b[^>]*\bname="{re.escape(name)}"[^>]*>(.*?)</textarea>'
    match = re.search(pattern, html_text, flags=re.DOTALL)
    if not match:
        return None
    return html.unescape(match.group(1))

def _parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)

def _numeric_or_none(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None

def _round_optional(value: float | None, digits: int, *, scale: float | None = None) -> float | None:
    if value is None:
        return None
    if scale:
        value = value / scale
    return round(value, digits)

def _numbers_equal(value: Any, expected: float) -> bool:
    if not isinstance(value, int | float):
        return False
    return abs(float(value) - expected) < 1e-9

def _date_to_unix(value: str | date, *, end_of_day: bool = False) -> int:
    from datetime import datetime, time

    value_date = date.fromisoformat(value) if isinstance(value, str) else value
    value_time = time.max if end_of_day else time.min
    local_datetime = datetime.combine(value_date, value_time).astimezone()
    return int(local_datetime.timestamp())

def _date_to_string(value: str | date) -> str:
    return value.isoformat() if isinstance(value, date) else value

def _load_env_values(env_path: str | Path) -> dict[str, str]:
    path = Path(env_path)
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values
