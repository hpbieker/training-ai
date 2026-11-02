---
name: komoot
description: List Komoot tours, inspect tour metadata and full route geometry, or download planned tours as FIT using the Komoot MCP and existing Safari login.
---

# Komoot

Use `list_tours` to find the signed-in account's planned tours; it also supports
recorded tours, all tours, name search, and pagination. Use
`get_tour_metadata` for one tour's metadata without geometry, or
`get_tour_route` for the complete coordinates, directions, way types, and
surface payload. Both read tools accept a numeric tour ID or full tour URL.

Use `get_tour_line` for Komoot's native geometry from `/tour_line`. Use
`download_tour_gpx` for a validated GPX export when moving a route to another
service or device.

Use `rename_tour` only for an explicitly requested rename. It requires
`confirm=true`, checks that the tour appears in the signed-in account's
planned-tour list, rejects folder separators, then reads the tour back and
requires the exact new name. Komoot does not offer a public API, so this write
uses an undocumented web endpoint. If the result is `komoot_write_unverified`,
read the tour's current name before retrying; the mutation may already have
reached Komoot.

Use `download_tour_fit` for a planned tour's FIT export. The local server reads
matching Safari cookies from curl-safari's Unix socket; cookies are never tool
arguments or printed. By default, the FIT file is saved in the training-ai
workspace as `<tour-id>.fit`. Choose an explicit absolute `output_path` when
another destination is requested. Existing files are preserved unless
`overwrite=true` is supplied.

This supports planned tours for which Komoot provides a FIT or GPX export. The
server does not use the website UI or prompt for Komoot credentials.

## Data sources

All tour reads, listing, FIT/GPX export and rename use
`https://www.komoot.com/api/v007` with Safari cookies from the local socket.
Route readers call the API directly, with no HTML fallback. Full route data
uses `_embedded=coordinates,way_types,surfaces,directions`; `get_tour_line`
uses `/tours/<id>/tour_line`. Before each API request, the server initializes a web session with a home-page
GET and retains its Set-Cookie updates in the same in-memory cookie jar for
the API request. This exchanges Safari refresh cookies for API session cookies.
Nothing is written back to Safari or saved on disk, and API calls are not
automatically retried. The home page also resolves the signed-in user ID for
listing and ownership checks.

The rename tool has ownership checks and readback, but a live rename has not
been verified as part of this fix. Do not claim that writes were tested based
on successful read or export calls.

## Planning points, inspection and comparison

Use `get_tour_waypoints` for the API's ordered `path` planning points, retaining
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
identity or prove a route is identical. The reusable computations live in
`route_analysis.py` and have no Komoot or Strava dependency.
