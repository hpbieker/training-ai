"""Time-scoped outdoor evidence, without physiological grades or inferred intent."""
from __future__ import annotations

from bisect import bisect_left
import math

from physiological_evidence import numeric, timeline, field_summary, quality

FIELDS = ('watts', 'cadence', 'heartrate', 'respiration', 'tidal_volume',
          'tidal_volume_min', 'smo2', 'core_temperature', 'temp')


def _summary(rows, fields):
    clock = timeline(rows)
    return {field: {'mean': round(s['avg'], 2) if s else None,
                    'coverage': round(1-q['missing_fraction'], 4),
                    'reasons': q['reasons']}
            for field in fields
            for q in [quality(rows, field, clock)]
            for s in [field_summary(rows, field, clock)]}


def _mechanics(rows):
    clock = timeline(rows)
    if clock is None:
        return None
    power = field_summary(rows, 'watts', clock)
    cadence = field_summary(rows, 'cadence', clock)
    speed = field_summary(rows, 'velocity_smooth', clock)
    if not power or not cadence or not speed or power['avg'] < 50 or cadence['avg'] < 30:
        return None
    pairs = [(numeric(r, 'watts'), w) for r, w in zip(rows, clock[1]) if numeric(r, 'watts') is not None]
    duration = sum(w for _, w in pairs)
    variance = sum(w*(v-power['avg'])**2 for v,w in pairs)/duration
    coast = sum(w for v,w in pairs if v < 20)/duration
    stopped = sum(w for r,w in zip(rows,clock[1]) if (numeric(r,'velocity_smooth') or 0) < .6)/sum(clock[1])
    if stopped > .02 or coast > .1:
        return None
    quartiles = []
    for fraction in (.25,.5,.75):
        cumulative = 0
        for v,w in sorted(pairs):
            cumulative += w
            if cumulative >= fraction*duration:
                quartiles.append(v)
                break
    return {'power_w': power['avg'], 'cadence_rpm': cadence['avg'],
            'power_cv': math.sqrt(variance)/power['avg'], 'coasting_fraction': coast,
            'power_quartiles_w': quartiles}


def outdoor_evidence(rows, *, fields=FIELDS, pauses=(), chunk_seconds=1800):
    """Describe clock interruptions, chronological work and mechanically matched variable windows.

    Matching uses mechanics only, never the direction of HR/respiration changes.
    Five-minute variable-work windows are descriptive comparisons, not steady
    states or validated durability tests. Exact tolerances are engineering policy.
    """
    clock = timeline(rows)
    if clock is None:
        return {'status': 'unavailable', 'reason': 'missing_or_nonmonotonic_time'}
    times, weights, duration = clock
    fields = [f for f in FIELDS if f in fields]
    interruptions = []
    breaks = {times[0], times[-1]+weights[-1]}
    for i in range(1,len(rows)):
        end_previous = times[i-1]+weights[i-1]
        if times[i]-end_previous >= 30:
            d0, d1 = numeric(rows[i-1],'distance'), numeric(rows[i],'distance')
            interruptions.append({'start_s': end_previous, 'end_s': times[i],
                'unrecorded_seconds': times[i]-end_previous,
                'distance_change_m': None if d0 is None or d1 is None else round(d1-d0,1),
                'kind': 'recording_gap',
                'interpretation': 'unobserved interval; unchanged distance supports a paused recording, not proof of sensor failure or the reason for stopping'})
            breaks.update((end_previous,times[i]))
    long_stops = [(p['start_s'],p['end_s']+1) for p in pauses if p.get('duration_s',0)>=120]
    for start,end in long_stops:
        breaks.update((start,end))
    # Work integrates only covered, valid source time. Unknown intervals contribute
    # neither invented zero watts nor interpolated work.
    work = [0.0]
    power_samples = [0]
    for r,w in zip(rows,weights):
        p = numeric(r,'watts') if 'watts' in fields else None
        work.append(work[-1] + (p*w/1000 if p is not None else 0))
        power_samples.append(power_samples[-1] + int(p is not None and w > 0))
    phases = []
    candidates = []
    ordered = sorted(breaks)
    for start,end in zip(ordered,ordered[1:]):
        if any(start>=a and end<=b for a,b in long_stops):
            continue
        left = start
        while left < end:
            right = min(end,left+chunk_seconds)
            i,j = bisect_left(times,left),bisect_left(times,right)
            if j-i >= 2:
                subset = rows[i:j]
                phases.append({'start_s': times[i], 'end_s_exclusive': times[j-1]+weights[j-1],
                    'recorded_seconds': round(sum(weights[i:j]),1),
                    'observed_work_before_kj': round(work[i],1) if power_samples[i] or (i == 0 and power_samples[-1]) else None,
                    'observed_work_kj': round(work[j]-work[i],1) if power_samples[j] > power_samples[i] else None,
                    'statistics_scope': 'chronological_segment_not_prescribed_interval',
                    'fields': _summary(subset, fields)})
            left = right
        # Exclude transition following the beginning of each run and each stop.
        left = start + 120
        while left+300 <= end:
            i,j = bisect_left(times,left),bisect_left(times,left+300)
            pi = bisect_left(times,left-60)
            subset = rows[i:j]
            c = timeline(subset)
            if 'watts' in fields and 'cadence' in fields and c and c[2]>=295:
                mech = _mechanics(subset)
                prior = field_summary(rows[pi:i], 'watts')
                if mech and prior and mech['power_cv']<=.5:
                    candidates.append({'start_s':left,'end_s_exclusive':left+300,
                        'position_in_elapsed_ride_pct':round((left-times[0])/duration*100,1),
                        'seconds_since_run_or_stop_boundary':left-start,
                        'observed_work_before_kj':round(work[i],1),
                        'mechanics':mech,'preceding_60s_power_w':prior['avg'],
                        'fields':_summary(subset,fields)})
            left += 300
    matches = []
    for aidx,a in enumerate(candidates):
        for b in candidates[aidx+1:]:
            if b['start_s']-a['start_s'] < 3600:
                continue
            x,y = a['mechanics'],b['mechanics']
            if abs(y['power_w']/x['power_w']-1)>.05 or abs(y['cadence_rpm']/x['cadence_rpm']-1)>.1:
                continue
            if abs(y['power_cv']-x['power_cv'])>.05 or abs(y['coasting_fraction']-x['coasting_fraction'])>.05:
                continue
            if any(abs(v-u)>max(10,abs(u)*.1) for u,v in zip(x['power_quartiles_w'],y['power_quartiles_w'])):
                continue
            if abs(b['preceding_60s_power_w']-a['preceding_60s_power_w'])>max(10,a['preceding_60s_power_w']*.1):
                continue
            matches.append((b['start_s']-a['start_s'],a,b))
    comparison = {'status':'unavailable', 'candidate_windows':len(candidates), 'eligible_pairs':len(matches),
        'policy':{'window_seconds':300,'minimum_separation_seconds':3600,'max_power_cv':.5,
                  'mean_power_tolerance':.05,'mean_cadence_tolerance':.1,'cv_absolute_tolerance':.05,
                  'coasting_fraction_tolerance':.05,'power_quartiles_tolerance':'.1 relative or 10 W',
                  'preceding_60s_power_tolerance':'.1 relative or 10 W'},
        'interpretation':'mechanically similar variable-work windows; not steady state, a causal test, or a durability score; preceding 60s does not match all prior workload',
        'limitations':['posture, wind, drafting, fueling and cooling unresolved',
                       'physiological device lag unverified',
                       'mechanical matching cannot establish equal metabolic demand']}
    if matches:
        _,a,b = max(matches,key=lambda x:x[0])
        changes = {f:round(b['fields'][f]['mean']-a['fields'][f]['mean'],2)
                   for f in fields if a['fields'][f]['mean'] is not None and b['fields'][f]['mean'] is not None}
        comparison.update(status='descriptive_match',selection='widest separation satisfying mechanical criteria',
                          early=a,late=b,late_minus_early=changes,
                          recording_gap_seconds_between_windows=sum(g['unrecorded_seconds'] for g in interruptions if g['start_s']>=a['end_s_exclusive'] and g['end_s']<=b['start_s']),
                          scope_note='Later selected window is not necessarily the end of the ride; retain its timestamps and prior work.')
    else:
        comparison['reason']='no_mechanically_comparable_variable_windows'
    return {'status':'available','recorded_seconds':round(sum(weights),1),
            'elapsed_seconds':duration,'observed_work_kj':round(work[-1],1) if power_samples[-1] else None,
            'work_is_partial': not quality(rows,'watts',clock)['usable'] if 'watts' in fields else True,
            'interruptions':interruptions,'segments':phases,'variable_work_comparison':comparison,
            'interpretation':'Segments describe chronology, not prescribed intervals. Compare phases cautiously; their averages do not establish drift. Recording gaps do not by themselves invalidate Garmin device models.'}
