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
refresh.

Use `planning-context.json` beside the recommendation packet only when an
auditable trace of resolved logistics is useful. It is LLM-authored context,
not a helper input contract.

## Readiness Composition

- Fetch volatile inputs through their source plugins and pass normalized JSON
  to repo helpers. Do not pass raw API payloads into readiness consumers.
- Use direct physiological domains—HRV relative to baseline, resting HR,
  sleep, Body Battery, stress, and body feel—plus cumulative load and recent
  workout response.
- Show both Body Battery at wake and most recent when present. The first is
  overnight recovery context; the second is current energy context. Neither is
  decisive alone, and stale current data must be labelled.
- Keep aggregate Training Readiness diagnostic-only. Do not separately weight
  it or yesterday's workout on top of the underlying direct signals.
- Project timestamped recovery estimates to the planned start when appropriate,
  assuming no intervening training and stating that assumption.
- Interpret load relative to the athlete's history. Check rolling seven-day and
  calendar-week distributions before calling load high or low, especially when
  challenged or when it changes the recommendation.
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
