"""Strava activity, gear, and media operations for the MCP server."""

from __future__ import annotations

import datetime as dt
import html
import json
from pathlib import Path
import re
from typing import Any
import time
import urllib.parse
import urllib.request
import uuid

from scripts import strava_activity_tags as activity_metadata
from scripts.strava_activities import activity_date, fetch_page, normalized_activity, payload_rows
from strava_route_api import StravaAuthRequired, StravaError, StravaSession, default_cookie_file


TAG_ID_TO_NAME = {
    1: "Race",
    2: "Workout",
    3: "Commute",
    12: "Recovery",
    13: "WithPet",
    14: "ForACause",
    15: "Competition",
    16: "WithKid",
}

GEAR_COLLECTIONS = {
    "bike": "bikes",
    "shoe": "shoes",
}

MEDIA_TYPE_NAMES = {
    1: "photo",
    2: "video",
}


def _media_props(edit_html: str) -> dict[str, Any]:
    """Read the MediaUploader state embedded in Strava's edit page."""
    match = re.search(
        r"data-react-class='MediaUploader' data-react-props='([^']*)'", edit_html
    )
    if not match:
        raise StravaError("Strava activity edit page did not expose media state.")
    try:
        props = json.loads(html.unescape(match.group(1)))
    except json.JSONDecodeError as exc:
        raise StravaError("Strava activity edit page returned invalid media state.") from exc
    if not isinstance(props, dict) or not isinstance(props.get("media"), list):
        raise StravaError("Strava activity edit page returned unexpected media state.")
    return props


def _media_identifier(row: dict[str, Any]) -> str | None:
    for field in ("id", "uuid", "media_id"):
        value = row.get(field)
        if value is not None and str(value):
            return str(value)
    return None


def _media_url(row: dict[str, Any]) -> str | None:
    """Choose the largest available delivery URL without exposing credentials."""
    urls = row.get("urls")
    if isinstance(urls, dict):
        preferred = ("original", "2048", "1800", "1600", "1200", "1024", "600", "300", "200", "100")
        for key in preferred:
            value = urls.get(key)
            if isinstance(value, str) and value.startswith("https://"):
                return value
        for value in urls.values():
            if isinstance(value, str) and value.startswith("https://"):
                return value
    for field in ("url", "source_url", "original_url"):
        value = row.get(field)
        if isinstance(value, str) and value.startswith("https://"):
            return value
    return None


def _normalize_media(row: dict[str, Any]) -> dict[str, Any]:
    identifier = _media_identifier(row)
    if identifier is None:
        raise StravaError("Strava returned media without an ID.")
    raw_type = row.get("media_type") or row.get("type")
    try:
        kind = MEDIA_TYPE_NAMES.get(int(raw_type), str(raw_type))
    except (TypeError, ValueError):
        kind = str(raw_type) if raw_type is not None else None
    result = {
        "media_id": identifier,
        "type": kind,
        "caption": row.get("caption"),
        "filename": row.get("filename") or row.get("original_filename"),
        "created_at": row.get("created_at") or row.get("taken_at"),
        "is_highlight": row.get("id") == row.get("default_photo_id"),
    }
    return {key: value for key, value in result.items() if value is not None}


def _fetch_edit_media(session: StravaSession, activity_id: int | str) -> tuple[str, dict[str, Any]]:
    activity_metadata.SESSION = session
    edit_html = activity_metadata.fetch_edit(str(activity_id))
    return edit_html, _media_props(edit_html)


def list_activity_media(
    *, activity_id: int | str, cookie_file: Path | None = None
) -> dict[str, Any]:
    """List photos and videos currently attached to one exact activity."""
    with StravaSession(cookie_file or default_cookie_file()) as session:
        _, props = _fetch_edit_media(session, activity_id)
    rows = props["media"]
    if not all(isinstance(row, dict) for row in rows):
        raise StravaError("Strava activity media list contained an invalid item.")
    return {
        "activity_id": int(activity_id) if str(activity_id).isdigit() else str(activity_id),
        "count": len(rows),
        "media": [_normalize_media(row) for row in rows],
    }


def _safe_filename(name: str) -> str:
    candidate = Path(name).name.strip()
    if not candidate or candidate in {".", ".."}:
        return "strava-media"
    return candidate


def _filename_for_media(row: dict[str, Any], media_id: str) -> str:
    explicit = row.get("filename") or row.get("original_filename")
    if isinstance(explicit, str) and explicit.strip():
        return _safe_filename(explicit)
    media_url = _media_url(row)
    suffix = Path(urllib.parse.urlparse(media_url or "").path).suffix
    return f"strava-{media_id}{suffix}" if suffix else f"strava-{media_id}"


def _is_strava_host(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return host == "strava.com" or host.endswith(".strava.com")


def download_activity_media(
    *,
    activity_id: int | str,
    media_id: int | str,
    destination_dir: str,
    overwrite: bool = False,
    cookie_file: Path | None = None,
) -> dict[str, Any]:
    """Download one listed activity media item to an explicit local folder."""
    target_dir = Path(destination_dir).expanduser()
    if target_dir.exists() and not target_dir.is_dir():
        raise ValueError("destination_dir must be a directory")
    target_dir.mkdir(parents=True, exist_ok=True)
    wanted_id = str(media_id)
    with StravaSession(cookie_file or default_cookie_file()) as session:
        _, props = _fetch_edit_media(session, activity_id)
        row = next(
            (item for item in props["media"] if isinstance(item, dict) and _media_identifier(item) == wanted_id),
            None,
        )
        if row is None:
            raise ValueError(f"No media with ID {media_id!r} is attached to activity {activity_id!r}.")
        media_url = _media_url(row)
        if media_url is None:
            raise StravaError("Strava did not expose a downloadable URL for this media item.")
        destination = target_dir / _filename_for_media(row, wanted_id)
        if destination.exists() and not overwrite:
            raise ValueError(f"Destination already exists: {destination}. Use overwrite=true to replace it.")
        body, _, _ = session.request(media_url, include_cookie=_is_strava_host(media_url))
    destination.write_bytes(body)
    return {
        "activity_id": int(activity_id) if str(activity_id).isdigit() else str(activity_id),
        "media_id": wanted_id,
        "path": str(destination.resolve()),
        "bytes": len(body),
    }


def _csrf_from_edit_html(edit_html: str) -> str:
    match = re.search(r'<meta name="csrf" content="([^"]+)"', edit_html)
    if not match:
        raise StravaError("Strava activity edit page did not expose a CSRF token.")
    return html.unescape(match.group(1))


def _upload_media_blob(
    session: StravaSession,
    *,
    athlete_id: int,
    file_path: Path,
    csrf: str,
) -> str:
    media_uuid = str(uuid.uuid4())
    metadata_body = urllib.parse.urlencode(
        {"athlete_id": athlete_id, "uuid": media_uuid, "taken_at": int(file_path.stat().st_mtime * 1000)}
    ).encode("utf-8")
    body, _, _ = session.request(
        "https://www.strava.com/photos/metadata",
        method="PUT",
        headers=[
            "Accept: application/json, text/javascript, */*; q=0.01",
            "Content-Type: application/x-www-form-urlencoded; charset=UTF-8",
            "Origin: https://www.strava.com",
            "Referer: https://www.strava.com/",
            "X-Requested-With: XMLHttpRequest",
            f"X-CSRF-Token: {csrf}",
        ],
        data=metadata_body,
    )
    try:
        metadata = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StravaError("Strava returned invalid upload metadata.") from exc
    if not isinstance(metadata, dict) or not isinstance(metadata.get("uri"), str):
        raise StravaError("Strava did not provide a media upload URL.")
    if urllib.parse.urlparse(metadata["uri"]).scheme != "https":
        raise StravaError("Strava did not provide a secure media upload URL.")
    upload_headers = metadata.get("header")
    if not isinstance(upload_headers, dict) or not all(
        isinstance(name, str) and isinstance(value, str) for name, value in upload_headers.items()
    ):
        raise StravaError("Strava did not provide valid media upload headers.")
    session.request(
        metadata["uri"],
        method="PUT",
        headers=[*([f"{name}: {value}" for name, value in upload_headers.items()]), "Content-Type: application/octet-stream"],
        data=file_path.read_bytes(),
        include_cookie=False,
    )
    return media_uuid


def upload_activity_media(
    *,
    activity_id: int | str,
    file_path: str,
    confirm: bool,
    caption: str | None = None,
    cookie_file: Path | None = None,
) -> dict[str, Any]:
    """Attach one local image or video to an exact activity and verify it appears."""
    if not confirm:
        raise ValueError("upload_activity_media requires confirm=true")
    source = Path(file_path).expanduser()
    if not source.is_file():
        raise ValueError(f"file_path must be an existing file: {source}")
    if source.stat().st_size == 0:
        raise ValueError("file_path must not be empty")
    if source.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".mp4", ".mov"}:
        raise ValueError("file_path must be a JPG, PNG, GIF, MP4, or MOV media file")
    with StravaSession(cookie_file or default_cookie_file()) as session:
        edit_html, props = _fetch_edit_media(session, activity_id)
        athlete_id = props.get("athleteId")
        if not isinstance(athlete_id, int):
            raise StravaError("Strava activity edit page did not expose the athlete ID.")
        media_uuid = _upload_media_blob(
            session,
            athlete_id=athlete_id,
            file_path=source,
            csrf=_csrf_from_edit_html(edit_html),
        )
        pairs = urllib.parse.parse_qsl(
            activity_metadata.build_form_body(
                edit_html,
                activity_name=None,
                tag=None,
                tag_supplied=False,
                current_tag=None,
                trainer=None,
                visibility=None,
                start_time_hidden=None,
                bike_id=None,
            ),
            keep_blank_values=True,
        )
        rank = len(props["media"])
        pairs.extend(
            [
                (f"photos[{media_uuid}][caption]", caption or ""),
                (f"photos[{media_uuid}][rank]", str(rank)),
                (f"photos[{media_uuid}][media_type]", "1"),
            ]
        )
        session.request(
            f"https://www.strava.com/activities/{activity_id}",
            method="POST",
            headers=[
                "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Content-Type: application/x-www-form-urlencoded",
                "Origin: https://www.strava.com",
                f"Referer: https://www.strava.com/activities/{activity_id}/edit",
            ],
            data=urllib.parse.urlencode(pairs, doseq=True).encode("utf-8"),
        )
        deadline = time.monotonic() + 5.0
        while True:
            _, current = _fetch_edit_media(session, activity_id)
            attached = next(
                (item for item in current["media"] if isinstance(item, dict) and _media_identifier(item) == media_uuid),
                None,
            )
            if attached is not None:
                return {
                    "activity_id": int(activity_id) if str(activity_id).isdigit() else str(activity_id),
                    "uploaded": _normalize_media(attached),
                    "verified": True,
                }
            if time.monotonic() >= deadline:
                raise StravaError(
                    "Strava accepted the media upload request, but readback did not confirm the attachment."
                )
            time.sleep(0.4)


def normalize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return stable user-oriented fields across list, get, and update tools."""
    normalized = dict(result)
    value = normalized.get("start_date_local")
    if isinstance(value, (int, float)):
        # Strava's activity-detail endpoint encodes the local wall-clock value
        # as an epoch number rather than as an actual UTC instant.
        normalized["start_date_local"] = dt.datetime.fromtimestamp(
            value, dt.timezone.utc
        ).replace(tzinfo=None).isoformat()
    elif isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            normalized["start_date_local"] = parsed.isoformat()
        except ValueError:
            pass
    selected = normalized.get("selected_tag_type")
    try:
        tag_id = int(selected) if selected is not None else None
    except (TypeError, ValueError):
        tag_id = None
    normalized["tag"] = TAG_ID_TO_NAME.get(tag_id)
    normalized.pop("selected_tag_type", None)
    normalized.pop("tags", None)
    normalized.pop("true_tag_ids", None)
    bike_id = normalized.get("bike_id")
    if isinstance(bike_id, str) and bike_id.isdigit():
        normalized["bike_id"] = int(bike_id)
    elapsed = normalized.pop("elapsed_time_raw", None)
    moving = normalized.pop("moving_time_raw", None)
    distance = normalized.pop("distance_raw", None)
    elevation = normalized.pop("elevation_gain_raw", None)
    normalized["elapsed_time_seconds"] = int(elapsed) if elapsed is not None else None
    normalized["moving_time_seconds"] = int(moving) if moving is not None else None
    normalized["distance_meters"] = float(distance) if distance is not None else None
    normalized["distance_km"] = round(float(distance) / 1000, 3) if distance is not None else None
    normalized["elevation_gain_meters"] = float(elevation) if elevation is not None else None
    return normalized


def list_activities(
    *,
    since: str,
    until: str | None = None,
    visibility: str | None = None,
    max_pages: int = 20,
    per_page: int = 100,
    cookie_file: Path | None = None,
) -> dict[str, Any]:
    since_date = dt.date.fromisoformat(since)
    until_date = dt.date.fromisoformat(until) if until else dt.date.today()
    if until_date < since_date:
        raise ValueError("until must be on or after since")
    if visibility not in {None, "everyone", "followers_only", "only_me"}:
        raise ValueError("visibility must be everyone, followers_only, or only_me")
    if max_pages < 1 or per_page < 1:
        raise ValueError("max_pages and per_page must be positive")

    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    with StravaSession(cookie_file or default_cookie_file()) as session:
        for page in range(1, max_pages + 1):
            rows = payload_rows(fetch_page(session, page, per_page))
            if not rows:
                break
            oldest: dt.date | None = None
            for row in rows:
                row_date = activity_date(row)
                if row_date is not None:
                    oldest = row_date if oldest is None else min(oldest, row_date)
                activity = normalize_result(normalized_activity(row))
                identifier = str(activity["id"])
                if identifier in seen or row_date is None or not since_date <= row_date <= until_date:
                    continue
                if visibility and activity["visibility"] != visibility:
                    continue
                seen.add(identifier)
                matches.append(activity)
            if oldest is not None and oldest < since_date:
                break
    matches.sort(key=lambda row: (row.get("start_date_local") or "", str(row.get("id"))), reverse=True)
    return {"count": len(matches), "activities": matches}


def _gear_distance_km(value: Any) -> float | None:
    """Convert Strava's display-formatted total distance to a numeric value."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _notification_distance_km(value: Any) -> float | None:
    """Convert the website gear endpoint's millimetre notification value."""
    if value is None:
        return None
    try:
        return float(value) / 1_000_000
    except (TypeError, ValueError):
        return None


def _normalize_gear(row: dict[str, Any], gear_type: str) -> dict[str, Any]:
    total_distance = row.get("total_distance")
    result = {
        "id": row.get("id"),
        "gear_type": gear_type,
        "name": row.get("display_name") or row.get("name"),
        "active": row.get("active"),
        "default": row.get("default"),
        "total_distance_km": _gear_distance_km(total_distance),
    }
    for field in ("brand_name", "model_name", "description"):
        if field in row:
            result[field] = row[field]
    if "notification_distance" in row:
        result["notification_distance_km"] = _notification_distance_km(row["notification_distance"])
    return result


def _fetch_gear_collection(session: StravaSession, athlete_id: int, gear_type: str) -> list[dict[str, Any]]:
    collection = GEAR_COLLECTIONS[gear_type]
    body, _, _ = session.request(f"https://www.strava.com/athletes/{athlete_id}/gear/{collection}")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise StravaError(f"Strava returned invalid JSON for {collection}.") from exc
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise StravaError(f"Strava returned an unexpected {collection} response.")
    return [_normalize_gear(row, gear_type) for row in payload]


def _list_gear_with_session(session: StravaSession) -> dict[str, list[dict[str, Any]]]:
    authenticated = session.authenticate()
    athlete_id = authenticated.get("athlete_id")
    if not isinstance(athlete_id, int):
        raise StravaError("Authenticated Strava session did not expose an athlete ID.")
    return {
        gear_type: _fetch_gear_collection(session, athlete_id, gear_type)
        for gear_type in GEAR_COLLECTIONS
    }


def list_gear(*, cookie_file: Path | None = None) -> dict[str, Any]:
    """List the account's active and retired bikes and shoes."""
    with StravaSession(cookie_file or default_cookie_file()) as session:
        gear = _list_gear_with_session(session)
    return {
        "count": sum(len(items) for items in gear.values()),
        "bikes": gear["bike"],
        "shoes": gear["shoe"],
    }


def get_gear(
    *,
    gear_id: int | str,
    gear_type: str | None = None,
    cookie_file: Path | None = None,
) -> dict[str, Any]:
    """Get one gear item from the account's current bike and shoe lists."""
    if gear_type not in {None, *GEAR_COLLECTIONS}:
        raise ValueError("gear_type must be bike or shoe")
    wanted_types = [gear_type] if gear_type else list(GEAR_COLLECTIONS)
    with StravaSession(cookie_file or default_cookie_file()) as session:
        authenticated = session.authenticate()
        athlete_id = authenticated.get("athlete_id")
        if not isinstance(athlete_id, int):
            raise StravaError("Authenticated Strava session did not expose an athlete ID.")
        for item_type in wanted_types:
            for item in _fetch_gear_collection(session, athlete_id, item_type):
                if str(item["id"]) == str(gear_id):
                    return item
    suffix = f" among {gear_type}s" if gear_type else ""
    raise ValueError(f"No gear with ID {gear_id!r} found{suffix}.")


def get_activity_kudos(*, activity_id: int | str, cookie_file: Path | None = None) -> dict[str, Any]:
    """Read the activity's kudos list through Strava's browser-session endpoint."""
    if not re.fullmatch(r"[0-9]+", str(activity_id)):
        raise ValueError("activity_id must be a numeric Strava activity ID")
    with StravaSession(cookie_file or default_cookie_file()) as session:
        body, _, _ = session.request(
            f"https://www.strava.com/feed/activity/{activity_id}/kudos",
            headers=[
                "Accept: application/json",
                "X-Requested-With: XMLHttpRequest",
                f"Referer: https://www.strava.com/activities/{activity_id}",
            ],
        )
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StravaError("Strava returned non-JSON kudos data.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("athletes"), list):
        raise StravaError("Strava returned an unexpected kudos response.")
    athletes = payload["athletes"]
    if not all(isinstance(row, dict) for row in athletes):
        raise StravaError("Strava returned an invalid kudos athlete.")
    return {
        "activity_id": str(activity_id),
        "count": len(athletes),
        "athletes": athletes,
        "is_owner": payload.get("is_owner"),
        "kudosable": payload.get("kudosable"),
    }


def get_activity(*, activity_id: int | str, cookie_file: Path | None = None) -> dict[str, Any]:
    with StravaSession(cookie_file or default_cookie_file()) as session:
        activity_metadata.SESSION = session
        activity = activity_metadata.fetch_activity(str(activity_id))
        activity["_edit_html"] = activity_metadata.fetch_edit(str(activity_id))
        result = activity_metadata.summarize(activity)
        for field in (
            "elapsed_time_raw",
            "moving_time_raw",
            "distance_raw",
            "elevation_gain_raw",
            "suffer_score",
            "commute",
            "has_latlng",
        ):
            result[field] = activity.get(field)
        return normalize_result(result)


def validate_patch(patch: dict[str, Any]) -> None:
    allowed = {"name", "tag", "trainer", "visibility", "start_time_hidden", "mute", "bike_id", "bike_name"}
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise ValueError(f"Unsupported activity patch fields: {', '.join(unknown)}")
    if "mute" in patch and not isinstance(patch["mute"], bool):
        raise ValueError("mute must be a boolean")
    if not patch:
        raise ValueError("patch must contain at least one field")
    if "bike_id" in patch and "bike_name" in patch:
        raise ValueError("Use either bike_id or bike_name, not both")


def update_with_session(
    session: StravaSession,
    *,
    activity_id: int | str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    activity_metadata.SESSION = session
    activity = activity_metadata.update_activity(
        str(activity_id),
        activity_name=patch.get("name"),
        tag=activity_metadata.normalize_tag(patch.get("tag")),
        tag_supplied="tag" in patch,
        trainer=patch.get("trainer"),
        visibility=patch.get("visibility"),
        start_time_hidden=patch.get("start_time_hidden"),
        mute=patch.get("mute"),
        bike_id=str(patch["bike_id"]) if patch.get("bike_id") is not None else None,
        bike_name=patch.get("bike_name"),
    )
    result = activity_metadata.summarize(activity)
    for field in (
        "elapsed_time_raw",
        "moving_time_raw",
        "distance_raw",
        "elevation_gain_raw",
        "suffer_score",
        "commute",
        "has_latlng",
    ):
        result[field] = activity.get(field)
    return normalize_result(result)


def update_activity(
    *,
    activity_id: int | str,
    patch: dict[str, Any],
    confirm: bool,
    cookie_file: Path | None = None,
) -> dict[str, Any]:
    if not confirm:
        raise ValueError("update_activity requires confirm=true")
    validate_patch(patch)

    with StravaSession(cookie_file or default_cookie_file()) as session:
        return update_with_session(session, activity_id=activity_id, patch=patch)


def update_activities(
    *,
    activity_ids: list[int | str],
    patch: dict[str, Any],
    confirm: bool,
    cookie_file: Path | None = None,
) -> dict[str, Any]:
    if not activity_ids:
        raise ValueError("activity_ids must contain at least one ID")
    if not confirm:
        raise ValueError("update_activities requires confirm=true")
    validate_patch(patch)
    updated: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    with StravaSession(cookie_file or default_cookie_file()) as session:
        for activity_id in activity_ids:
            try:
                updated.append(update_with_session(session, activity_id=activity_id, patch=patch))
            except (OSError, StravaError, ValueError) as exc:
                failed.append({
                    "activity_id": activity_id, "error": str(exc),
                    "errorCode": "auth_required" if isinstance(exc, StravaAuthRequired) else "tool_error",
                })
                if isinstance(exc, StravaAuthRequired):
                    break
    return {
        "requested_count": len(activity_ids),
        "updated_count": len(updated),
        "failed_count": len(failed),
        "complete": not failed,
        "updated": updated,
        "failed": failed,
        "not_attempted": activity_ids[len(updated) + len(failed):],
    }
