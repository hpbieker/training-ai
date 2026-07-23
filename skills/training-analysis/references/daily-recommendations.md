# Daily Training Recommendations

## Resolve Context First

Before running helpers, resolve the local date, planned start or free window,
location/start anchor, available modalities, surface/bike intent, target event
and time horizon, and practical fueling defaults. Use the configured earliest
preferred start when no time is supplied; if calendar context exists, move to
the first practical free window at or after it.

Pass these choices explicitly to `recommend_today.py`. Its default
`--refresh auto` reuses source snapshots within their TTL. Use `--refresh all`,
a comma-separated source list, or `--refresh none` only deliberately. An
explicit normalized `--garmin-json` cannot be combined with forced Garmin
refresh. Always pass the resolved intensity goal with the required
`--intensity-goal`; the helper has no default training goal. Readiness still
determines the highest intensity the recommendation may select.

Use `planning-context.json` beside the recommendation packet only when an
auditable trace of resolved logistics is useful. It is LLM-authored context,
not a helper input contract.

## Readiness Composition

- Fetch volatile inputs through their source plugins and pass normalized JSON
  to repo helpers. Do not pass raw API payloads into readiness consumers.
- Use direct physiological domains—HRV relative to baseline, resting HR,
  sleep, Body Battery, stress, and body feel—plus cumulative load and recent
  workout response.
- Interpret Body Battery by time of day. Use the wake value as overnight
  recovery context and the current value as remaining energy at its timestamp.
  A value concerning at wake may be normal later. Consider change since wake
  and intervening training; do not adjust the Xert dose from either value alone.
- Keep aggregate Training Readiness diagnostic-only. Do not separately weight
  it or yesterday's workout on top of the underlying direct signals.
- Project timestamped recovery estimates to the planned start when appropriate,
  assuming no intervening training and stating that assumption.
- Use Xert recovery hours as the first model gate for low/high/peak load, then
  compare the corresponding Xert Recovery Load with Training Load. Use Xert
  target XSS as the remaining recommended dose when available.
- Treat rolling seven-day totals as descriptive context. Do not use a historical
  percentile unless its metric, coverage period, complete-window count, and
  validation status are explicit. Never mix XSS with Intervals or Garmin load.
- Separate historical/cumulative load from acute physiological response. A
  normal load does not make mixed acute signals disappear.

## Illness And Return

A structured current-day sickness event overrides model readiness: recommend no
training. If only the previous day is marked sick, ask whether symptoms remain
or this is the first healthy day; until clarified, offer rest or a provisional
very-easy return only.

After the last sick day, default to two intensity-free return days: day one is
rest or 20–45 minutes very easy; day two is 30–60 minutes easy endurance. Cap
candidate duration/load to that ramp rather than merely describing it. Resume
normal logic from day three only if the athlete feels healthy.

## Dose And Intensity

- Use readiness to set the intensity ceiling. Within that ceiling, use the
  resolved goal and progression history to select the concrete domain; recent
  same-family hard work can reduce the selection to VT1.
- Treat the recommendation packet as evidence. The final coaching decision must
  also account for goals, future sessions, logistics, weather, and body feel.
- A hard session requires agreement across the important direct signals; stale
  or conflicting data should reduce confidence before increasing intensity.
- Inspect today's soreness before hard work. Missing soreness alone does not
  downgrade the session, but ask the user to record it; explicit zero counts as
  present.
- When cumulative load is normal but acute signals are cautious, prefer adding
  easy endurance duration over intensity when logistics and body feel permit.
- If offering a dose beyond a helper guardrail, label it as a conditional
  coaching override and use a 15-minute breathing/HR/body-feel gate.
- Keep model-specific recovery, target-load, and capacity concepts distinct.
  Use source semantics rather than re-explaining private-model formulas here.

## Candidate Selection

For `rest`, retain only rest or explicit recovery candidates within the cap.
For `easy_vt1`, retain recovery/endurance candidates within duration and load.
Suppressed harder workouts remain audit context, not normal options.

Indoor trainer sessions default to ERG unless the user requests another mode.
Use an existing suitable workout as-is when it fits; modify power, duration, or
repetitions only for a concrete readiness, time, load, or specificity reason.
Do not add warm-up outside a workout whose total already includes it.

## Final Answer Contract

- Follow `primary_decision.action` and `primary_decision.executable_now` as the
  default recommendation. Treat `remaining_after_completed_activities` as a
  remaining dose whose same-day activities are already accounted for; never
  subtract them again. Do not schedule an `unscheduled_remainder` without a real
  available window. If new information justifies a different recommendation,
  label it as a coaching override and state which packet input did not cover it.
- Start with the recommended session and best time.
- If both cycling modalities are available, provide one concrete indoor and one
  concrete outdoor option with duration, warm-up, watts/intensity, setup/route,
  and countable fueling actions.
- Explain briefly why the winner fits readiness, recent load, weather, calendar,
  goals, and reported body feel.
- Keep the chosen prescription distinct from reference watt anchors for other
  zones.
- State whether timing was user-provided or assumed and identify stale/missing
  inputs that materially limit confidence.
