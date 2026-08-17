"""Shared normalized route-context contract for agent-facing route helpers."""

from __future__ import annotations

import argparse
import json
from typing import Any


SURFACE_PREFERENCES = {"road", "gravel", "any", "unknown-ok"}


def parse_route_context_json(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--route-context-json must be valid JSON: {exc.msg}"
        ) from exc
    return parse_route_context_payload(
        payload,
        argument_name="--route-context-json",
    )


def parse_route_context_payload(
    payload: Any,
    *,
    argument_name: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise argparse.ArgumentTypeError(f"{argument_name} must be one JSON object")
    unknown = sorted(
        set(payload)
        - {"start_anchor", "surface_preference", "target_distance_km", "allow_away"}
    )
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unsupported {argument_name} field(s): " + ", ".join(unknown)
        )

    surface_preference = payload.get("surface_preference", "road")
    if surface_preference not in SURFACE_PREFERENCES:
        raise argparse.ArgumentTypeError(
            f"{argument_name} surface_preference is unsupported"
        )
    allow_away = payload.get("allow_away", False)
    if not isinstance(allow_away, bool):
        raise argparse.ArgumentTypeError(
            f"{argument_name} allow_away must be boolean"
        )

    target_distance_km = optional_number(
        payload.get("target_distance_km"),
        field=f"{argument_name} target_distance_km",
    )
    if target_distance_km is not None and target_distance_km <= 0:
        raise argparse.ArgumentTypeError(
            f"{argument_name} target_distance_km must be positive"
        )

    start_anchor = payload.get("start_anchor")
    if start_anchor is not None:
        if not isinstance(start_anchor, dict):
            raise argparse.ArgumentTypeError(
                f"{argument_name} start_anchor must be an object or null"
            )
        unknown_anchor = sorted(
            set(start_anchor) - {"display_name", "lat", "lng", "radius_km"}
        )
        if unknown_anchor:
            raise argparse.ArgumentTypeError(
                f"unsupported {argument_name} start_anchor field(s): "
                + ", ".join(unknown_anchor)
            )
        lat = required_number(
            start_anchor.get("lat"),
            field=f"{argument_name} start_anchor.lat",
        )
        lng = required_number(
            start_anchor.get("lng"),
            field=f"{argument_name} start_anchor.lng",
        )
        if not -90 <= lat <= 90:
            raise argparse.ArgumentTypeError(
                f"{argument_name} start_anchor.lat must be between -90 and 90"
            )
        if not -180 <= lng <= 180:
            raise argparse.ArgumentTypeError(
                f"{argument_name} start_anchor.lng must be between -180 and 180"
            )
        radius_km = optional_number(
            start_anchor.get("radius_km", 0.25),
            field=f"{argument_name} start_anchor.radius_km",
        )
        if radius_km is None or radius_km <= 0:
            raise argparse.ArgumentTypeError(
                f"{argument_name} start_anchor.radius_km must be positive"
            )
        display_name = start_anchor.get("display_name")
        if display_name is not None and not isinstance(display_name, str):
            raise argparse.ArgumentTypeError(
                f"{argument_name} start_anchor.display_name must be a string or null"
            )
        start_anchor = {
            "display_name": (
                display_name.strip()
                if isinstance(display_name, str) and display_name.strip()
                else None
            ),
            "lat": lat,
            "lng": lng,
            "radius_km": radius_km,
        }

    return {
        "start_anchor": start_anchor,
        "surface_preference": surface_preference,
        "target_distance_km": target_distance_km,
        "allow_away": allow_away,
    }


def required_number(value: Any, *, field: str) -> float:
    number = optional_number(value, field=field)
    if number is None:
        raise argparse.ArgumentTypeError(f"{field} must be numeric")
    return number


def optional_number(value: Any, *, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise argparse.ArgumentTypeError(f"{field} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(f"{field} must be numeric") from exc
