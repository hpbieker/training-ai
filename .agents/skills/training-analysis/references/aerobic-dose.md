# Choosing the aerobic dose

Before choosing minutes, compare recorded volume with the active plan's target
over its stated horizon. For a moving-time target, use completed moving time
in the same local-date windows. For the last N completed days, use the decision
date minus N through yesterday inclusive. Fetch the longest range once with
Intervals.icu `list_activities` and `includeFields: ["moving_time", "icu_ignore_time"]`,
without filters or a result limit. Supply the full response, including its query
bounds, as `sources.intervals_activity_volume` in the saved request. Report the
packet’s `training_history_context.completed_moving_time` for those dates.
If fetched coverage starts late, fetch the full range before quoting the mean.
The rolling window ending today is separate and is used for projections.
Check the dated activity list for coverage,
pagination and missing rides when local artifacts are the only basis for a
total. If coverage differs, use the more complete verified source for that
metric; name any remaining gap. Keep prior hours and the projected weekly
equivalent after today's full session distinct. When projecting a fixed-length
rolling window through today, drop the outgoing oldest date before adding
today's ride.

## Primary dose and optional aerobic extension

Prescribe a primary session that fulfills today's training purpose. Consider
whether riding longer would add useful aerobic work today. Weigh the extra
minutes against comparable rides, other opportunities for volume, intervening
training and recovery before the next priority session. Spare time or unused
XSS capacity alone is insufficient reason to extend.

Choose the size of an extension before checking the model ceiling. Compare
the primary finish with plausible shorter and longer additions at the same
watts. Use total steady minutes after the intervals and total ride minutes
for each, so a familiar duration or round increment does not silently become
the upper limit. Include a materially longer ride when history and calendar
make it credible. When revisiting an old offer, choose the range from the
evidence first, then compare with the saved minutes.

Size the optional finish for the *favorable late response* specified in its
cue. Uncertainty before the intervals may justify a conservative primary
ride. To limit the option on good legs, identify the cost that would still
matter at the checkpoint. Compare the *whole* longer candidate with a
successful historical dose: account for fewer or more hard minutes as well
as changed watts, the aerobic block and intervening days. If pace is novel
but hard time falls, check the complete dose before assuming it is heavier.
Use the time actually available on intervening days. When that time
changes the choice, add today's aerobic minutes to the intervening ride and
compare the combined exposure with a similar recorded sequence through the
next quality session. A shorter easy day both removes a volume opportunity
and reduces work before quality. Weigh those changes against the cost of
concentrating more work after intervals. Explain any residual reason to
hold back even when the historical sequence included more work between rides.
If both finishes fit, distinguish omitting the extra minutes from moving
them. For a move, compare equal work across both days: the longer finish
today with the usual intervening ride versus the shorter finish plus the
difference on the intervening ride. The latter puts that work closer to the
next priority session. What observed late fatigue, known session demands or
practical constraint favors it? If the intervening duration is unknown,
compare the marginal minutes without inventing a baseline. A model capacity
for tomorrow's start does not predict performance at the next quality ride.
An abbreviated historical quality set of unknown cause cannot by itself
justify moving work later. If the longer finish is useful on good legs and
the case for moving its last minutes is weak, offer it conditionally. When
the athlete stops for fatigue, leave those minutes unassigned. Use standard Xert strain for the leading candidates when comparison with
a recorded combined load helps resolve that trade-off; match model and units.
If the proposed finish falls between a short and a very long reference,
compare the nearest useful intermediate dose too, especially one that brings
the whole ride near a recent achieved load. Increasing beyond it calls for
an identifiable benefit in this week's schedule. Use known or explicitly
assumed recovery times. In the final answer give the athlete one upper option,
its nearest meaningful alternative and a cue to stop earlier if effort rises.

If the longer dose is the best choice at a normal response, prescribe it as
the primary session. If its value depends on how the ride unfolds, offer one
bounded extension the athlete can choose. Say when to decide, which response
to look for at familiar power, and when to finish with the primary dose. Use
observable cues such as breathing and perceived effort over the preceding
minutes at steady watts. Give the extra minutes, power and total ride time.
If the likely benefit is small or the next priority session needs the recovery,
recommend finishing at the primary duration. An open slot tomorrow shows
another opportunity. To use it as the deciding reason to stop today, identify
the planned work that would be displaced or the specific recovery cost that
would remain on a favorable late response. If a bounded extra dose serves
the volume goal, history supports it, and that conflict is absent, offer it.

## Endurance after intervals

First select the interval set. Then weigh finishing with cooldown against a
plausible period of steady riding at familiar aerobic power. Compare a shorter
addition with the usual full extension when they differ materially. Explain
the aerobic work gained, the opportunities for volume on adjacent days, and
what recovery the next priority session needs. If a recent combined session
preceded shortened quality, check the reviewed history for a comparable
successful sequence, including older sets with similar hard minutes. Compare
the interval set, extension, intervening rides and next achieved bouts before
attributing a later outcome to the extension. The quality-sequence helper
returns two recent attempts per role. For the range of achievable finishes,
read `long_finish_references[role]` alongside the recent sequences. It
selects an indoor ride by elapsed recovery intervals after the last work
bout; those minutes include cooldown. Use the review for actual steady minutes
and watts, then check the intervening rides and next quality outcome. Look
up other same-role reviews in `config/plan-state.json` when needed. Find the closest hard set with a longer recorded steady
block and read the subsequent entries through the next quality attempt. Check
dates against the decision time. Use the reviewed watts, minutes and actual
outcome. A successful sequence supports feasibility, and an abbreviated
subsequent set with an unknown cause leaves the recovery cost uncertain.

Keep the prescribed hard set as the priority. After its final repetition,
use the actual interval response to decide whether to begin the planned
aerobic work or go straight to cooldown. If a further extension is worthwhile,
place that decision near the end of the primary aerobic block. Keep the
extension at the stated aerobic power and include cooldown once in each total.

## Standalone aerobic rides

On a spacing day, compare the primary ride and a credible longer version
across the whole sequence: preceding quality dose, steady minutes at the
proposed watts, and recovery from each finish to the next priority start.
Use `measured_indoor_aerobic_references` with `quality_sequences` and
`long_finish_references` to distinguish total riding time from steady work.
Check which bouts the athlete actually completed next. If an abbreviated
quality ride weighs against extending, look for a comparable successful
sequence and weigh differences in prior work and recovery time. An unknown
stop reason or the extra mechanical work alone cannot establish a cutoff.
Use the recorded `finish_to_next_quality_minutes` for that comparison.
Distinguish it from time between the preceding hard ride and the spacing ride.

If declining a long extension, compare a useful intermediate dose at the
planned watts. Assess the primary plus that smaller addition against the
successful and abbreviated rides. When cutting both power and duration,
compare retaining one at its usual level first. Explain what favors the
chosen dose on normal legs and what still limits it on good legs.

Choose the primary dose for the day's purpose. If more volume serves the
plan, fits the schedule and is supported by the athlete's history, prescribe
one bounded option for good legs unless a specific cost still applies then.
When the next priority session moves later, start the good-legs comparison
at the familiar steady block, even if the primary ride is shorter. Look for
the nearest longer measured block at similar watts and compare their total
ride times with the same warm-up and cooldown. Two additions that both end
at or below the familiar block leave that question open. In the rider’s answer,
say what the last increment would buy if the intervening ride is short, what
would favor stopping at the familiar block, and where to decide while riding.
If a longer finish lacks support or cannot fit, give the specific reason.
Compare the upper options on the same favorable late response. Show how
many steady minutes each would produce, at what power, and the actual
difference in recovery before the next quality start. If the longer option
restores a familiar tolerated block, helps the volume goal and fits the
sequence, offer up to that total unless there is a specific reason to stop
earlier even then. Evidence for a cautious primary may apply to both options.
Distinguish a recent repeatable dose from an exceptional long ride. If both
options exceed the usual block, ask what the last increment buys over the
shorter *extended* ride specifically on this day. A weekly volume gap and
one successful long sequence establish a reason for some volume and the
possibility of more. To choose the exceptional dose, identify the extra
benefit in the actual schedule and weigh differences in the next quality
target. Without a distinct benefit, size the option around the repeatable
work and reassess at its end.
If retaining a shorter offer, give the athlete the deciding observation or
constraint in one sentence. Label a discretionary coaching judgment as such.
If recovery or a practical limit favors the primary even on good legs,
explain why.

Use an early fallback for unexpectedly heavy legs. Give an offered extension
its own decision point near the end of the primary steady work, before
cooldown. Start the extra minutes only after completing the full primary work
block. Use the packet’s `extension_start` when present. An earlier response
check may shorten the ride; if presenting it, separately state how much primary
work remains before the extension begins. Base the cue on the response at the same power and express it in ridden
minutes or completed work so a delayed start or pause preserves the cue.

Use dated athlete answers already available at the decision time. A later
clarification of why a bout ended takes precedence over an earlier unknown
reason. An answer about soreness today remains relevant when the numeric
wellness entry is missing. Ask again only if a different, unresolved fact
would change the prescription.

Compare elapsed recovery from the end of each ride to the next quality start
when both starts are known. Use the historical steady block and the proposed
work minutes and watts to explain the combined change in dose. Distinguish
measured work from prescribed work and a scheduled recovery window from an
observed response. A movable calendar event alone cannot cap the dose.

Choose the normal-response dose from the day's training purpose, comparable rides,
current response and available time before assessing a suggested workout. An
athlete's time limit or request is a constraint. A suggested duration, a solver
result or a capacity ceiling is not evidence of how much training is warranted.
If you adjust both watts and minutes, explain the combined change in work and
why changing one alone would be insufficient. Compare your choice with a
plausible shorter or longer alternative: what aerobic work would be gained
or lost, and what specific constraint or response matters today? Give the
primary duration, work minutes, watts and fallback. For an optional extension,
place the decision late enough to assess the response to the primary dose and
before cooldown or the last practical turnaround.
