"""User-oriented Strava activity operations shared by CLI tools."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from scripts import strava_activity_tags as activity_metadata
from scripts.strava_activities import activity_date, fetch_page, normalized_activity, payload_rows
from scripts.strava_route_api import StravaError, StravaSession, default_cookie_file


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
    allowed = {"name", "tag", "trainer", "visibility", "start_time_hidden", "bike_id", "bike_name"}
    unknown = sorted(set(patch) - allowed)
    if unknown:
        raise ValueError(f"Unsupported activity patch fields: {', '.join(unknown)}")
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
                failed.append({"activity_id": activity_id, "error": str(exc)})
    return {
        "requested_count": len(activity_ids),
        "updated_count": len(updated),
        "failed_count": len(failed),
        "complete": not failed,
        "updated": updated,
        "failed": failed,
    }
