"""Read saved routes through Strava's authenticated My Routes source."""

from __future__ import annotations

from html.parser import HTMLParser
import copy
import json
from typing import Any

from strava_route_api import StravaError, StravaHttpError, StravaSession, default_cookie_file


ROUTES_PAGE = "https://www.strava.com/athlete/routes"
ROUTES_API = "https://www.strava.com/api/next/data/routes/my-routes"
# Strava's route-type selector sends all types explicitly; [] matches no routes.
ROUTE_TYPES = [
    "Ride", "Run", "Walk", "Hike", "TrailRun", "GravelRide",
    "MountainBikeRide", "EMountainBikeRide", "EBikeRide", "Swim", "Kayak",
    "Golf", "Sail", "Canoe", "AlpineSki", "BackcountrySki", "IceSkate",
    "InlineSkate", "Handcycle", "Kitesurf", "NordicSki", "RockClimbing",
    "RollerSki", "Rowing", "Skateboard", "Snowshoe", "StandUpPaddle",
    "Surfing", "Velomobile", "Windsurf", "Wheelchair",
]
CREATED_BY = {"any": "Any", "me": "Athlete", "others": "Others"}


class _RoutePageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_data = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.in_data = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_data = False

    def handle_data(self, data: str) -> None:
        if self.in_data:
            self.parts.append(data)


def _page_data(body: bytes) -> dict[str, Any]:
    parser = _RoutePageParser()
    try:
        parser.feed(body.decode("utf-8"))
        payload = json.loads("".join(parser.parts))
    except (ValueError, UnicodeError) as exc:
        raise StravaError("Strava route page did not contain valid route data.") from exc
    if not isinstance(payload, dict):
        raise StravaError("Strava route page returned unexpected data.")
    return payload


def get_route(route_id: str) -> dict[str, Any]:
    """Return props.pageProps.route exactly as supplied by Strava."""
    if not isinstance(route_id, str) or not route_id.isascii() or not route_id.isdigit():
        raise ValueError("route_id must be a numeric string returned by list_routes.")
    with StravaSession(default_cookie_file()) as session:
        body, _, _ = session.request(f"https://www.strava.com/routes/{route_id}")
    payload = _page_data(body)
    props = payload.get("props") if isinstance(payload, dict) else None
    page_props = props.get("pageProps") if isinstance(props, dict) else None
    route = page_props.get("route") if isinstance(page_props, dict) else None
    if not isinstance(route, dict) or str(route.get("id")) != route_id:
        raise StravaError("Strava route page did not contain the requested route.")
    return route


class RouteWriteError(StravaError):
    def __init__(self, operation: str, route_id: str | None, stage: str) -> None:
        super().__init__("Route write could not be verified. Read current state before retrying; the operation may already have succeeded.")
        self.details = {"operation": operation, "route_id": route_id, "stage": stage,
                        "outcome_uncertain": True}


def _editable_route(session: StravaSession, route_id: str) -> dict[str, Any]:
    body, _, _ = session.request(f"https://www.strava.com/maps/create?routeId={route_id}")
    data = _page_data(body)
    props = data.get("props")
    page_props = props.get("pageProps") if isinstance(props, dict) else None
    route = page_props.get("prefetchedRoute") if isinstance(page_props, dict) else None
    if not isinstance(route, dict) or str(route.get("id")) != route_id:
        raise StravaError("Strava did not return the requested editable route.")
    return route


def _write_props(route: dict[str, Any]) -> dict[str, Any]:
    required = {"title", "routeDescription", "isPrivate", "isStarred", "elements", "legs", "routePrefs", "routeType"}
    if not required.issubset(route) or not isinstance(route["isPrivate"], bool) or not isinstance(route["isStarred"], bool):
        raise StravaError("Strava editable route is incomplete; omitted fields cannot be preserved.")
    props = {
        "name": route["title"], "description": route["routeDescription"] or "",
        "visibility": "OnlyMe" if route["isPrivate"] else "Everyone",
        "starred": route["isStarred"], "elements": copy.deepcopy(route["elements"]),
        "legs": copy.deepcopy(route["legs"]),
        "routePrefs": {**route["routePrefs"], "routeType": route["routeType"]},
    }
    for index, leg in enumerate(props["legs"]):
        leg["startElement"] = index
    return props


def _validate_geometry(props: dict[str, Any]) -> None:
    elements, legs = props["elements"], props["legs"]
    if len(legs) != len(elements) - 1:
        raise ValueError("There must be one built leg between each pair of elements.")
    for index, leg in enumerate(legs):
        if leg.get("startElement") != index or not leg.get("paths"):
            raise ValueError("Built legs must have consecutive startElement indices and paths.")
        for path in leg["paths"]:
            polyline = path.get("polyline")
            if not isinstance(polyline, dict) or polyline.get("encoding") != "Google" or not polyline.get("data"):
                raise ValueError("Every built path must include its Strava Google polyline.")


def _verify_write(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    saved = _write_props(actual)
    for field in ("name", "description", "visibility", "starred", "elements", "routePrefs"):
        if saved[field] != expected[field]:
            raise StravaError(f"Saved route did not match requested {field}.")
    # Server-derived path measurements may differ; compare the actual saved geometry.
    def polylines(props: dict[str, Any]) -> list[list[dict[str, Any]]]:
        return [[path["polyline"] for path in leg["paths"]] for leg in props["legs"]]
    if polylines(saved) != polylines(expected):
        raise StravaError("Saved route did not match requested geometry.")


def _save_route(session: StravaSession, operation: str, props: dict[str, Any], route_id: str | None) -> dict[str, Any]:
    request_path = session.tmp_dir / "route-write-request.json"
    response_path = session.tmp_dir / "route-write-response.json"
    request_path.write_text(json.dumps({"props": props}))
    stage = "submit"
    try:
        response = session.api(operation, request_path, response_path)
        key = "createRoute" if operation == "create" else "updateRoute"
        if response.get("errors") or key not in response:
            raise StravaError("Strava did not acknowledge the route write.")
        if operation == "create":
            identifier = response[key]
            if isinstance(identifier, bool) or not isinstance(identifier, (str, int)) or not str(identifier).isascii() or not str(identifier).isdigit():
                raise StravaError("Strava create response did not contain a route ID.")
            route_id = str(identifier)
        stage = "readback"
        _verify_write(props, _editable_route(session, route_id))
        result = get_route(route_id)
        # Public detail data must agree too; returned object remains source-native.
        for field, wanted in {"title": props["name"], "isPrivate": props["visibility"] == "OnlyMe", "isStarred": props["starred"]}.items():
            if result.get(field) != wanted:
                raise StravaError("Route detail and editor readbacks disagreed.")
        return result
    except (OSError, StravaError, ValueError, KeyError, TypeError) as exc:
        raise RouteWriteError(operation, route_id, stage) from exc


def build_route(requests: list[dict[str, Any]]) -> dict[str, Any]:
    """Return Strava's build response unchanged without saving a route."""
    with StravaSession(default_cookie_file()) as session:
        request_path = session.tmp_dir / "route-build-request.json"
        response_path = session.tmp_dir / "route-build-response.json"
        request_path.write_text(json.dumps({"requests": requests}))
        response = session.api("build", request_path, response_path)
    built = response.get("buildRoute")
    if response.get("errors") or not isinstance(built, list) or len(built) != len(requests):
        raise StravaError("Strava did not return one build result per requested leg.")
    for result in built:
        if not isinstance(result, dict) or not isinstance(result.get("legs"), list) or not result["legs"]:
            raise StravaError("Strava build response did not contain complete legs.")
        for leg in result["legs"]:
            if not isinstance(leg, dict) or not isinstance(leg.get("paths"), list) or not leg["paths"]:
                raise StravaError("Strava build response did not contain complete paths.")
    return response


def create_route(props: dict[str, Any], confirm: bool) -> dict[str, Any]:
    """Save previously built and inspected geometry using native Strava write fields."""
    if confirm is not True:
        raise ValueError("Route creation requires confirm=true.")
    prepared = {"description": "", "visibility": "OnlyMe", "starred": False, **copy.deepcopy(props)}
    _validate_geometry(prepared)
    with StravaSession(default_cookie_file()) as session:
        auth = session.authenticate()
        prepared["athleteId"] = auth["athlete_id"]
        return _save_route(session, "create", prepared, None)


def delete_route(route_id: str, confirm: bool) -> dict[str, Any]:
    """Delete one owned route and require an authenticated not-found readback."""
    if confirm is not True:
        raise ValueError("Route deletion requires confirm=true.")
    if not isinstance(route_id, str) or not route_id.isascii() or not route_id.isdigit():
        raise ValueError("route_id must be a numeric string returned by list_routes.")
    url = f"https://www.strava.com/routes/{route_id}"
    with StravaSession(default_cookie_file()) as session:
        auth = session.authenticate()
        current = _editable_route(session, route_id)
        if str((current.get("athlete") or {}).get("id")) != str(auth["athlete_id"]):
            raise ValueError("Only a route owned by the authenticated athlete can be deleted.")
        stage = "submit"
        try:
            _, status, _ = session.request(
                url, method="DELETE",
                headers=["Accept: application/json", f"Referer: {ROUTES_PAGE}",
                         "Origin: https://www.strava.com", "X-Requested-With: XMLHttpRequest"],
                secret_headers=[f"X-CSRF-Token: {session.csrf}"],
            )
            if not 200 <= status < 300:
                raise StravaError("Strava did not acknowledge the route deletion.")
            stage = "readback"
            try:
                session.request(url)
            except StravaHttpError as exc:
                if exc.status not in {404, 410}:
                    raise
            else:
                raise StravaError("Route still exists or deletion could not be established.")
            # A missing page is proof only while the same account remains authenticated.
            verified_auth = session.authenticate()
            if verified_auth.get("athlete_id") != auth.get("athlete_id"):
                raise StravaError("Strava account changed during deletion verification.")
            return {"route_id": route_id, "deleted": True}
        except (OSError, StravaError, ValueError) as exc:
            raise RouteWriteError("delete", route_id, stage) from exc


def update_route(route_id: str, patch: dict[str, Any], confirm: bool) -> dict[str, Any]:
    """Merge supplied native write fields with freshly read editable state."""
    if confirm is not True or not patch:
        raise ValueError("Route update requires a nonempty patch and confirm=true.")
    if not isinstance(route_id, str) or not route_id.isascii() or not route_id.isdigit():
        raise ValueError("route_id must be a numeric string returned by list_routes.")
    with StravaSession(default_cookie_file()) as session:
        auth = session.authenticate()
        current = _editable_route(session, route_id)
        if str((current.get("athlete") or {}).get("id")) != str(auth["athlete_id"]):
            raise ValueError("Only a route owned by the authenticated athlete can be updated.")
        prepared = _write_props(current)
        for field, value in copy.deepcopy(patch).items():
            if field == "routePrefs":
                prepared[field].update(value)
            else:
                prepared[field] = value
        _validate_geometry(prepared)
        prepared["routeId"] = route_id
        return _save_route(session, "update", prepared, route_id)


class _CsrfParser(HTMLParser):
    token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta" and values.get("name") == "csrf":
            self.token = values.get("content")


def _route(row: Any, athlete_id: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise StravaError("Strava returned an invalid route entry.")
    identifier = row.get("id")
    if not isinstance(identifier, (str, int)) or isinstance(identifier, bool) or not str(identifier).isdigit():
        raise StravaError("Strava route entry did not contain a valid ID.")
    identifier = str(identifier)  # Route IDs exceed JavaScript's safe integer range.
    owner = row.get("athlete") or {}
    owner_id = str(owner["id"]) if owner.get("id") is not None else None
    return {
        "id": identifier,
        "name": row.get("title"),
        "url": f"https://www.strava.com/routes/{identifier}",
        "type": row.get("routeType"),
        "distance_m": row.get("length"),
        "elevation_gain_m": row.get("elevationGain"),
        "estimated_time_s": (row.get("estimatedTime") or {}).get("expectedTime"),
        "created_at": row.get("creationTime"),
        "starred": row.get("isStarred"),
        "private": row.get("isPrivate"),
        "athlete_id": owner_id,
        "created_by_me": owner_id == athlete_id if owner_id is not None else None,
    }


def list_routes(
    *, query: str = "", created_by: str = "any", only_starred: bool = False,
    route_types: list[str] | None = None, max_pages: int = 20, cursor: str | None = None,
) -> dict[str, Any]:
    """Read source pages in order; expose truncation and a resumable cursor."""
    routes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    after = cursor if cursor is not None else "0"
    seen_cursors = {after}
    search = {
        "query": query, "onlyStarred": only_starred, "createdBy": CREATED_BY[created_by],
        "routeTypes": ROUTE_TYPES if route_types is None else route_types,
        "elevGainMin": 0, "elevGainMax": None, "distanceMin": 0, "distanceMax": None,
    }
    with StravaSession(default_cookie_file()) as session:
        page, _, _ = session.request(ROUTES_PAGE)
        parser = _CsrfParser()
        parser.feed(page.decode("utf-8"))
        if not parser.token:
            raise StravaError("Strava routes page did not expose a CSRF token.")
        for page_number in range(1, max_pages + 1):
            body, _, _ = session.request(
                ROUTES_API, method="POST",
                headers=["Content-Type: application/json", "Accept: application/json", f"Referer: {ROUTES_PAGE}"],
                secret_headers=[f"X-CSRF-Token: {parser.token}"],
                data=json.dumps({"pageSize": 16, "after": after, "searchArgs": search, "resolutions": []}).encode(),
            )
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError) as exc:
                raise StravaError("Strava routes search returned invalid JSON.") from exc
            if not isinstance(payload, dict) or payload.get("errors"):
                raise StravaError("Strava routes search returned an error response.")
            me = payload.get("me")
            result = me.get("searchRoutes") if isinstance(me, dict) else None
            if not isinstance(result, dict) or me.get("id") is None:
                raise StravaError("Strava routes search returned unexpected account data.")
            nodes, info = result.get("nodes"), result.get("pageInfo")
            if not isinstance(nodes, list) or not isinstance(info, dict) or not isinstance(info.get("hasNextPage"), bool):
                raise StravaError("Strava routes search returned invalid pagination data.")
            for row in nodes:
                route = _route(row, str(me["id"]))
                if route["id"] not in seen_ids:
                    routes.append(route)
                    seen_ids.add(route["id"])
            has_more = info["hasNextPage"]
            next_cursor = info.get("endCursor") if has_more else None
            if not has_more:
                break
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors or not nodes:
                raise StravaError("Strava routes pagination did not advance.")
            seen_cursors.add(next_cursor)
            after = next_cursor
    return {
        "routes": routes, "count": len(routes), "pages_fetched": page_number,
        "has_more": has_more, "next_cursor": next_cursor,
        "query": query, "created_by": created_by, "only_starred": only_starred,
        "route_types": search["routeTypes"],
    }
