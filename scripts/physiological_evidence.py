"""Descriptive, time-aware evidence; quality thresholds are engineering policy.

No physiological cost, adaptation, or recovery scores are assigned here.
Source streams are assumed to share an elapsed-time clock. Unknown device lag
is not estimated or corrected from correlated signals.
"""
from __future__ import annotations

import math
from statistics import median
from collections import deque

# Data sufficiency rules, not athlete-specific physiological thresholds.
MAX_MISSING_FRACTION = 0.05
MAX_GAP_SECONDS = 30
MAX_SAMPLE_INTERVAL = 10


# Descriptive response-to-power ratios, never physiological cost estimates.
POWER_NORMALIZED_FIELDS = frozenset({'heartrate', 'respiration', 'tidal_volume_min'})
DELTA_UNITS = {
    'core_temperature': 'degC',
    'skin_temperature': 'degC',
    'temp': 'degC',
    'RuuviTemperature': 'degC',
    'dewpoint_c': 'degC',
    'smo2': 'percentage_points',
}


def numeric(row, field):
    try:
        result = float(row.get(field))
    except (ValueError, TypeError):
        return None
    if not math.isfinite(result):
        return None
    if field in {'watts', 'cadence', 'heartrate', 'respiration', 'tidal_volume', 'tidal_volume_min', 'thb'} and result < 0:
        return None
    if field in {'heartrate', 'respiration', 'tidal_volume', 'tidal_volume_min'} and result == 0:
        return None
    if field in {'smo2', 'Humidity', 'RuuviHumidity'} and not 0 <= result <= 100:
        return None
    return result


def timeline(rows):
    times = [numeric(row, 'time') for row in rows]
    if len(times) < 2 or any(t is None for t in times):
        return None
    steps = [b - a for a, b in zip(times, times[1:])]
    if any(step <= 0 for step in steps):
        return None
    nominal = min(median(steps), MAX_SAMPLE_INTERVAL)
    weights = [step if step <= max(3 * nominal, MAX_SAMPLE_INTERVAL) else nominal for step in steps] + [nominal]
    return times, weights, times[-1] - times[0] + nominal


def quality(rows, field, clock=None):
    clock = clock if clock is not None else timeline(rows)
    values = [numeric(row, field) for row in rows]
    present = sum(v is not None for v in values)
    invalid = sum(row.get(field) not in (None, '') and v is None for row, v in zip(rows, values))
    longest_samples = current = 0
    for v in values:
        current = current + 1 if v is None else 0
        longest_samples = max(longest_samples, current)
    result = dict(total=len(rows), present=present, missing=len(rows)-present,
                  invalid=invalid, has_values=present > 0, longest_gap=longest_samples,
                  usable=False, reasons=[])
    if clock is None:
        result.update(missing_fraction=1-present/len(rows) if rows else 1,
                      meaningful_gap=True, reasons=['missing_or_nonmonotonic_time'])
        return result
    times, weights, duration = clock
    valid_seconds = sum(w for w, v in zip(weights, values) if v is not None)
    covered_end = times[0]
    longest_gap = 0.0
    for t, w, v in zip(times, weights, values):
        if v is not None:
            longest_gap = max(longest_gap, t - covered_end)
            covered_end = t + w
    longest_gap = max(longest_gap, times[0] + duration - covered_end)
    missing = max(0, 1-valid_seconds/duration)
    reasons = []
    if not present:
        reasons.append('no_valid_values')
    if missing >= MAX_MISSING_FRACTION:
        reasons.append('insufficient_time_coverage')
    if longest_gap >= MAX_GAP_SECONDS:
        reasons.append('long_gap')
    if invalid:
        reasons.append('invalid_values')
    result.update(valid_seconds=valid_seconds, duration_seconds=duration,
                  missing_fraction=missing, longest_gap_seconds=longest_gap,
                  start_s=times[0], end_s=times[0]+duration,
                  usable=not reasons, meaningful_gap=bool(reasons), reasons=reasons)
    return result


def field_summary(rows, field, clock=None):
    clock = clock if clock is not None else timeline(rows)
    q = quality(rows, field, clock)
    if not q['usable']:
        return None
    pairs = [(numeric(row, field), w) for row, w in zip(rows, clock[1]) if numeric(row, field) is not None]
    total = sum(w for _, w in pairs)
    return dict(avg=sum(v*w for v, w in pairs)/total, min=min(v for v, _ in pairs),
                max=max(v for v, _ in pairs), start=pairs[0][0], end=pairs[-1][0], count=float(len(pairs)))


def matched_windows(rows, fields, *, transition_seconds=120, window_seconds=120,
                    power_tolerance=0.05, cadence_tolerance=0.10, window_context=None):
    """Find contiguous stable early/late windows; never stitch isolated samples.

    Windows use elapsed time, skip the initial transition and windows with
    substantial power variability. No universal physiological settling time is
    implied by the explicit transition exclusion.
    """
    fields = list(dict.fromkeys(fields))
    result = dict(status='unavailable', reasons=[], fields={},
                  policy=dict(transition_seconds=transition_seconds, window_seconds=window_seconds,
                              max_power_cv=0.10, power_tolerance=power_tolerance,
                              cadence_tolerance=cadence_tolerance),
                  alignment='source_elapsed_time; device lag unverified',
                  interpretation='descriptive matched-work change, not physiological cost')
    clock = timeline(rows)
    if clock is None:
        result['reasons'] = ['missing_or_nonmonotonic_time']
        return result
    times, _, duration = clock
    if window_context is None:
        window_context = prepare_windows(rows, transition_seconds=transition_seconds,
                                         window_seconds=window_seconds)
    if (window_context['transition_seconds'], window_context['window_seconds']) != (transition_seconds, window_seconds):
        raise ValueError('Window context and comparison policy must match')
    # Keep the activity-wide grid and work-run history. A block may only use
    # complete windows inside its own elapsed-time bounds.
    included_rows = {id(row) for row in rows}
    candidates = [(chunk, window) for chunk, window in window_context['candidates']
                  if window['start_s'] >= times[0]
                  and window['end_s'] <= times[0] + duration
                  and all(id(row) in included_rows for row in chunk)]
    result['candidate_windows'] = len(candidates)
    # Prefer the widest temporal separation that satisfies mechanical matching.
    pairs = []
    for i, (early, e) in enumerate(candidates):
        for late, l in candidates[i+1:]:
            if e['work_run_start_s'] != l['work_run_start_s'] and abs(e['elapsed_work_s']-l['elapsed_work_s']) > window_seconds / 2:
                continue
            if abs(l['power_avg']/e['power_avg']-1) > power_tolerance:
                continue
            if e['cadence_avg'] is not None and l['cadence_avg'] is not None:
                if e['cadence_avg'] <= 0 or abs(l['cadence_avg']/e['cadence_avg']-1) > cadence_tolerance:
                    continue
            pairs.append((l['start_s']-e['start_s'], early, e, late, l))
    if not pairs:
        result['reasons'] = ['no_comparable_stable_windows']
        return result
    _, early, e, late, l = max(pairs, key=lambda pair: pair[0])
    result.update(status='matched', early=e, late=l,
                  work_phase_comparison='same_continuous_work' if e['work_run_start_s'] == l['work_run_start_s'] else 'equivalent_elapsed_work',
                  cadence_comparison='matched' if e['cadence_avg'] is not None and l['cadence_avg'] is not None else 'unresolved',
                  prior_work_context='elapsed time differs; fueling, cooling and prior recovery require context')
    for field in fields:
        q1, q2 = quality(early, field), quality(late, field)
        a, b = field_summary(early, field), field_summary(late, field)
        item = dict(status='usable' if a and b else 'unavailable', early_quality=q1, late_quality=q2)
        if a and b:
            item.update(early_avg=a['avg'], late_avg=b['avg'], delta=b['avg']-a['avg'])
            if field in DELTA_UNITS:
                item['delta_unit'] = DELTA_UNITS[field]
            if a['avg'] and field in POWER_NORMALIZED_FIELDS:
                item['per_watt_change_pct'] = ((b['avg']/l['power_avg'])/(a['avg']/e['power_avg'])-1)*100
        result['fields'][field] = item
    return result


def prepare_windows(rows, *, transition_seconds=120, window_seconds=120):
    """Prepare stable windows once on the complete, unfiltered activity stream.

    Reuse this context for contiguous blocks from that same stream. It retains
    source rows and must be rebuilt if the source data or window policy changes.
    """
    return dict(transition_seconds=transition_seconds, window_seconds=window_seconds,
                candidates=_stable_windows(rows, transition_seconds, window_seconds))


def _stable_windows(rows, transition_seconds, window_seconds):
    clock = timeline(rows)
    if clock is None:
        return []
    times, _, duration = clock
    # Track sustained work runs so separate intervals can be compared at
    # equivalent elapsed work, rather than an onset against a late plateau.
    run_starts = []
    run_start = times[0]
    run_power = None
    recent = deque()
    for t, row in zip(times, rows):
        power = numeric(row, 'watts')
        recent.append((t, power))
        while recent and recent[0][0] < t - 30:
            recent.popleft()
        valid = [p for _, p in recent if p is not None]
        smoothed = median(valid) if valid else None
        # Brief fluctuations do not restart a whole work run. Sustained changes
        # in the preceding 30-second power median do; candidate windows still
        # have their own raw-power variability and data-quality checks.
        if smoothed is None or smoothed < 50:
            run_start, run_power = t, None
        elif run_power is None or abs(smoothed/run_power-1) > 0.10:
            run_start, run_power = t, smoothed
        run_starts.append(run_start)
    candidates = []
    start = times[0] + transition_seconds
    stop = times[0] + duration
    cursor = 0
    while start + window_seconds <= stop:
        while cursor < len(rows) and times[cursor] < start:
            cursor += 1
        end = cursor
        while end < len(rows) and times[end] < start + window_seconds:
            end += 1
        chunk = rows[cursor:end]
        c = timeline(chunk)
        power = field_summary(chunk, 'watts', c)
        if c and c[0][0] - start <= MAX_SAMPLE_INTERVAL and c[2] >= window_seconds - MAX_SAMPLE_INTERVAL and power and power['avg'] >= 50:
            variance = sum(w * (numeric(row, 'watts')-power['avg'])**2 for row, w in zip(chunk, c[1]) if numeric(row, 'watts') is not None) / sum(w for row, w in zip(chunk, c[1]) if numeric(row, 'watts') is not None)
            if math.sqrt(variance)/power['avg'] <= 0.10 and start-run_starts[cursor] >= transition_seconds and run_starts[end-1] == run_starts[cursor]:
                cadence = field_summary(chunk, 'cadence', c)
                candidates.append((chunk, dict(start_s=start, end_s=start+window_seconds,
                                               power_avg=power['avg'], cadence_avg=cadence['avg'] if cadence else None,
                                               work_run_start_s=run_starts[cursor], elapsed_work_s=start-run_starts[cursor])))
        start += window_seconds
    return candidates
