"""Bind calculation evidence to the proposed workout and recovery horizon."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from xert_strain_model import calculate_workout, validate_signature


def finite_nonnegative(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{field} must be a finite nonnegative number")
    return float(value)


def canonical_structure(structure: dict) -> dict:
    signature = structure.get('signature')
    if not isinstance(signature, dict):
        raise ValueError('Calculation binding requires Fitness Signature')
    for field in ('tp', 'hie', 'pp'):
        finite_nonnegative(signature.get(field), f'signature {field}')
    tp, hie, pp = validate_signature(signature)
    raw = structure.get('segments')
    if not isinstance(raw, list) or not raw:
        raise ValueError('Calculation binding requires the complete ordered segments')
    segments = []
    for segment in raw:
        if not isinstance(segment, dict):
            raise ValueError('Calculation segment must be an object')
        seconds = finite_nonnegative(segment.get('duration_seconds'), 'segment duration')
        if seconds != int(seconds):
            raise ValueError('Calculation segment duration must be whole seconds')
        power = finite_nonnegative(segment.get('power', segment.get('start_power')), 'segment power')
        end = finite_nonnegative(segment.get('end_power', power), 'segment end power')
        segments.append({'duration_seconds':int(seconds), 'power':power, 'end_power':end})
    return {'signature':{'tp':tp, 'hie':hie, 'pp':pp}, 'segments':segments}


def bind_workout_calculation(calculation: dict, expected_structure: dict) -> dict:
    """Check native evidence against independent planned inputs and recalculate it.

    Only the selected adjustable duration may change in a solver result. Native
    strain results expose start_power rather than power in their segment summaries.
    """
    source = calculation.get('source')
    if source not in {'local_xert_strain_model', 'local_xert_segment_duration_solver'}:
        raise ValueError('Workout binding requires the complete native calculate_strain or solve_segment_duration result; summary-only Calculate results cannot establish the calculation inputs')
    if calculation.get('network_used') is not False:
        raise ValueError('Native workout evidence must identify its offline calculation')
    expected = canonical_structure(expected_structure)
    actual = canonical_structure(calculation)
    if actual['signature'] != expected['signature']:
        raise ValueError('Calculated Fitness Signature differs from the proposed workout')
    if len(actual['segments']) != len(expected['segments']):
        raise ValueError('Calculated segment count differs from the proposed workout')
    adjustable = None
    if source == 'local_xert_segment_duration_solver':
        adjustable = expected_structure.get('adjustable_segment_index')
        if isinstance(adjustable, bool) or not isinstance(adjustable, int) or not 0 <= adjustable < len(actual['segments']):
            raise ValueError('Proposed solver structure needs a valid adjustable segment index')
        if calculation.get('adjustable_segment_index') != adjustable:
            raise ValueError('Solver changed the adjustable segment index')
    for index, (planned, computed) in enumerate(zip(expected['segments'], actual['segments'])):
        for field in ('power', 'end_power', 'duration_seconds'):
            if field == 'duration_seconds' and index == adjustable:
                continue
            if not math.isclose(planned[field], computed[field], rel_tol=0, abs_tol=1e-8):
                raise ValueError(f'Calculated segment {index} {field} differs from the proposed workout')
    if adjustable is not None:
        seconds = actual['segments'][adjustable]['duration_seconds']
        if seconds != finite_nonnegative(calculation.get('adjustable_duration_seconds'), 'adjustable duration'):
            raise ValueError('Solver adjustable duration disagrees with its segments')
        minimum = finite_nonnegative(expected_structure.get('minimum_duration_seconds', 0), 'minimum duration')
        maximum = finite_nonnegative(expected_structure.get('maximum_duration_seconds', 28800), 'maximum duration')
        if not minimum <= seconds <= maximum:
            raise ValueError('Solver duration is outside the requested bounds')
    # Recalculate instead of trusting an input fingerprint attached after the fact.
    checked = calculate_workout(**actual, include_series=False)
    if not checked['feasibility']['valid']:
        raise ValueError('Proposed complete workout is not model-feasible')
    duration = finite_nonnegative(calculation.get('duration_seconds'), 'calculated duration')
    if duration != checked['duration_seconds']:
        raise ValueError('Calculated duration disagrees with its segments')
    reported = calculation.get('achieved_xss' if adjustable is not None else 'xss') or {}
    for system in ('low', 'high', 'peak', 'total'):
        value = finite_nonnegative(reported.get(system), f'calculated {system} XSS')
        if abs(value - checked['xss'][system]) > 0.05:
            raise ValueError(f'Calculated {system} XSS does not match the bound workout inputs; recalculate')
    fingerprint = hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    binding = {'status':'verified', 'input_sha256':fingerprint, 'method':'canonical_inputs_and_local_recalculation'}
    if adjustable is not None:
        return {**calculation, 'calculation_binding':binding}
    # Adapt the verified native result to the existing composition interface.
    return {'source':'xert_workout_calculate', 'duration_minutes':duration/60,
            'xss':reported['total'], 'low_xss':reported['low'], 'high_xss':reported['high'],
            'peak_xss':reported['peak'], 'canonical_structure':{**actual,
                'adjustable_segment_index':expected_structure.get('adjustable_segment_index')},
            'calculation_binding':binding}


def instant(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f'{field} requires an offset-aware timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'{field} requires an offset-aware timestamp') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f'{field} requires an offset-aware timestamp')
    return parsed.astimezone(timezone.utc)


def validate_capacity_values(capacity: dict) -> dict:
    systems = capacity.get('workout_capacity_xss')
    if not isinstance(systems, dict):
        raise ValueError('Capacity requires workout_capacity_xss')
    return {key:finite_nonnegative(systems.get(key), f'capacity {key}') for key in ('low','high','peak')}


def validate_capacity_horizon(capacity: dict, *, planned_at: str, next_workout_at: str,
                              approximation: dict | None = None) -> dict:
    validate_capacity_values(capacity)
    start = instant(planned_at, 'planned_at')
    end = instant(next_workout_at, 'next_workout_at')
    actual_start = instant(capacity.get('as_of'), 'capacity as_of')
    actual_end = instant(capacity.get('fresh_at'), 'capacity fresh_at')
    if end <= start or actual_end <= actual_start:
        raise ValueError('Capacity horizon must end after the workout start')
    exact = actual_start == start and actual_end == end
    if not exact:
        if not isinstance(approximation, dict) or not isinstance(approximation.get('reason'), str) or not approximation['reason'].strip():
            raise ValueError('Capacity timestamps differ from the planned workouts; recalculate or document an equivalent-horizon approximation')
        evidence = approximation.get('evidence')
        if not isinstance(evidence, list) or not evidence or any(not isinstance(v,str) or not v.strip() for v in evidence):
            raise ValueError('Capacity approximation requires evidence')
        if actual_end - actual_start != end - start:
            raise ValueError('Capacity approximation must preserve the exact recovery interval; recalculate')
    return {'status':'exact' if exact else 'equivalent_horizon_approximation',
            'planned_at':planned_at, 'next_workout_at':next_workout_at,
            'calculated_as_of':capacity['as_of'], 'calculated_fresh_at':capacity['fresh_at'],
            'approximation':approximation if not exact else None}
