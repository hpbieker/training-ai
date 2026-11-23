---
name: training-analysis
description: Use in the training-ai repo for workout analysis, activity comparison, readiness questions, daily training recommendations, outdoor route selection, weather-informed decisions, and composing normalized source data with repo helpers.
---

# Training Analysis

Use this skill for repo-level orchestration, local artifacts, cross-source
composition, and the final coaching answer. Source plugins own authentication,
live access, field semantics, and remote write safety.

## Context And Sources

- Apply `config/coaching-preferences.md`, `config/practical-context.md`, and
  other relevant LLM-readable context under `config/`.
- Resolve personal-context conflicts in this order: explicit current message,
  temporary rule, durable memory, stable practical context, generic fallback.
- Never make helper scripts parse personal profile or plan Markdown. Resolve the
  context as the agent and pass explicit CLI arguments or normalized JSON.
- Read the relevant plugin skill before using a source. Resolve its linked
  references relative to that skill's directory.
- Run the `scripts/` commands in this skill from the repository root.
- Prefer original-source values for source-specific semantics and use
  aggregation copies only when they are the best available input.
- Keep comparable timestamps in UTC internally and convert at local-calendar or
  user-display boundaries.

## Choose The Workflow

Choose the workflow that answers the user's request. Combine analysis and a
new training recommendation only when both are requested; a brief consequence
for subsequent training within an activity analysis does not require a complete
daily recommendation.

### Activity or workout analysis

Read [references/activity-analysis.md](references/activity-analysis.md) to
assess a completed session's execution, physiological response, and meaning.
Follow its [reference reading order](references/activity-analysis.md#reference-roles-and-reading-order):
this entrypoint selects the workflow, the activity reference directs the
analysis, specialist references qualify the measurements, and the synthesis
reference integrates the findings.

For late efforts on long rides, compare elapsed time, work already completed and
carbohydrate consumed before the effort when intake is known. Use the
[cycling physiology reference](references/cycling-endurance-physiology.md) when interpreting durability.

### Capture athlete feedback

If the athlete also rules out a workout on a future date, record that
[instruction for the workout date](references/daily-recommendations.md#dated-athlete-constraints).

At post-ride review, first read saved feedback, the activity analysis and
completed intervals. When the reason for a shortened set or omitted extension
could change a future dose, ask what made the athlete stop there. For a long
reference ride, ask about the late response at comparable power only if it is
missing and materially changes how the ride can be used. Capture actual intake
only when it could explain the response. Link the next quality result from the
activity history when it becomes available.

Save each relevant answer verbatim locally with
`python3 scripts/athlete_feedback.py --activity-id ID --observed-at DATE_OR_TIMESTAMP --reported-at ANSWER_TIMESTAMP --context SCOPE --question QUESTION --answer ANSWER`.
Use the real answer time with offset, the exact saved activity and the date of
the observation if its clock time is unknown. Split distinct observation times
(e.g. why yesterday's set ended and today's soreness). For pre-ride answers
about a previous ride, use that ride's ID and distinguish current status in
the observation context. For a standalone pre-ride answer when the upcoming ride has no activity ID,
use the latest completed activity as a history anchor and label the context
as pre-ride status for the decision date; it describes the upcoming session. Read back the saved record. Preserve earlier
answers when recording corrections.

### Activity comparison

Read [references/activity-analysis.md](references/activity-analysis.md) for
each selected activity. Establish which sessions or work blocks are comparable,
then assess the observed differences and their uncertainty. Use the same
reference reading order, selecting the specialist guidance relevant to the
measurements and session structures being compared.

### Training volume and load over a period

For a week or block comparison, report volume from recorded time. When
explaining a change in cumulative load across periods with different mixes of
endurance and quality work, compare standard XSS and Xert 2.0 XSS for the
matched rides. Follow the [period comparison guidance](references/activity-analysis.md#xert-20-beta-for-completed-rides-and-training-history)
for coverage, reuse and attribution. A time-only question needs only duration.

### Molecular stimulus analysis

When the user asks about a workout's cellular, biochemical, or molecular
stimuli, signalling pathways, or likely adaptations, first establish actual
execution and physiological response through the
[activity analysis workflow](references/activity-analysis.md). Reuse an existing
analysis when it covers the same session and relevant evidence.

Use that analysis and relevant research references to explain plausible links
between the actual intensity, duration, work-recovery structure, possible
signalling, and expected adaptations. Select mechanisms for their relevance to
the question rather than covering a fixed list of pathways or organ systems.

Keep general research findings, observed responses in this session, plausible
session-specific mechanisms, and demonstrated individual adaptation distinct.
Do not present signalling pathways as measured to be activated or rank their
individual activation strength without suitable measurement evidence. Ordinary
activity streams may support a stimulus interpretation without establishing the
molecular response or lasting adaptation.

Apply the shared
[competing-mechanism](references/physiological-response-synthesis.md#explain-competing-mechanisms)
and [adaptation](references/physiological-response-synthesis.md#compare-sessions-and-assess-adaptation)
rules. Explain the most relevant expected effects, the supporting session
features and research, and what remains uncertain for this athlete.

### Readiness or daily recommendation

- For a single measurement, use the source tool with the relevant fields.
- For a readiness assessment, follow the [focused readiness workflow](references/daily-recommendations.md#focused-readiness-questions)
  and run `readiness_snapshot.py --summary`.
- For a workout prescription, apply the [dated athlete constraints](references/daily-recommendations.md#dated-athlete-constraints)
  for the workout date. Follow the recommendation workflow below. The saved
  request runner builds the readiness snapshot as part of that workflow.

For a change to an existing recommendation, begin with
[updating the selected recommendation](references/daily-recommendations.md#update-an-existing-recommendation).
When availability disrupts the quality rhythm or the athlete asks about earlier
quality, locate the next realistic priority slot. Weigh moving quality earlier
and adding a single controlled effort while keeping the full session. Briefly
explain that effort’s value even if the athlete only reports the schedule
change. Include a later same-day start when recovery matters. For back-to-back
quality, include the decisive same-athlete outcomes and the choice before the
first ride in the rider's answer.
When the next priority session moves, including in the initial request, revisit
the preceding aerobic ride. On good legs compare the familiar steady block
with the next credible longer block in the athlete’s history. Give both total
ride times and what favors the last increment under the revised schedule.
For a new recommendation, read [references/daily-recommendations.md](references/daily-recommendations.md).
Use its [source collection guidance](references/daily-recommendations.md#collect-source-inputs)
to read the relevant sections, look up MCP schemas by exact tool name, and
collect independent inputs together. Include `xert_activity_loads` in the
initial source collection for a saved recommendation.
Also read
[references/cycling-endurance-physiology.md](references/cycling-endurance-physiology.md)
when prescribing a long ride, late-session intensity, severe intervals, heat
exposure, or deliberate low-carbohydrate availability.
Use the repo-local [training-plan skill](../training-plan/SKILL.md) to find active
plans under `config/plans/`, select the applicable plan, decide the current plan role, and
pass that role to the recommendation helper through an explicit
`intensity_goal` inside `--plan-selection-json`. Do not use a generic goal as a substitute for plan
selection, and do not make a helper parse an LLM-readable plan file.
Before choosing the session role and duration, read the preceding rides,
reviewed quality outcomes and available dated athlete reports. Use the
[focused history example](references/daily-recommendations.md#read-training-history)
to save the full `vt1_dose.py` result and display the rides and fields needed
for the decision.
If today's subjective response could change the session, check current chat
and dated reports first. In a live exchange, including a reply to an automated
recommendation, ask for a missing observation the athlete can already make
if it changes the choice. Place other checks where the uncertainty can be
resolved: during warm-up, after an effort, or late in steady work. For a
long aerobic ride with a justified extension, give the base dose and an upper
duration supported by the day's purpose and training history. Within that
range the rider can decide in stages. At each relevant checkpoint use the
recent response at the same power and the value of the next increment before
the next priority session to say whether to stop or how far to continue
before reassessing. Distinguish steady work from total ride time.
Use the [pre-session question guidance](references/daily-recommendations.md#pre-session-questions).
When quality is due, compare the achieved set with the next step in the
reviewed plan. Compare both as complete workouts, including work per effort,
total work minutes and recovery. If either can be done without an optional
extension, assess both on that basis. Use the following day and next quality
session to identify which difference the history actually informs.
When recommending another repeat, explain what remains to be established
after earlier completions and how repeating the set would clarify it. Keep the queued role as
the provisional goal when uncertainty can be resolved in the warm-up or set.
A change of goal before the helper runs needs a reason that still applies if
the athlete responds normally at the familiar workload.
The final recommendation packet also includes these observations under
`training_history_context.prior_quality_sequences`.

When a Garmin value influences intensity, dose or an on-bike check, compare it
briefly in the rider's answer with pre-ride values and actual outcomes from
comparable sessions by this athlete. Follow the [readiness comparison
guidance](references/daily-recommendations.md#comparing-readiness-before-quality-sessions).

Use [Choosing the aerobic dose](references/aerobic-dose.md) when choosing
endurance duration, including how far to ride after intervals. Ground the range
in comparable completed rides and explain the choice against a materially
different finish. Use the history packet's `long_finish_references` to check
the earlier combined ride and its follow-up before carrying forward a decision
to stop or cap a finish, including one from automation memory. If moving
minutes to a later ride, compare both placements through the next quality session. In a saved
daily request, keep the selected ride and the athlete's later choice separate:
resolve `training_target.aerobic_finish` and include the packet's finish
decision in the final prescription, including on reruns. When declining a longer
finish after intervals, check whether a shorter addition supported by comparable
rides still makes sense after a controlled set. If it does, include that option
in the selected recommendation before running the helper. For a
planned aerobic or recovery day, add `--aerobic-references` to the history
query for measured indoor blocks. On a spacing day, compare both the primary
and a longer ride through the next quality session, including a successful
sequence when one is available. Size the optional finish on good legs.
If choosing less than a familiar, useful longer dose, tell the rider what
favors the smaller addition at that checkpoint. The packet compares the two
totals and time to the next session under `aerobic_finish.spacing_comparison`.

[Save the candidate inputs](references/daily-recommendations.md#save-and-run-a-candidate)
and run `python3 -B scripts/run_training_request.py /absolute/path/to/request.json`.
Use its default compact output and read relevant fields from the saved packet
when more evidence is needed.

### Outdoor route recommendation

Read [references/outdoor-routes.md](references/outdoor-routes.md).

### Strava workout card

When the user asks to add a banner, card, or workout image to a completed
Strava activity, use `scripts/generate_strava_workout_card.py` by default.
After renaming in Intervals.icu, fetch and save fresh metadata for the same
activity ID before rendering. Call the generator with that activity
directory, `--xert-session` for the matching saved Xert session, and `--output`
for the PNG. Pass `--workout-role vo2max` or `--workout-role vt2` when the
completed role is confirmed. Pass `--inspection` with the same activity's
brief inspection JSON when it contains a measured `steady_vt1_segment`.
For VO₂max and VT2 cards, request the completed activity's model series with
Xert's `analyze_activity_xert_2(save_series=true)` and pass the saved file as
`--lactate-series` when available. The card shows the estimated maximum within
each work interval when the series covers every displayed interval.
Inspect the finished PNG against the recorded work before uploading. Check
the interval count, duration and power, and the duration and power of any
measured aerobic finish. Attach it through the
[Strava media workflow](../../../plugins/strava/skills/strava/references/write-safety.md#activity-media).

## Output

### Shared rules

- Answer in chat unless the user explicitly requests a report file.
- Label each training-load value with its source and metric; never treat values
  from different sources as interchangeable.
- State missing or stale inputs when they materially limit the conclusion.
- Use the output rules for the selected workflow below. Route recommendations,
  molecular explanations, and workout cards follow their own workflow above.

### Completed-activity analysis

Lead with a concise verdict on the actual session and whether it fulfilled its
purpose. Explain mechanical execution, integrated physiological response, and
what the findings mean for recovery and progression. Keep observed responses
separate from modeled stimulus and inferred adaptation. Use the detailed
[analysis reporting contract](references/physiological-response-synthesis.md#reporting-contract).

### Activity comparison

Lead with the main supported difference. Identify the compared sessions or work
blocks, explain their comparability and material confounders, and distinguish
execution differences from physiological response differences. State what the
comparison supports about development and what remains uncertain; a difference
between sessions does not by itself establish adaptation.

### Readiness question

Answer the specific readiness question using the relevant evidence and its
limitations. Use the readiness guidance in
[references/daily-recommendations.md](references/daily-recommendations.md).
Apply the full recommendation output contract when the user also requests a
concrete session decision.

### Training recommendation

For every interval ride, include the VT1 finish decision in the rider's
prescription, even when the primary workout contains no VT1. If offering extra
work, give its duration, power and the on-bike cue. If finishing after the
planned work, name the extra dose considered and why to skip it even on good
legs. A binding time or recovery constraint needs only a brief explanation.

For an interval set with uncertain repeatability, tell the rider where comparable attempts first diverged and what to do before starting the next effort. Use the response late in the preceding effort and during its recovery to explain when to continue, when to end the set, and what that means for an optional finish. Use the athlete’s reported reason when interpreting an omitted effort.

Follow the
[Final Answer Contract](references/daily-recommendations.md#final-answer-contract),
including the separate physiological scope, training need, final recommendation,
and capacity before the next workout. Recommendation-specific timing, dose,
fueling, alternatives, and artifact handling belong to that workflow.
