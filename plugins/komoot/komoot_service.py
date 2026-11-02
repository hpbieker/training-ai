#!/usr/bin/env python3
"""Read and export Komoot tours through the curl-safari cookie socket."""

from __future__ import annotations

import json
import os
import re
import socket
import tempfile
import time
from http.cookiejar import Cookie, CookieJar
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


FIT_API_ROOT = "https://www.komoot.com/api/v007/tours"
API_ROOT = "https://www.komoot.com/api/v007"
WEB_ROOT = "https://www.komoot.com"
DEFAULT_COOKIE_SOCKET = "/private/tmp/curl-safari.sock"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2]


class KomootError(RuntimeError):
    """A Komoot request, authentication, or file operation failed."""


def parse_tour_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"\d+", value):
        return value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"komoot.com", "www.komoot.com"}:
        raise ValueError("tour must be a numeric Komoot tour ID or a Komoot tour URL")
    match = re.fullmatch(r"(?:/[a-z]{2}(?:-[a-z]{2})?)?/tour/(\d+)(?:/.*)?", parsed.path, re.IGNORECASE)
    if not match:
        raise ValueError("tour URL must contain /tour/<numeric-id>")
    return match.group(1)


def _cookie_jar(url: str) -> CookieJar:
    host = urllib.parse.urlparse(url).hostname
    if not host:
        raise KomootError("Could not determine the Komoot API hostname")
    socket_path = os.environ.get("CURL_SAFARI_SOCKET_PATH", DEFAULT_COOKIE_SOCKET)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(10)
            client.connect(socket_path)
            client.sendall(json.dumps({"op": "fetch", "domain": host, "url": url}).encode("utf-8") + b"\n")
            with client.makefile("rb") as reader:
                response = reader.readline(1_048_577)
    except OSError as exc:
        raise KomootError(f"Could not read Safari cookies through the curl-safari socket: {exc}") from exc

    try:
        payload = json.loads(response) if len(response) <= 1_048_576 else None
    except (ValueError, UnicodeError):
        payload = None
    if not isinstance(payload, dict) or payload.get("ok") is not True or not isinstance(payload.get("cookie_jar"), str):
        raise KomootError("curl-safari did not return a valid cookie jar")

    now = int(time.time())
    jar = CookieJar()
    for line in payload["cookie_jar"].splitlines():
        http_only = line.startswith("#HttpOnly_")
        fields = line.removeprefix("#HttpOnly_").split("\t")
        if len(fields) != 7 or fields[0].startswith("#"):
            continue
        domain, include_subdomains, path, secure, expiry_raw, name, value = fields
        domain = domain.lower()
        bare_domain = domain.lstrip(".")
        if not (host == bare_domain or host.endswith("." + bare_domain)):
            continue
        try:
            expiry = int(expiry_raw) if expiry_raw and expiry_raw != "0" else None
        except ValueError:
            expiry = None
        if expiry is not None and expiry <= now:
            continue
        domain_specified = include_subdomains.upper() == "TRUE"
        rest = {"HttpOnly": None} if http_only else {}
        jar.set_cookie(Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain=domain, domain_specified=domain_specified,
            domain_initial_dot=domain.startswith("."), path=path or "/",
            path_specified=True, secure=secure.upper() == "TRUE", expires=expiry,
            discard=expiry is None, comment=None, comment_url=None, rest=rest,
            rfc2109=False,
        ))
    if not list(jar):
        raise KomootError(f"No Safari cookies are available for {host}; sign in to Komoot in Safari and retry")
    return jar


def _request_bytes(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    accept: str = "application/hal+json,application/json",
    content_type: str | None = None,
) -> bytes:
    headers = {"Accept": accept, "User-Agent": "training-ai-komoot-mcp/0.1.5"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar(url)))
        # Safari may only hold Komoot's long-lived refresh cookies. A normal
        # home-page request exchanges these for short-lived API session cookies.
        # Keep Set-Cookie updates in this same in-memory opener for the API call.
        # This is session initialization, not a retry after a failed request.
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname == "www.komoot.com" and parsed.path.startswith("/api/"):
            bootstrap = urllib.request.Request(
                f"{WEB_ROOT}/", headers={"Accept": "text/html", "User-Agent": headers["User-Agent"]},
            )
            with opener.open(bootstrap, timeout=60) as response:
                response.read()
        with opener.open(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in (401, 403):
            raise KomootError("Komoot rejected the Safari session or the requested data is not accessible") from exc
        if exc.code == 404:
            raise KomootError("Komoot did not find the requested tour or route page") from exc
        raise KomootError(f"Komoot request failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise KomootError(f"Komoot request failed: {exc.reason}") from exc


def _get_bytes(url: str, accept: str = "application/hal+json,application/json") -> bytes:
    return _request_bytes(url, accept=accept)


def _get_json(url: str) -> dict[str, Any]:
    data = _get_bytes(url)
    try:
        payload = json.loads(data)
    except (ValueError, UnicodeError) as exc:
        raise KomootError("Komoot returned a response that was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise KomootError("Komoot returned an unexpected response shape")
    if payload.get("error"):
        raise KomootError(str(payload.get("message") or payload["error"]))
    return payload


def _current_user_id() -> str:
    """Resolve the signed-in account ID from its authenticated Komoot home page."""
    page = _get_bytes(f"{WEB_ROOT}/", "text/html").decode("utf-8", errors="replace")
    matches = set(re.findall(
        r"href=[\"'](?:https://www\.komoot\.com)?/(?:saved-routes/(\d+)|user/(\d+)/routes)(?:[/?#\"'])",
        page,
    ))
    user_ids = {first or second for first, second in matches}
    if len(user_ids) != 1:
        raise KomootError("Could not resolve the signed-in Komoot account ID; confirm Safari is logged in")
    return user_ids.pop()


def list_tours(
    *,
    tour_type: str = "planned",
    query: str | None = None,
    page: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    user_id = _current_user_id()
    params: dict[str, str | int] = {"page": page, "limit": limit}
    if tour_type != "all":
        params["type"] = f"tour_{tour_type}"
    if query:
        params["name"] = query
    url = f"{API_ROOT}/users/{user_id}/tours/?{urllib.parse.urlencode(params)}"
    payload = _get_json(url)
    rows = payload.get("_embedded", {}).get("tours", [])
    if not isinstance(rows, list):
        raise KomootError("Komoot returned an unexpected tours list")
    page_data = payload.get("page", {})
    tours = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        tour_id = str(row.get("id", ""))
        tours.append({
            "id": tour_id,
            "name": row.get("name"),
            "tour_type": row.get("type"),
            "status": row.get("status"),
            "sport": row.get("sport"),
            "date": row.get("date"),
            "distance_m": row.get("distance"),
            "duration_s": row.get("duration"),
            "elevation_up_m": row.get("elevation_up"),
            "elevation_down_m": row.get("elevation_down"),
            "start_point": row.get("start_point"),
            "url": f"https://www.komoot.com/tour/{tour_id}" if tour_id else None,
        })
    total_pages = page_data.get("totalPages") if isinstance(page_data, dict) else None
    return {
        "tours": tours,
        "page": page,
        "limit": limit,
        "total_elements": page_data.get("totalElements") if isinstance(page_data, dict) else None,
        "total_pages": total_pages,
        "next_page": page + 1 if isinstance(total_pages, int) and page + 1 < total_pages else None,
    }


def get_tour_metadata(tour: str) -> dict[str, Any]:
    tour_id = parse_tour_id(tour)
    payload = _get_json(f"{API_ROOT}/tours/{tour_id}")
    payload.pop("_embedded", None)
    payload.pop("_links", None)
    payload.pop("_meta", None)
    return {"tour_id": tour_id, "metadata": payload}


def get_tour_route(tour: str) -> dict[str, Any]:
    tour_id = parse_tour_id(tour)
    embedded = urllib.parse.urlencode({"_embedded": "coordinates,way_types,surfaces,directions"})
    payload = _get_json(f"{API_ROOT}/tours/{tour_id}?{embedded}")
    embedded_data = payload.get("_embedded")
    if not isinstance(embedded_data, dict) or not isinstance(embedded_data.get("coordinates"), dict):
        raise KomootError("Komoot did not return route coordinates for this tour")
    route = {key: value for key, value in payload.items() if key not in {"_links", "_meta"}}
    # These are capability-bearing values and unrelated account context; never
    # expose them as route geometry through an MCP result.
    for key in ("participants", "share_token", "share_token_invite", "creator"):
        embedded_data.pop(key, None)
    return {"tour_id": tour_id, "route": route}


def get_tour_line(tour: str) -> dict[str, Any]:
    """Read Komoot's native tour-line geometry directly from the web API."""
    tour_id = parse_tour_id(tour)
    payload = _get_json(f"{API_ROOT}/tours/{tour_id}/tour_line")
    if "geometry" not in payload:
        raise KomootError("Komoot did not return tour-line geometry for this tour")
    payload.pop("_links", None)
    return {"tour_id": tour_id, "tour_line": payload}


def _save_export(tour: str, file_format: str, output_path: str | None, overwrite: bool) -> dict[str, Any]:
    tour_id = parse_tour_id(tour)
    url = f"{FIT_API_ROOT}/{tour_id}.{file_format.lower()}"
    accept = "application/vnd.ant.fit,application/octet-stream" if file_format == "FIT" else "application/gpx+xml,application/xml,text/xml"
    try:
        file_bytes = _get_bytes(url, accept)
    except KomootError as exc:
        raise KomootError(f"Komoot {file_format} export failed: {exc}") from exc

    if file_format == "FIT":
        valid = len(file_bytes) >= 14 and file_bytes[8:12] == b".FIT"
    else:
        try:
            root = ET.fromstring(file_bytes)
            valid = root.tag.rsplit("}", 1)[-1].lower() == "gpx"
        except ET.ParseError:
            valid = False
    if not valid:
        raise KomootError(f"Komoot response was not a valid {file_format} export")

    destination = Path(output_path).expanduser() if output_path else DEFAULT_OUTPUT_DIR / f"{tour_id}.{file_format.lower()}"
    if not destination.is_absolute():
        raise ValueError("output_path must be absolute")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Output already exists; set overwrite=true to replace it: {destination}")

    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(file_bytes)
            handle.flush()
            os.fsync(handle.fileno())
        if destination.exists() and not overwrite:
            raise FileExistsError(f"Output already exists; set overwrite=true to replace it: {destination}")
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return {"tour_id": tour_id, "file_path": str(destination.resolve()), "byte_size": len(file_bytes), "format": file_format}


def download_tour_gpx(tour: str, *, output_path: str | None = None, overwrite: bool = False) -> dict[str, Any]:
    return _save_export(tour, "GPX", output_path, overwrite)


def download_tour_fit(
    tour: str,
    *,
    output_path: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    return _save_export(tour, "FIT", output_path, overwrite)


def rename_tour(tour: str, name: str, *, confirm: bool) -> dict[str, Any]:
    """Rename one of the signed-in user's planned tours and verify by readback."""
    if confirm is not True:
        raise ValueError("Renaming a Komoot tour requires confirm=true")
    tour_id = parse_tour_id(tour)
    name = name.strip()
    if not name or len(name) > 120 or "/" in name or "\\" in name:
        raise ValueError("name must be 1–120 characters and cannot contain folder separators")

    user_id = _current_user_id()
    page = 0
    owned_tour = None
    while page < 100:
        params = urllib.parse.urlencode({"page": page, "limit": 100, "type": "tour_planned"})
        listing = _get_json(f"{API_ROOT}/users/{user_id}/tours/?{params}")
        rows = listing.get("_embedded", {}).get("tours", [])
        if not isinstance(rows, list):
            raise KomootError("Komoot returned an unexpected tours list while checking tour ownership")
        owned_tour = next((row for row in rows if isinstance(row, dict) and str(row.get("id")) == tour_id), None)
        if owned_tour:
            break
        total_pages = (listing.get("page") or {}).get("totalPages")
        if not isinstance(total_pages, int) or page + 1 >= total_pages:
            break
        page += 1
    if not owned_tour:
        raise KomootError("Only planned tours listed in the signed-in Komoot account can be renamed")

    old_name = owned_tour.get("name")
    url = f"{WEB_ROOT}/api/v007/tours/{tour_id}?hl=en"
    try:
        _request_bytes(
            url,
            method="PATCH",
            body=json.dumps({"name": name}, separators=(",", ":")).encode("utf-8"),
            content_type="application/json",
            accept="application/hal+json,application/json",
        )
    except KomootError as exc:
        raise KomootWriteUnverified(
            f"Komoot did not confirm the rename request; inspect the tour before retrying: {exc}"
        ) from exc

    try:
        updated = _get_json(f"{API_ROOT}/tours/{tour_id}")
    except KomootError as exc:
        raise KomootWriteUnverified("Rename may have succeeded, but Komoot readback failed; inspect the tour before retrying") from exc
    if updated.get("name") != name:
        raise KomootWriteUnverified("Komoot did not confirm the requested name; inspect the tour before retrying")
    return {"tour_id": tour_id, "old_name": old_name, "name": name, "verified": True}


class KomootWriteUnverified(KomootError):
    """A tour mutation may have reached Komoot but could not be verified."""


def get_tour_waypoints(tour: str) -> dict[str, Any]:
    """Return the planned path, preserving Komoot order and coordinate indices."""
    from route_analysis import positions
    tour_id = parse_tour_id(tour)
    payload = _get_json(f'{API_ROOT}/tours/{tour_id}')
    path = payload.get('path')
    if not isinstance(path, list) or not path:
        raise KomootError('Komoot did not provide a planned path for this tour')
    # Validate all points; never silently drop a waypoint.
    positions([row['location'] for row in path])
    waypoints = [{'position': i+1, **row} for i, row in enumerate(path)]
    return {'tour_id': tour_id, 'source': 'Komoot path field', 'count': len(path), 'waypoints': waypoints}


def inspect_tour(tour: str) -> dict[str, Any]:
    from route_analysis import inspect_route
    result = get_tour_route(tour)
    return {'tour_id': result['tour_id'], **inspect_route(result['route'])}


def compare_tours(tour: str, other_tour: str | None = None,
                  coordinates: list[dict[str, float]] | None = None,
                  tolerance_m: float = 25, sample_spacing_m: float = 100) -> dict[str, Any]:
    from route_analysis import compare_routes
    if (other_tour is None) == (coordinates is None):
        raise ValueError('Supply exactly one of other_tour or coordinates')
    reference = get_tour_route(tour)
    if other_tour is not None:
        candidate = get_tour_route(other_tour)
        coordinates = candidate['route']['_embedded']['coordinates']['items']
    return {'tour_id': reference['tour_id'],
            'other_tour_id': parse_tour_id(other_tour) if other_tour is not None else None,
            **compare_routes(reference['route']['_embedded']['coordinates']['items'], coordinates,
                             tolerance_m, sample_spacing_m)}
