"""Read saved routes through Strava's authenticated My Routes source."""

from __future__ import annotations

from html.parser import HTMLParser
import copy
import json
import math
import os
import tempfile
import time
from route_editing import fingerprint
from pathlib import Path

from route_geometry import compare_route_geometry, TOLERANCE_M
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


def _get_route_full(route_id: str) -> dict[str, Any]:
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


# Omit these source arrays consistently, independent of their size.
OMITTED_ROUTE_ARRAY_PATHS = frozenset({
    '/elements', '/legs', '/segmentsOnRoute', '/segments',
    '/elevation', '/polyline', '/distanceStream', '/routePolylineData/media',
})


def _compact_route(value, path='', omitted=None):
    omitted = omitted if omitted is not None else []
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            pointer = path + '/' + key.replace('~', '~0').replace('/', '~1')
            if pointer in OMITTED_ROUTE_ARRAY_PATHS and isinstance(child, list):
                size = len(json.dumps(child, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
                omitted.append({'path': pointer, 'item_count': len(child), 'byte_size': size})
                continue
            result[key] = _compact_route(child, pointer, omitted)
        return result
    if isinstance(value, list):
        return [_compact_route(child, path+'/'+str(i), omitted) for i,child in enumerate(value)]
    return value


def get_route(route_id: str, save_full: bool = False) -> dict[str, Any]:
    """Return native fields except fixed detail arrays, optionally exporting full data."""
    if not isinstance(save_full, bool): raise ValueError('save_full must be a boolean')
    source = _get_route_full(route_id)
    omitted = []
    result = {'route_id': route_id, 'route': _compact_route(source, omitted=omitted),
              'omitted_arrays': omitted}
    if save_full:
        fd, name = tempfile.mkstemp(prefix=f'strava-{route_id}-', suffix='-route.json')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump({'route_id': route_id, 'route': source}, handle, ensure_ascii=False, separators=(',', ':'))
            os.chmod(name, 0o600)
            result.update(full_route_file=name, full_route_format='strava-route-v1',
                          full_route_byte_size=Path(name).stat().st_size)
        except Exception:
            Path(name).unlink(missing_ok=True)
            raise
    return result


class RouteWriteError(StravaError):
    def __init__(self, operation: str, route_id: str | None, stage: str, verification=None) -> None:
        super().__init__("Route write could not be verified. Read current state before retrying; the operation may already have succeeded.")
        self.details = {"operation": operation, "route_id": route_id, "stage": stage,
                        "outcome_uncertain": True}
        if verification is not None:
            self.details["verification"] = verification
            self.details["write_acknowledged"] = stage == "readback"


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
        if len(leg.get('paths', [])) != 1:
            raise ValueError('Save exactly one complete path per leg; multiple paths may be alternatives.')
        if leg.get("startElement") != index or not leg.get("paths"):
            raise ValueError("Built legs must have consecutive startElement indices and paths.")
        for path in leg["paths"]:
            polyline = path.get("polyline")
            if not isinstance(polyline, dict) or polyline.get("encoding") != "Google" or not polyline.get("data"):
                raise ValueError("Every built path must include its Strava Google polyline.")


class VerifiedRoute(dict):
    """Keep source JSON intact; attach diagnostics out of band for MCP."""
    def __init__(self, route, verification):
        super().__init__(route)
        self.verification = verification


class RouteVerificationError(StravaError):
    def __init__(self, report):
        super().__init__('Saved route differs or could not be verified; inspect verification details.')
        self.verification = report


def _verify_write(expected: dict[str, Any], actual: dict[str, Any]) -> dict:
    saved = _write_props(actual)
    fields = [field for field in ('name', 'description', 'visibility', 'starred', 'routePrefs') if saved[field] != expected[field]]
    waypoint_status = 'equivalent_within_tolerance'
    if len(saved['elements']) != len(expected['elements']):
        waypoint_status = 'unresolved'
    else:
        for left,right in zip(expected['elements'],saved['elements']):
            a,b=copy.deepcopy(left),copy.deepcopy(right)
            try:
                x=a['waypoint'].pop('point');y=b['waypoint'].pop('point')
                # Strava alternates omitted and explicit null waypoint metadata.
                for e in (a,b):
                    if e['waypoint'].get('metadata') is None:e['waypoint'].pop('metadata',None)
                gap=111195*math.hypot(x['lat']-y['lat'],(x['lng']-y['lng'])*math.cos(math.radians(x['lat'])))
                if a!=b or not math.isfinite(gap) or gap>TOLERANCE_M:waypoint_status='changed';break
            except (KeyError,TypeError,ValueError):waypoint_status='unresolved';break
    geometry=compare_route_geometry(expected,saved)
    report={'geometry':geometry,'waypoints':waypoint_status,'metadata_mismatches':fields}
    report['status']='changed' if fields or waypoint_status=='changed' or geometry['status']=='changed' else 'unresolved' if waypoint_status=='unresolved' or geometry['status']=='unresolved' else geometry['status']
    if report['status'] in {'changed','unresolved'}:raise RouteVerificationError(report)
    return report


def _save_route(session: StravaSession, operation: str, props: dict[str, Any], route_id: str | None, detail_geometry: dict | None = None) -> dict[str, Any]:
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
        # Read twice even after an immediate match: Strava may normalize later.
        previous_match = False
        last_error = None
        for attempt, delay in enumerate((0, 2, 3), 1):
            if delay: time.sleep(delay)
            try:
                editor_verification = _verify_write(props, _editable_route(session, route_id))
                result = _get_route_full(route_id)
                for field, wanted in {"title": props["name"], "isPrivate": props["visibility"] == "OnlyMe", "isStarred": props["starred"],
                                      "routeDescription": props["description"] or None}.items():
                    actual = result.get(field)
                    if field == 'routeDescription': actual = actual or None
                    if actual != wanted:
                        raise RouteVerificationError({'status':'changed','source':'detail','metadata_mismatches':[field]})
                detail_verification = compare_route_geometry(detail_geometry or props, result)
                if detail_verification['status'] in {'changed', 'unresolved'}:
                    raise RouteVerificationError({'status':detail_verification['status'],'source':'detail','geometry':detail_verification})
                if previous_match:
                    return VerifiedRoute(result, {'write_acknowledged':True, 'editor':editor_verification,
                                                 'detail':detail_verification, 'readback_rounds':attempt,
                                                 'consecutive_matches':2})
                previous_match = True
            except RouteVerificationError as exc:
                previous_match = False
                last_error = exc
        if previous_match:
            raise RouteVerificationError({'status':'unresolved','reason':'readback_not_stable'})
        if last_error: raise last_error
        raise RouteVerificationError({'status':'unresolved','reason':'readback_not_stable'})

    except (OSError, StravaError, ValueError, KeyError, TypeError) as exc:
        raise RouteWriteError(operation, route_id, stage, getattr(exc, 'verification', {'status':'unresolved','reason':'readback_unavailable' if stage=='readback' else 'submission_not_acknowledged'})) from exc


def build_route(requests: list[dict[str, Any]], save_full: bool = False) -> dict[str, Any]:
    """Build without saving a route; optionally export the full response locally."""
    if not isinstance(save_full, bool): raise ValueError("save_full must be a boolean")
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
    if save_full:
        fd, name = tempfile.mkstemp(prefix='strava-build-', suffix='.json')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(response, handle, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            return {'result_count': len(built),
                    'leg_count': sum(len(row['legs']) for row in built),
                    'full_build_file': name, 'full_build_format': 'strava-build-v1',
                    'full_build_byte_size': Path(name).stat().st_size}
        except Exception:
            Path(name).unlink(missing_ok=True)
            raise
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


def update_route(route_id: str, patch: dict[str, Any], confirm: bool, base_geometry_sha256: str | None = None) -> dict[str, Any]:
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
        unchanged = {}
        if base_geometry_sha256 is not None:
            if not {'elements', 'legs'}.issubset(patch):
                raise ValueError('Geometry baseline requires elements and legs')
            baseline = _get_route_full(route_id)
            if fingerprint(baseline) != base_geometry_sha256:
                raise ValueError('Route geometry changed since preparation; fetch save_full and prepare again. No write submitted.')
            # Preserve fresh editor geometry for untouched prefix/suffix legs.
            # Source detail geometry may have been normalized differently.
            patch = copy.deepcopy(patch)
            def same_leg(i, j):
                return (patch['legs'][j]['paths'] == baseline['legs'][i]['paths'] or
                        [p['polyline'] for p in patch['legs'][j]['paths']] == [p['polyline'] for p in baseline['legs'][i]['paths']]) and [e['waypoint']['point'] for e in patch['elements'][j:j+2]] == [e['waypoint']['point'] for e in baseline['elements'][i:i+2]]
            if len(prepared['legs']) != len(baseline['legs']):
                raise ValueError('Editor and detail leg structures disagree; refresh before saving')
            left = 0
            while left < min(len(patch['legs']), len(baseline['legs'])) and same_leg(left, left):
                unchanged[left] = baseline['legs'][left]
                patch['legs'][left] = copy.deepcopy(prepared['legs'][left]); left += 1
            i, j = len(baseline['legs'])-1, len(patch['legs'])-1
            while i >= left and j >= left and same_leg(i, j):
                unchanged[j] = baseline['legs'][i]
                patch['legs'][j] = copy.deepcopy(prepared['legs'][i]); patch['legs'][j]['startElement'] = j
                i -= 1; j -= 1
            if len(patch['legs']) == len(baseline['legs']):
                for index in range(left, j+1):
                    if same_leg(index, index):
                        unchanged[index] = baseline['legs'][index]
                        patch['legs'][index] = copy.deepcopy(prepared['legs'][index])
        for field, value in copy.deepcopy(patch).items():
            if field == "routePrefs":
                prepared[field].update(value)
            else:
                prepared[field] = value
        _validate_geometry(prepared)
        prepared["routeId"] = route_id
        detail_geometry = copy.deepcopy(prepared)
        for index, leg in unchanged.items(): detail_geometry['legs'][index] = leg
        return _save_route(session, "update", prepared, route_id, detail_geometry)


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
