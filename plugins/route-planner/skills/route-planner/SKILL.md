---
name: route-planner
description: Plan, edit, inspect and export cycling routes, verify roads and travel direction, or display saved routes and imported rides on an interactive map.
---

# Route Planner

## Plan and verify

- Use `create_route` to create a saved route from verified coordinates in travel order.
  Retain its `route_id` for later reads and edits. Preserve explicit
  stops and choose guide points on the through route for areas the user wants to
  pass. For a directional loop, place verified guides on each flank between the
  split and rejoin. Check their order before planning. Clockwise means southbound
  on the east flank and northbound on the west flank.
- Use `search_places` for public places and keep personal or confidential details
  out of queries. Treat place centres as lookup hints and include OpenStreetMap
  credit when presenting search results.
- Use `find_road_points` for guides on carriageways. Pass an exact mapped name or
  reference when known, or omit the road filter and verify the returned road.
  For a requested cycleway or other cycling-only link, use a point verified
  against mapped cycling geometry. If a guide misses the route, find another
  point in the same corridor.
- Use `inspect_route` to check requested corridors, direction and unintended
  detours before reporting the result. Confirm road identity from mapped roads
  and junctions. Use `locate_on_route` to compare kilometre markers, offsets and
  bearings for separate passages near a point, including suspected retracing.
  Report any required corridor or direction you could not verify.

## Edit and compare

- Read the latest summary with `get_route` and pass its revision as
  `expected_revision`. Use `move_waypoint` for a move and
  `add_waypoint.after_waypoint_id` to insert after a waypoint. Omit
  `after_waypoint_id` to insert after the start. For multiple changes, use an
  ordered `waypoints` list and preserve retained IDs. After a revision conflict,
  read the latest summary again before retrying.
- When the user prefers a parallel carriageway, limit lookups, trials and edits
  to the requested area unless the preference is route-wide. Use
  `inspect_route` with a narrow `distance_range` around the middle route
  kilometre of the path section. Use a returned on-route coordinate as
  `near` for the road lookup. Place new guides alongside the affected section
  and in travel order on each affected pass.
- Use `evaluate_route_change` to preview an edit against `expected_revision`.
  It uploads the routing profile and sends the proposed coordinates to BRouter
  while keeping the saved route at its current revision.
  `same_profile: true` with zero changed sections is
  strong evidence that the route geometry is preserved. If
  `changed_section_count` exceeds the number of returned spans, the preview is
  incomplete. Its span endpoints are insufficient to confirm road identity.
- When the user wants an edit saved, use `update_route`, then inspect the new
  revision for road identity and side trips. For local edits, check that the
  surrounding route is preserved. If both directions matter, check each pass
  independently.

Use `show_route` when the user asks for a map. Pass `route_id` for a saved
route or an absolute `route_file` for an existing GPX, GeoJSON or training-ai
route JSON. Label a draft if a required corridor or direction is unresolved.
Use `export_route` for a requested route file. GPX is the default and replaces
the GPX export for that revision. GeoJSON returns the existing file.
