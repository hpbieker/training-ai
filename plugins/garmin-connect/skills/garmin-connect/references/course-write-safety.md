# Garmin Course Write Safety

## Upload

- Fetch and save the source with `course <course-id>` before creating a copy.
- Use `course-upload` with that JSON. Do not round-trip through GPX when exact
  Garmin geometry or named course points matter.
- Give a copy a distinct name unless the user explicitly asks for the same one.
- The uploader removes server-owned fields such as `courseId`, timestamps, and
  source-application attribution. Garmin assigns new values and may normalize
  fields such as elevation source or segment matching.
- Treat `verification.verified: true` as confirmation that stable summary
  fields, the complete `geoPoints` array, and course-point names survived the
  read-back. If it is false, report the new course ID and mismatches; do not
  automatically delete the created course.
- Never print or persist the access token returned by `gccli`.

## Delete

- Deletion is permanent in Garmin Connect. Resolve the course ID and name with
  `course <course-id>` immediately before deletion.
- Require explicit user authorization for that target. Pass the same numeric ID
  to both `<course-id>` and `--confirm-course-id`.
- Do not delete the source route merely because a copy was created.
- Report the deleted ID and name only after the post-delete list check succeeds.
