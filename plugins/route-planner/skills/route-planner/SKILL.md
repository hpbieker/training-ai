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
