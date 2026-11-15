# Preparing Strava Route Edits

Run the examples from the Strava plugin directory. Read the
[write-safety reference](write-safety.md#route-creation-and-updates) before
submitting any edit.

To prepare a section update locally, run:

```bash
python3 -B scripts/prepare_route_update.py \
  --route /absolute/path/full-route.json \
  --replacement /absolute/path/replacement.json \
  --from-element 4 --to-element 7 \
  --output-dir /private/tmp/prepared-route-update
```

The source is the full file from `get_route(save_full=true)`. Replacement JSON
contains native `elements` and already built `legs`, including both boundary
waypoints. Indices are zero-based source `elements` indices, inclusive, not
kilometres or polyline vertices. Boundary coordinates must match exactly.
The helper preserves original boundary metadata and all outside geometry,
adds source-omitted `elementType=Waypoint`, and renumbers `startElement`.
It writes private `update.json` (`route_id`, `patch`, `base_geometry_sha256`) and `report.json` files
to a new directory and prints only paths and counts. It does not set `confirm`,
access the network, build paths, or save a route. Metadata and preferences are
omitted from the patch so `update_route` preserves current values.
Pass `base_geometry_sha256` unchanged to `update_route`. It checks a fresh
detail read before writing and rejects an outdated source. For untouched legs,
the service retains fresh editor geometry and verifies each source against its
own fresh baseline. Geometry changes still must match the submitted proposal.

For a local change within one leg, use point mode:

```bash
python3 -B scripts/prepare_route_update.py \
  --route /absolute/path/full-route.json \
  --replacement /absolute/path/replacement.geojson \
  --leg 15 --from-point 48 --to-point 74 \
  --output-dir /private/tmp/prepared-section-update
```

Point indices refer to decoded Google polyline vertices within the selected
zero-based leg. They are not waypoint indices or kilometres. Endpoints must
match the selected source coordinates at encoded precision by default.
Explicit `--max-join-gap-m 1.5` permits endpoint adjustments within 1.5 metres;
the default is zero. Original prefix and suffix coordinates are preserved.
Replacement accepts a GeoJSON LineString/Feature with longitude, latitude and
elevation in metres, native `{legs: [...]}`, or a `buildRoute` response whose
results are sequential sections. Each native leg must have exactly one path:
multiple paths may represent alternatives and are rejected, not concatenated.

For 2D GeoJSON supply `--elevation-profile /absolute/path/profile.json`, an
ordered array of `[distance_m, elevation_m]` covering the replacement from zero
to its complete distance. Missing heights fail rather than being invented.
GeoJSON surface type is Unknown. Distances and elevation gain/loss are computed;
grade-adjusted length is the geometric length, not a Strava grade model.
Old directions are cleared for rebuilt paths. Native elevation profiles are
trimmed and shifted along with retained geometry. Each edited leg is emitted
as one complete path so Strava cannot discard later sections as alternatives.

For multiple changes in one operation use a batch manifest:

```json
{
  "max_join_gap_m": 1.5,
  "edits": [
    {"leg": 15, "from_point": 79, "to_point": 116, "replacement_file": "ut.json"},
    {"leg": 26, "from_point": 115, "to_point": 134, "replacement_file": "retur.json"}
  ]
}
```

```bash
python3 -B scripts/prepare_route_update.py \
  --route /absolute/path/full-route.json \
  --edits /absolute/path/edits.json \
  --output-dir /private/tmp/prepared-batch
```

Relative replacement paths resolve from the manifest directory. Each edit can
also specify `elevation_profile_file` for 2D GeoJSON. All indices address the
same original route, even when earlier edits change vertex counts. Changes
within one leg are assembled together; overlapping intervals are rejected.
Adjacent intervals may share their unchanged original boundary point.

The manifest tolerance defaults to zero and applies both to internal joins in
sequential native build results and to replacement endpoints. Internal joins
move the following section's start to the previous section's end. Outer joins
move replacement endpoints to the original route, never the other way around.
No straight connector is added. Distance-based profiles are rescaled after an
adjustment. `report.json` lists every adjustment with original/new coordinates,
gap in metres, edit index, and input file hashes. Tolerance does not establish
road identity: inspect the proposal before saving. An excessive gap or invalid
edit rejects the entire batch before output files are created. Batch options
cannot be combined with single-edit flags.

Inspect geometry before submitting. Pass the prepared file directly:

```json
{"route_id": "123456789", "patch_file": "/absolute/path/update.json", "confirm": true}
```

`update_route` accepts exactly one of `patch` and `patch_file`. The latter must
be an absolute path to the `prepare-update` envelope containing `route_id`,
`patch` and optional `base_geometry_sha256`. The caller's route ID must match
the file; its geometry fingerprint is carried into the normal stale-input
check. Conflicting explicit fingerprints are rejected. Confirmation remains
an explicit tool argument; the file cannot provide it. Unknown fields, invalid
patches and malformed JSON are rejected before network access. The input file
is not modified. The verified update response remains the native full route.
