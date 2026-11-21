---
name: route-planner
description: Plan cycling routes through ordered waypoints.
---

# Route Planner

Use `plan_route` with verified coordinates for the start, end and any stops
or roads the user wants to pass. Put waypoints in travel order. If the route
misses a required waypoint, verify the point on the intended road before
retrying. The planner sends coordinates to BRouter and saves the route locally.
