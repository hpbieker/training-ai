---
name: olympiatoppen
description: Read and inspect logged workouts in Olympiatoppen's training diary using local MCP tools.
---

# Olympiatoppen

Use `list_workouts(from_date=..., to_date=...)` for the signed-in athlete's
sessions in an inclusive range of local diary dates. For a full record, use
`get_activity` with the exact `session_id` and both dates. When the session
date is known, pass it as both bounds.

`list_workouts` also returns the source `sessionMetrics` array for each session,
including metrics such as `Opplevd belastning` and `Dagsform` when present.

## Session setup

Use `get_session_status` when diagnosing access. Ordinary diary reads already
verify the saved session.

If an MCP diary call returns `auth_required`, use the authenticated
Olympiatoppen tab in Nettleser to extract the cookie header from a real request
to the site's own `/api/Auth/Session` endpoint. Do not use `Network.getCookies`
for this site: it may return only load-balancer cookies and omit the session
cookies that the browser actually sends.

When the browser exposes CDP network events and supports private transfer to
the import tool, enable `Network`, record the current event
cursor, then evaluate `fetch('/api/Auth/Session', {credentials:'include'})`
and read the resulting network events. Match
`Network.requestWillBeSentExtraInfo` to the `Network.requestWillBeSent` event
whose URL path is exactly `/api/Auth/Session`, using its `requestId`. Take only
the `cookie` header from that matching `ExtraInfo` event and pass it directly
as `cookie_header` to `import_session`. Do not return the cookie from the
browser step as user-facing text, inspect unrelated origins, or pass any other
headers or response data. If the auth request is not successful or no Cookie
header is present, stop and report that the browser session could not provide
a usable cookie. The MCP verifies and stores the cookie privately. After a
successful import, repeat the diary call that returned `auth_required`.
Use `clear_session` only when the user asks to remove the saved session.
Nettleser is only for obtaining a replacement cookie when the MCP session
needs renewal; all diary reads remain in MCP.

## Diary records

- Match records using local date and session identity. Distinguish a logged
  session from a planned entry; do not infer completion from a plan or title.
- Treat the diary as the source for its descriptions and recorded structure.
  Preserve source wording and line breaks when copying it; don't invent missing
  text, intensity, or repetition counts.
- Keep activity type, session name, description, and recorded metrics separate.
- Include the session ID when it helps distinguish similar entries.
