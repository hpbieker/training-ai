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
- Point lookups start with three candidates, fetch their samples together, and
  expand only for insufficient coverage. They do not fetch series availability
  separately. Station metadata is reused for 15 minutes, scoped to validity
  dates; observations are not cached. The same station is used for all elements
  in a point result, including partial results.
- Quality codes are returned unchanged. Consult Frost's available quality-code
  definitions before excluding or interpreting a flagged value.
- Frost's interval endpoint is exclusive; the tools adapt it to the documented
  inclusive local window and filter returned samples accordingly.
- Data requests use client-ID Basic authentication with an empty password.
  Only the public archive is accessed; there is no OAuth flow or account creation.
