---
name: strava
description: Read Strava activities, kudos, gear and media, edit activity metadata and attachments, or build and manage Strava routes from waypoints or a target distance.
---

# Strava

Use the local MCP tools for activity, saved routes, gear, and media
operations. The server reads
`~/.strava/session.headers` for each operation; it does not authenticate through
Safari, refresh cookies, or retry failed writes.

## Authentication

On `auth_required`, open an authenticated Strava page in Safari. In Web
Inspector, reload with the Network panel open, select a request to
`www.strava.com` with a Cookie header, and choose **Copy as cURL**. With the
request on the clipboard, run the importer from the Strava plugin directory:

```sh
python3 -B scripts/strava_session.py import-curl
```

The importer verifies and stores the Cookie header in the private session
cache. Keep cookies, CSRF and Authorization headers and the full cURL command
out of chat, logs and arguments. Retry the original read after renewal. Before
retrying a write, check the remote state. For partial batches inspect
`details.updated`, `details.failed` and `details.not_attempted` before choosing
which items to retry.

See [session diagnostics](references/route-builder.md#session-diagnostics) for cache paths
and troubleshooting.

## Activities

Read [references/write-safety.md](references/write-safety.md) before writes.
Use MCP `list_activities`, `get_activity`, `list_gear`, `get_gear`,
`update_activity`, and `update_activities`. Discover exact IDs through reads;
`list_activities` accepts inclusive `since` and `until` dates. It scans from
the newest page up to `max_pages` and returns matching activities. For an
older period, an empty result can mean the scan stopped before reaching it.
Activity metadata writes take a `patch` and `confirm=true` for an already
authorized action. Omitted fields are
preserved. Use `tag: null` to clear a tag or `bike_id: "none"` to clear a bike.
Visibility, hidden start time, and mute are independent settings. Updates verify
API metadata plus edit-page-only bike, start-time, and mute state.

`start_date_local` is the activity's local wall-clock time. Use `start_utc`
when present to compare start times across sources or timezones.

Activity, gear, and media operations are available only through MCP. The Python
activity helpers are internal modules without CLI entry points. Use MCP
`build_route` for explicit waypoint pairs. CLI helpers handle session
management, target-distance route candidates and route analysis.

Use `list_gear` to retrieve current and retired bikes and shoes. `get_gear`
accepts an ID returned by that list; provide `gear_type` (`bike` or `shoe`) when
the type is already known.

Use `get_activity_kudos(activity_id)` to read who gave kudos to one exact
activity through the existing browser session. It returns `athletes` with native
source fields, `count` (the number of returned athletes), `is_owner`, and
`kudosable`. It never gives kudos. Missing or malformed data is an error, not
zero kudos. The browser endpoint exposes no pagination metadata; `count` is
the returned list size rather than a separately verified total.

Use `list_activity_media` with one exact activity ID before downloading or
changing attachments. For an authorized removal, pass the listed `media_id`,
`activity_id` and `confirm=true` to `delete_activity_media`. The tool checks
that the attachment disappeared. `download_activity_media` requires the
returned `media_id` and an explicit `destination_dir`. An existing file is replaced only when
`overwrite=true` is explicit.

`upload_activity_media` is an activity write. It accepts one local JPG, PNG,
GIF, MP4, or MOV file and requires `confirm=true`. The upload is staged through
Strava's short-lived media-storage URL, then attached through the activity edit
form. Do not send the Strava cookie to that storage URL. Report success only
after fresh media-list readback confirms the attachment.

Pass absolute local paths in `destination_dir` and `file_path`. Media IDs may be
UUIDs; preserve the exact `media_id` returned by the list. If an upload fails
with an uncertain result, list the activity's media again before retrying to
avoid attaching it twice.

## Routes

- Use `list_routes` to discover saved routes and exact IDs. Continue with
  `next_cursor` when `has_more` is true. Use `get_route(save_full=true)` when the
  task requires complete geometry. Reuse the returned `full_route_file` for
  inspection and patch preparation.
- Use `build_route` for explicit waypoint pairs and `strava_build_route.py` for
  candidates from a start point and target distance. Inspect the geometry and
  [route quality](references/route-quality.md) before saving. See the
  [route-builder reference](references/route-builder.md) for payloads and
  candidate selection.
- Use `prepare_route_update.py` to prepare local section, point or batch edits.
  Follow the [route-editing examples](references/route-editing.md) to prepare
  and inspect the patch and retain its geometry fingerprint.
- Use `create_route`, `update_route` or `delete_route` only for an explicitly
  requested write with `confirm=true`. Read the
  [write-safety reference](references/write-safety.md#route-creation-and-updates),
  resolve the exact target, and inspect the verified result. Keep new routes
  private unless the user asks for public visibility.
- Treat `write_unverified` as unresolved. Check the route and the verification
  details before retrying. When creation returns no ID, check `list_routes` for
  the proposed route before attempting another create.

## Boundaries

This plugin owns Strava session mechanics, route-builder payloads, activity
mutations, and readback verification. The caller owns personal route
preferences, candidate selection, maps, and final route or training decisions.
