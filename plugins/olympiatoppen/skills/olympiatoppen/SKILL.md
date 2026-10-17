---
name: olympiatoppen
description: Read and inspect logged workouts in Olympiatoppen's training diary using local MCP tools.
---

# Olympiatoppen

Use the MCP tools `list_workouts` and `get_activity` for all diary reads.
Dates are local diary dates; use inclusive date ranges. Use `get_activity` with
its exact session ID and a narrow date range, normally the single known session
date.

`list_workouts` also returns the source `sessionMetrics` array for each session,
including metrics such as `Opplevd belastning` and `Dagsform` when present.

## Session setup

If an MCP diary call returns `auth_required`, use the authenticated
Olympiatoppen tab in Nettleser to extract the cookie header from a real request
to the site's own `/api/Auth/Session` endpoint. Do not use `Network.getCookies`
for this site: it may return only load-balancer cookies and omit the session
cookies that the browser actually sends.

Use the tab's CDP capability: enable `Network`, record the current event
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
- Fetch only the requested athlete and date range.

## Output

- Use a date-ordered table when presenting multiple sessions.
- Include session links or IDs when they help locate a record.
- Keep uncertainty visible when matching is ambiguous.
