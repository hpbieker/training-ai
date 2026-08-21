"""Public facade for live Xert access helpers."""

from __future__ import annotations

from xert_activities import (
    fetch_activity_detail,
    fetch_activity_event_metadata_for_starts,
    fetch_flagged_activity_starts_with_login,
    list_activities,
    list_activity_details,
)
from xert_calendar import (
    create_calendar_event_with_opener,
    delete_calendar_event_with_opener,
    fetch_calendar_notes_with_opener,
    fetch_calendar_event_with_opener,
    fetch_calendar_events_with_opener,
    fetch_recommended_training_with_login,
    fetch_recommended_training_with_opener,
    fetch_training_forecast_with_login,
    fetch_training_forecast_with_opener,
    recommended_training_url,
    set_calendar_note,
    update_calendar_event_with_opener,
)
from xert_common import (
    LOCAL_TIMEZONE,
    XERT_API_BASE_URL,
    XERT_FORECAST_PATH,
    XertCredentials,
    _request_json,
    load_xert_credentials,
    request_xert_token,
    xert_web_login,
)
from xert_recovery import (
    calc_activity_max,
    calc_recovery_days_component,
    calculate_recovery_days,
    calculate_workout_capacity,
    fetch_ir_params,
    fetch_fitness_measures_with_login,
    fetch_my_fitness_model,
    fetch_recovery_model_with_login,
    infer_next_workout_days,
)
from xert_load_model import (
    calculate_load_projection,
    linear_daily_xss_distribution,
    recovery_demand_sensitivity,
    same_day_completed_and_planned_policy,
    simulate_calendar_sequence,
    summarize_signature_decay_analysis,
    validate_fitness_measures_history,
    validate_freshness_history,
    validate_signature_history,
)
from xert_workouts import (
    calculate_new_workout,
    create_workout,
    delete_workout,
    fetch_workout,
    fetch_workout_designer_rows,
    list_workouts,
    mutate_workout_row,
    parse_work_watts_from_name,
    replace_workout,
    summarize_workout_library,
    update_workout,
)
