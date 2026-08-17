# Training Load, Recovery Load, and Fitness Development

Use this reference to reason about how training changes Xert's state over time.
Use `xert_cli.py load-model` for numerical answers; the mental model below is
for explaining direction, timing, and tradeoffs without inventing precision.
Read [sources.md](sources.md) before making evidence or validation claims.

## Contents

- One Model, Three Parallel Systems
- Intuitive Dynamics
- Calculation Model
- What It Takes to Build TP, HIE, or PP
- State and Interpretation Rules
- Confidence Boundary

## One Model, Three Parallel Systems

Xert tracks Low, High, and Peak separately. Each system has its own XSS,
Training Load (TL), Recovery Load (RL), time constants, and Fitness Signature
response:

| Training dose | Persistent load | Signature component |
|---|---|---|
| Low XSS | Low TL/RL | TP |
| High XSS | High TL/RL | HIE |
| Peak XSS | Peak TL/RL | PP |

The systems are parallel, but a hard effort normally produces Low XSS as well
as smaller High and Peak amounts. Do not treat the XSS split as exclusive
zones or infer intensity from percentages alone.

## Intuitive Dynamics

Think of TL as the slower memory of training and RL as the faster memory of
recent fatigue. A workout adds an impulse to both. With no new training, both
fall exponentially, but RL normally falls faster than TL. This is why Form and
freshness can improve during recovery while much of the fitness-relevant TL is
retained.

Forecast-AI does not let RL decay below its TL-linked minimum floor (called a
cap in Xert fields and the implementation). Treat it as a lower bound, never as
an upper ceiling.

- More system-specific XSS gives a larger immediate TL and RL impulse.
- Frequent training can accumulate TL because the next impulse arrives before
  the previous one has fully decayed.
- The same XSS has less net build effect at a distant horizon because its TL
  impulse has more time to decay.
- Rest does not add fitness. It reduces RL faster than TL, revealing retained
  capacity and improving Form.
- Repeating only Low XSS primarily sustains/builds TP-related TL; meaningful
  HIE or PP development requires workouts that actually generate High or Peak
  XSS.

Form is `TL - RL`. Positive Form is the fresh side of the load balance, but
Xert freshness is classified per system using Recovery Demand boundaries; it
is not determined by total Form alone. Low not recovered produces Very Tired.
High or Peak not recovered, with Low recovered, produces Tired. Very Fresh
requires all three RL values to have reached their model caps.

Training status/stars depend on total TL across the three systems. They describe
the size of the training base, not whether the athlete is recovered today.
They also depend on sufficiently complete recorded cycling power/XSS history
and do not represent subjective or whole-body readiness.

Recovery Demands moves each system's freshness boundary. A larger current
setting is more conservative and lengthens modeled recovery. This direction is
for today's Recovery Demands control; older Freshness Feedback documentation
must not be used to reverse it.

## Calculation Model

For one system with time constant `tau`, the daily impulse gain is:

```text
g(tau) = 1 - exp(-1/tau)
```

If XSS is applied at the start and the state is observed `d` days later:

```text
TL(d) = (TL0 + XSS*g(tau_TL)) * exp(-d/tau_TL)
classic_RL(d) = (RL0 + XSS*g(tau_RL)) * exp(-d/tau_RL)
RL(d) = max(classic_RL(d), TL(d)*exp(-1/tau_RL))
```

For an impulse later in the horizon, first decay to the workout time, apply the
impulse, then decay through the remaining time. Completed-activity history uses
activity start as the impulse time. A Planner forecast becomes post-impulse one
second after the planned start; the exact start remains the pre-event state.

The marginal Training-Load-matched Fitness Signature response is:

```text
TP1  = TP0  + k1_TP *(Low_TL1  - Low_TL0)
HIE1 = HIE0 + k1_HIE*(High_TL1 - High_TL0)
PP1  = PP0  + k1_PP *(Peak_TL1 - Peak_TL0)
```

Here HIE is in kJ. The change is driven by the net TL change at the requested
horizon, not raw workout XSS alone. Therefore a workout can provide a positive
impulse relative to doing nothing while the projected signature still falls
slightly below today's value if the dose is insufficient to offset decay.

`k1` is athlete- and system-specific. Always fetch current live `tau`, `k1`,
TL, RL, Recovery Demands, and Fitness Signature instead of copying example
values or fitting old history.

## What It Takes to Build TP, HIE, or PP

To gain a requested signature amount at a chosen horizon:

1. convert the desired signature gain to required TL gain with
   `required_delta_TL = desired_gain/k1`;
2. include the TL that would decay before the horizon;
3. solve for the system XSS impulse at the planned workout time.

Use the implementation rather than calculating this manually:

```bash
python3 -B plugins/xert/scripts/xert_cli.py load-model \
  --target-at 2026-08-10T09:00:00+02:00 --workout-after-hours 4 \
  --build-tp 1 --build-hie 0.5 --build-pp 5 --summary
```

The returned `single_impulse_xss_at_workout_time` values are system-equivalent
requirements. They answer how much Low, High, or Peak XSS the response model
needs; they do not prove that one physiologically feasible workout can realize
that exact combination. Use Workout Designer/strain calculations to test an
actual workout structure.

For a known planned dose:

```bash
python3 -B plugins/xert/scripts/xert_cli.py load-model \
  --target-at 2026-08-09T09:00:00+02:00 --workout-after-hours 6 \
  --low-xss 80 --high-xss 8 --peak-xss 2
```

For several workouts, use `simulate_calendar_sequence`. Planner forecasts
aggregate multiple planned events on one local day and apply the combined XSS
at the last event time. Use independent impulses for completed activities or
an explicitly hypothetical sequence.

For a daily linear Low-XSS ramp to an absolute TP target, use:

```bash
python3 -B plugins/xert/scripts/xert_cli.py load-model \
  --target-at 2027-01-01T09:00:00 \
  --target-tp 300 --distribution linear --frequency daily --summary
```

The default start dose is the daily Low XSS that maintains the current Low TL.
`--start-low-xss` can override it. The solver weights every daily impulse by
its remaining decay before the target and solves the final dose of the linear
ramp. This mode projects Low TL and marginal TP only; it does not yet project
the repeated ramp's RL or final freshness/status. Do not silently assume either
the ramp shape or its frequency.

## State and Interpretation Rules

- Begin every projection from a fresh live Xert snapshot.
- After Xert processes any completed activity, resync before projecting again.
- Completed XSS is already present in the new live TL/RL state. Never apply or
  subtract it a second time.
- `remainingXSS` is Xert's remaining recommendation. A later planned event is
  an additional modeled impulse and does not reduce `remainingXSS` merely by
  existing in Planner.
- On a breakthrough, adopt Xert's saved new signature and activity XSS. Do not
  score the proprietary breakthrough jump as marginal-model error.
- Exclude transitions into manual/locked signatures from prediction error.
- Exclude a `flag: true` signature transition and the following invalid anchor
  from signature error, while retaining Xert's own load history.
- Historical data verifies the recurrence; it must not be used to tune a model
  whose purpose is predicting new work with current parameters.

## Confidence Boundary

The TL/RL recurrence, RL cap, status boundaries, Planner impulse timing, and
current `k1*delta_TL` marginal response are empirically validated. The model
does not predict whether Xert will award a breakthrough or near-breakthrough,
nor reproduce Xert's private decay convergence adjustment. Call TP/HIE/PP
outputs marginal Training-Load-matched projections, not guaranteed future
Fitness Signatures.
