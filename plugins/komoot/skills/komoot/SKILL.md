---
name: komoot
description: Find, inspect and compare Komoot tours, read waypoints and surfaces, export FIT or GPX files, and rename planned tours.
---

# Komoot

Use `list_tours` to find the signed-in account's planned tours; it also supports
recorded tours, all tours and name search. Follow `next_page` with the same
filters when more results are needed. Use
`get_tour_metadata` for one tour's metadata without geometry, or
`get_tour_route` for the complete coordinates, directions, way types, and
surface payload. Both read tools accept a numeric tour ID or full tour URL.

Use `get_tour_line` for Komoot's native route geometry.

Use `rename_tour` only for an explicitly requested rename. It requires
`confirm=true`, checks that the tour appears in the signed-in account's
planned-tour list, rejects folder separators, then reads the tour back and
requires the exact new name. If the result is `komoot_write_unverified`,
read the tour's current name before retrying; the mutation may already have
reached Komoot.

Use `download_tour_fit` or `download_tour_gpx` when a file is needed. Pass
an absolute `output_path` for a specific destination. The default directory
depends on the plugin installation. Use the returned `file_path` for handoff.
Set `overwrite=true` only when replacing the existing file is intended.
Live access uses the signed-in Safari session and local curl-safari service.

## Planning points, inspection and comparison

Use `get_tour_waypoints` for ordered planning points, retaining
all locations and coordinate indices. These are distinct from route geometry.
Use `inspect_tour` to report way types, surfaces and Komoot warnings with start
and end positions and approximate distance along the route. Distances are
calculated with haversine between geometry vertices, rather than copied from
Komoot's distance total. Preserve category codes and do not infer pedestrian
access or a legal cycling ban solely from a way type. `BICYCLE_DISMOUNT` means
Komoot marks a section where the bike should be pushed.

Use `compare_tours` with `tour` plus exactly one of `other_tour` or `coordinates`
(external objects with `lat` and `lng`). This also accepts geometry read from
Strava. It compares spatial paths in both directions at regular intervals,
returning deviation ranges, sample locations, and lengths. It ignores traversal
order, so reversed paths or different loop order can match spatially. Short
changes between samples can be missed. Lower `sample_spacing_m` for closer
inspection, subject to the bounded work limit. It does not establish road
identity or prove a route is identical.
