# Strava Write Safety

Perform writes only when the user explicitly requests them. Keep authentication
material private and verify the saved state afterward.

## Activity Changes

Use Safari Web Inspector Copy as cURL and `strava_session.py import-curl`
when the session needs renewal. Store the reusable Cookie header in the mode-0600 cache at
`~/.strava/session.headers`; never put cookie values in command arguments. Read the
activity back after each change.

Supported primary tag form values include `Race`, `Workout`, `Commute`,
`ForACause`, `Recovery`, `WithKid`, and `WithPet`.

Indoor cycling is not a normal primary tag. It is controlled by the trainer
flag and may appear as tag id 6 in the training API. Strava can refuse to unset
trainer for an indoor activity, so verify the resulting state.

Keep the edit-page CSRF token and `_strava4_session` cookie from the same live
session. Do not split the edit GET and form POST across unrelated cookie state;
a mismatch can redirect to the dashboard without applying the change.

## Activity Media

List the exact activity's media before downloading or changing it. Download
only a media ID returned by that listing, save to an explicit local directory,
and do not overwrite a local file without explicit confirmation.

Attaching media is an activity write and requires the caller's exact activity
ID, local file path, and explicit confirmation. Strava's web flow first returns
a short-lived storage URL and headers, then attaches the uploaded object through
the activity edit form. Send the Strava session cookie only to Strava hosts;
never forward it to the storage URL. Read the edit-page media state again and
report success only when the uploaded media appears.

## Route Creation And Updates

Build first and inspect the actual geometry before creation. Build is
non-persistent; create/update mutates the user's Strava account.

Save exactly one complete path per leg. Multiple native paths may be alternative
paths: Strava was observed to retain only the first during later processing.
Use `prepare_route_update.py` to merge sequential sections before saving.
Pass its `base_geometry_sha256` to reject an outdated geometry snapshot before
submission. Untouched geometry is preserved from the fresh editor state;
editor and detail readbacks use their respective fresh baselines.

Keep new route visibility `OnlyMe` unless the user explicitly requests another
setting. Resolve the exact route ID before updating an existing route.

Create success returns a route ID. Update has been observed to return
`{"updateRoute": null}` on success. In both cases, verify the resulting route
page and metadata through the authenticated Strava state rather than relying
only on the POST response.

Create/update success retains source-native route JSON, with verification in
MCP `_meta.route_verification`. Both editor and detail geometry must be exact or
equivalent within 2 metres under an order-preserving comparison. Changed or
unresolved results remain `write_unverified`, with `details.verification`
identifying fields/legs and deviation locations when available. Sampling and
work limits can produce unresolved results; never treat these as success or
retry automatically. Geometry tolerance is not confirmation of a particular
carriageway or of legal cycling access.

Verification requires two matching readback rounds, with a two-second wait
after the initial round and one further three-second wait when needed. A
transient mismatch can settle, but a final mismatch or insufficient consecutive
matches remains unverified. Never repeat the POST automatically. The finite
readback window cannot guarantee that later asynchronous changes never occur.

Retain the private Cookie header until Strava rejects it, it is replaced by a
newly verified Safari capture, or the user explicitly clears it. Never retain
CSRF headers or a complete copied cURL command. Follow browser-curl-replay for
the Web Inspector capture; MCP does not refresh the session itself.

Resolve activity IDs with a date-bounded MCP `list_activities` query before a
batch write. Do not select duplicate activity names without checking ID and
local start date. For a multi-activity update, require one readback result per
requested ID and report the saved tag, trainer flag, visibility, bike, and
hidden-start-time state.
