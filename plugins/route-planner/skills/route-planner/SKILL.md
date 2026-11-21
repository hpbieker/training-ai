---
name: route-planner
description: Plan and update cycling routes through ordered waypoints.
---

# Route Planner

Use `plan_route` with verified coordinates for the start, end and any stops
or roads the user wants to pass. Put waypoints in travel order. If the route
misses a required waypoint, verify the point on the intended road before
retrying.

Use `update_route` to change a saved route. Pass the route ID and revision from
the latest successful call, preserve waypoint IDs for points the user wants
to keep, and check the returned points after updating. If the revision has
changed, use `get_route` to read the latest route before retrying.

Use `export_route` only when the user requests a route file.

Use `inspect_route` to check road types, surfaces or access tags on a saved
route. Filter by kilometre range or by two waypoint IDs in travel order for a
specific section. Report gaps where the saved metadata is missing.

Use `locate_on_route` to find where a saved route passes near a coordinate.
Compare kilometre markers, offsets and bearings for all passages. Use
`inspect_route` to check road metadata around a passage when needed.

Use `evaluate_route_change` to compare a proposed edit to the saved route
before applying it. Check `same_profile` and the changed sections against the
user's intended roads and travel order.

Use `search_places` for public places named in individual user requests.
Keep personal or confidential information out of the query. Include the
OpenStreetMap credit when presenting place search results.

Use `find_road_points` to choose a waypoint on the intended road near a place
or approximate coordinate. Pass an exact name or road number when known.
Check the returned road before using the point in the route.
