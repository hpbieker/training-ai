# Frost Historical Observations

Source: [MET Norway Frost API](https://frost.met.no/api.html), especially
[time and level concepts](https://frost.met.no/concepts2.html#relationshipreftime).

- Station observations are point measurements, not conditions measured along
  a route or weather model estimates at arbitrary coordinates. Consider distance,
  altitude and exposure before comparing with a forecast or a bike sensor.
- These tools request subdaily time resolutions only. For subdaily data,
  `referenceTime` is already the observation time: do not add `timeOffset`.
  Daily/monthly data have different conventions and are outside this interface.
- Outputs retain original reference time, time offset, time resolution, sensor
  level, time-series ID, performance category and quality code. Local timestamps
  use the requested IANA timezone. Include an explicit UTC offset for ambiguous
  or nonexistent wall times around DST changes.
- The API uses default sensor levels/time offsets and the main time series.
  Do not merge different measurement heights or parallel sensors silently.
- Accumulated precipitation retains its exact element ID, e.g.
  `sum(precipitation_amount PT1H)`. A historical accumulation is not the
  forecast's next-hour precipitation. Preserve the period and source semantics.
- Missing samples stay missing, not zero; availability metadata says a series
  overlaps the interval, not that all expected samples are present. Batch results
  may have different actual observation times per element, each within tolerance.
- Quality codes are returned unchanged. Consult Frost's available quality-code
  definitions before excluding or interpreting a flagged value.
- Frost's interval endpoint is exclusive; the tools adapt it to the documented
  inclusive local window and filter returned samples accordingly.
- Data requests use client-ID Basic authentication with an empty password.
  Only the public archive is accessed; there is no OAuth flow or account creation.

## Station search, sampling and cache

- Use `find_observation_stations` with coordinates, timezone, local window and
  exact Frost element IDs. The search starts with at least three candidates
  (or the requested result limit) and expands through 10, 25 and 50 only when
  coverage is insufficient. Results are ranked by distance among candidates
  with all requested series available in the window. Availability
  metadata does not guarantee complete samples. Check altitude and exposure.
- Use `get_observation_series` for up to 10 known station IDs and 10 elements,
  an inclusive window of up to 31 days, and `PT1H` (default) or `PT10M` resolution.
  Requests are bounded to 50000 expected samples; reduce scope when necessary.
- Use `get_observations_summary` for temperature, hourly precipitation and
  snow depth near up to 25 points over one shared window. Each point references
  the nearest station with samples for each requested element. Shared station
  summaries appear once. Check distance, altitude and missing hours before
  using the results. When available, compare snow samples around the first
  and last wet hours. Frost's snow value `-1` means zero depth or partial snow
  cover and yields no numeric change when it occurs at either endpoint.
- Use `get_observations` for 1–25 selected point/time requests. It starts with
  three nearby candidates and fetches their observations in one request,
  normally making two API calls per point. It expands to 10, 25 and 50 candidates
  only when coverage is incomplete, fetching only newly encountered stations.
  It prefers complete element coverage then distance, and
  selects the nearest sample per element within `tolerance_minutes` (default
  60, maximum 180). Ties select the earlier sample. Each result uses one station;
  inspect actual times, missing elements, warnings and per-point errors.
- Station metadata and series-availability metadata are cached for 15 minutes
  in the server process, in a bounded cache. Metadata found by a nearest search
  is reused for explicit station reads for the same validity interval. Repeated
  point lookups normally need only the observation request. Observations are
  always fetched fresh. `available_series` is empty for point results because
  those use actual sample coverage rather than a separate availability request.
