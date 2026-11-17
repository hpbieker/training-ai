"""Evidence-based return workflow; elapsed calendar days never clear illness."""
import argparse
import json
import math
from datetime import date, datetime


def parse_illness_return_json(raw):
    try:
        value = json.loads(raw)
        validate_assessment(value)
        return value
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Illness assessment timestamps require UTC offsets')
    return result


def validate_assessment(value):
    if not isinstance(value, dict):
        raise ValueError('Illness return assessment must be an object')
    required = {'date', 'assessed_at', 'illness_started_on', 'last_sick_date', 'severity', 'symptoms',
                'red_flags', 'clinical_review', 'response', 'return_complete', 'reason', 'evidence'}
    optional = {'exercise_ended_at', 'dose_minutes', 'dose_xss'}
    if not required <= value.keys() or value.keys() - required - optional:
        raise ValueError('Illness assessment has missing or unsupported fields')
    date.fromisoformat(value['date'])
    date.fromisoformat(value['last_sick_date'])
    instant(value['assessed_at'])
    if not date.fromisoformat(value['illness_started_on']) <= date.fromisoformat(value['last_sick_date']) <= date.fromisoformat(value['date']):
        raise ValueError('Illness dates must be ordered and not in the future')
    if instant(value['assessed_at']).date().isoformat() != value['date']:
        raise ValueError('Assessment timestamp must be on its stated local date')
    if value['severity'] not in {'mild', 'moderate', 'severe', 'unknown'}:
        raise ValueError('Unsupported illness severity')
    if value['symptoms'] not in {'none', 'mild_local', 'systemic', 'unknown'}:
        raise ValueError('Unsupported current symptoms')
    if value['response'] not in {'not_started', 'pending', 'normal', 'abnormal'}:
        raise ValueError('Unsupported exercise response')
    for field in ('red_flags', 'clinical_review', 'return_complete'):
        if type(value[field]) is not bool:
            raise ValueError(f'{field} must be boolean')
    if not isinstance(value['reason'], str) or not value['reason'].strip():
        raise ValueError('Illness assessment requires a reason')
    if not isinstance(value['evidence'], list) or not value['evidence'] or any(
        not isinstance(item, str) or not item.strip() for item in value['evidence']
    ):
        raise ValueError('Illness assessment requires evidence references')
    if value['response'] in {'normal', 'pending'}:
        if 'exercise_ended_at' not in value:
            raise ValueError('Exercise response requires exercise_ended_at')
        if instant(value['exercise_ended_at']).date().isoformat() <= value['last_sick_date']:
            raise ValueError('Return exercise must be after the last sick day')
        if instant(value['exercise_ended_at']) > instant(value['assessed_at']):
            raise ValueError('Exercise response cannot precede the exercise')
    for field in ('dose_minutes', 'dose_xss'):
        if field in value and (type(value[field]) not in (int, float) or not math.isfinite(value[field]) or value[field] <= 0):
            raise ValueError(f'{field} must be positive and finite')


def assess_return(context, assessment, *, day, cutoff):
    """Update normalized context, preserving source illness and unknowns."""
    latest = context.get('latest_illness_event') or {}
    phase = 'awaiting_review' if latest else 'not_applicable'
    if assessment is not None:
        validate_assessment(assessment)
        if assessment['date'] != day or instant(assessment['assessed_at']) > cutoff:
            raise ValueError('Illness assessment must describe this day and be available at the data cutoff')
        if latest and assessment['last_sick_date'] < latest['date']:
            raise ValueError('Illness assessment predates the latest recorded illness episode')
        phase = 'awaiting_review'
        if assessment['red_flags'] or assessment['symptoms'] == 'systemic' or assessment['response'] == 'abnormal':
            phase = 'stop_and_review'
        elif assessment['severity'] in {'moderate', 'severe'} and not assessment['clinical_review']:
            phase = 'clinical_review_required'
        elif assessment['severity'] != 'unknown' and assessment['symptoms'] in {'none', 'mild_local'}:
            response = assessment['response']
            if response == 'not_started':
                phase = 'exercise_challenge'
            elif response == 'normal' and (instant(assessment['assessed_at']) - instant(assessment['exercise_ended_at'])).total_seconds() >= 86400:
                phase = 'complete' if assessment['return_complete'] and assessment['symptoms'] == 'none' else 'graded_return'
            else:
                phase = 'awaiting_24h_response'
        if assessment['last_sick_date'] >= day:
            phase = 'stop_and_review'
    if context.get('current_day_illness'):
        phase = 'stop_and_review'
    active = phase not in {'not_applicable', 'complete'}
    may_train = phase in {'exercise_challenge', 'graded_return'}
    context.update(
        illness_return_phase=phase,
        illness_return_assessment=assessment,
        illness_followup_needed=active and not may_train,
        illness_training_blocked=active and not may_train,
        return_to_training_active=active,
        return_to_training_guidance={
            'phase': phase,
            'duration_minutes': assessment.get('dose_minutes') if assessment and may_train else 0 if active else None,
            'intensity': 'very_easy_response_test' if phase == 'exercise_challenge' else 'easy_individualized_return' if may_train else 'rest_pending_review' if active else None,
            'max_minutes': assessment.get('dose_minutes') if assessment and may_train else 0 if active else None,
            'max_load': assessment.get('dose_xss') if assessment and may_train else 0 if active else None,
        } if active else None,
        followup_question='Avklar sykdomsforløp, aktuelle symptomer og respons under, etter og neste døgn etter siste lette økt.' if active and not may_train else None,
    )
    if may_train:
        if not all(key in assessment for key in ('dose_minutes', 'dose_xss')):
            raise ValueError('Active return requires an explicitly justified dose_minutes and calculated dose_xss')
        if phase == 'exercise_challenge' and assessment['dose_minutes'] > 20:
            raise ValueError('Initial exercise challenge must not exceed 20 minutes before reassessment')
    return context
