import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_strava_workout_card import load_lactate_maxima, load_steady_finish, workout_story


class StravaWorkoutCardTests(unittest.TestCase):
    def test_measured_interval_set_and_finish_survive_a_title_change(self):
        activity = {"interval_summary": ["1x 4m14s 242w", "6x 2m57s 354w"]}
        finish = {"duration_s": 4495, "watts_avg": 214}

        for name in ("Innendørssykling", "VO2Max 6x3 min + VT1 75 min"):
            with self.subTest(name=name):
                story = workout_story(
                    dict(activity, name=name), [], workout_role="vo2max", steady_finish=finish
                )
                self.assertEqual(story.headline, "VO₂MAX")
                self.assertEqual(story.subtitle, "6 × 2:57 at 354 W, followed by 75 min of VT1 at 214 W.")
                self.assertEqual(story.repetitions, 6)

        unknown_role = workout_story(dict(activity, name="Innendørssykling"), [], steady_finish=finish)
        self.assertEqual(unknown_role.headline, "INTERVALS")
        self.assertEqual(unknown_role.subtitle, story.subtitle)

    def test_cooldown_does_not_become_an_aerobic_finish(self):
        activity = {"name": "VO2Max 8x3 min", "interval_summary": ["8x 2m59s 349w"]}
        story = workout_story(activity, [], workout_role="vo2max")
        self.assertEqual(story.subtitle, "8 × 2:59 at 349 W.")

    def test_steady_ride_keeps_its_endurance_summary(self):
        rows = [{"time": second, "watts": 210} for second in range(3601)]
        story = workout_story({"interval_summary": ["1x 60m 210w"]}, rows)
        self.assertEqual(story.headline, "VT1")
        self.assertEqual(story.subtitle, "1 h 00 min of steady work at 210 W.")

    def test_inspection_must_belong_to_the_activity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inspection.json"
            path.write_text(json.dumps({"activity": {"id": "i123"}, "steady_vt1_segment": None}))
            self.assertIsNone(load_steady_finish(path, "i123"))
            with self.assertRaisesRegex(ValueError, "does not match"):
                load_steady_finish(path, "i456")

    def test_lactate_maxima_require_the_same_activity_and_every_work_interval(self):
        intervals = [{"start_time": 1, "end_time": 4}, {"start_time": 5, "end_time": 8}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "series.json"
            series = {
                "elapsed_s": list(range(9)),
                "lactate_model_mmol_l": [1, 2, 3, 4, 9, 4, 5, 6, 10],
            }
            payload = {"activity_path": "ride", "series": series}
            path.write_text(json.dumps(payload))
            self.assertEqual(load_lactate_maxima(path, "ride", intervals), [4, 6])
            with self.assertRaisesRegex(ValueError, "does not match"):
                load_lactate_maxima(path, "other-ride", intervals)

            for key in series:
                series[key].pop(6)
            path.write_text(json.dumps(payload))
            self.assertIsNone(load_lactate_maxima(path, "ride", intervals))
