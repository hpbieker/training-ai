# Strava Write Safety

Perform writes only when the user explicitly requests them. Keep authentication
material ephemeral and verify the saved state afterward.

## Activity Changes

Use `strava_session_from_safari.py` to obtain the live Safari cookies through
curl-safari. Put them in a mode-0600 temporary file and pass the file through
`--cookie-file`; never put cookie values in command arguments. Read the
activity back after each change.

Supported primary tag form values include `Race`, `Workout`, `Commute`,
`ForACause`, `Recovery`, `WithKid`, and `WithPet`.

Indoor cycling is not a normal primary tag. It is controlled by the trainer
flag and may appear as tag id 6 in the training API. Strava can refuse to unset
trainer for an indoor activity, so verify the resulting state.

Keep the edit-page CSRF token and `_strava4_session` cookie from the same live
session. Do not split the edit GET and form POST across unrelated cookie state;
a mismatch can redirect to the dashboard without applying the change.

## Route Creation And Updates

Build first and inspect the actual geometry before creation. Build is
non-persistent; create/update mutates the user's Strava account.

Keep new route visibility `OnlyMe` unless the user explicitly requests another
setting. Resolve the exact route ID before updating an existing route.

Create success returns a route ID. Update has been observed to return
`{"updateRoute": null}` on success. In both cases, verify the resulting route
page and metadata through the authenticated Strava state rather than relying
only on the POST response.

Never retain Cookie or CSRF headers. Obtain fresh session state through
curl-safari, use the private cookie file with the shared Python HTTP session
for the active workflow, and delete the file afterward. Use browser-curl-replay
only if curl-safari cannot provide the required session cookie.

Resolve activity IDs with a date-bounded `strava_activities.py` query before a
batch write. Do not select duplicate activity names without checking ID and
local start date. For a multi-activity update, require one readback result per
requested ID and report the saved tag, trainer flag, visibility, bike, and
hidden-start-time state.
