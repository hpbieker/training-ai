# Strava Write Safety

Perform writes only when the user explicitly requests them. Keep authentication
material ephemeral and verify the saved state afterward.

## Activity Changes

Preferred helper:

```bash
python3 -B plugins/strava/scripts/strava_activity_tags.py <activity-id> \
  --tag Workout --trainer true --visibility only_me --start-time-hidden true
python3 -B plugins/strava/scripts/strava_activity_tags.py <activity-id> --read
```

Supported primary tag form values include `Race`, `Workout`, `Commute`,
`ForACause`, `Recovery`, `WithKid`, and `WithPet`.

Indoor cycling is not a normal primary tag. It is controlled by the trainer
flag and may appear as tag id 6 in the training API. Strava can refuse to unset
trainer for an indoor activity, so verify the resulting state.

The helper keeps the edit-page CSRF token and `_strava4_session` cookie in the
same temporary jar. Do not split the edit GET and form POST across unrelated
cookie state; a mismatch can redirect to the dashboard without applying the
change.

## Route Creation And Updates

Use `strava_route_api.py build` first and inspect the actual geometry before a
create or update. Build is non-persistent; create and update mutate the user's
Strava account.

Keep new route visibility `OnlyMe` unless the user explicitly requests another
setting. Resolve the exact route ID before updating an existing route.

Create success returns a route ID. Update has been observed to return
`{"updateRoute": null}` on success. In both cases, verify the resulting route
page and metadata through the authenticated Strava state rather than relying
only on the POST response.

Never use a create/update body copied from a browser with persisted Cookie or
CSRF headers. Retain only the reviewed JSON body and obtain fresh session state
at runtime.
