import unittest

from scripts.readiness_snapshot import intervals_wellness_context


class IntervalsWellnessContextTests(unittest.TestCase):
    def test_preserves_supported_subjective_wellness_fields(self) -> None:
        result = intervals_wellness_context(
            "2026-07-22",
            [
                {
                    "id": "2026-07-22",
                    "injury": 1,
                    "fatigue": 2,
                    "soreness": 1,
                    "stress": 3,
                    "mood": 2,
                    "motivation": 2,
                    "hydration": 1,
                }
            ],
        )

        self.assertEqual(
            result["current_day"],
            {
                "date": "2026-07-22",
                "comments": None,
                "illness": False,
                "source": "wellness",
                "injury": 1,
                "fatigue": 2,
                "soreness": 1,
                "stress": 3,
                "mood": 2,
                "motivation": 2,
                "hydration": 1,
            },
        )

    def test_does_not_emit_empty_subjective_wellness_event(self) -> None:
        result = intervals_wellness_context(
            "2026-07-22",
            [{"id": "2026-07-22", "sleepQuality": 2, "sleepScore": 88}],
        )

        self.assertIsNone(result["current_day"])


if __name__ == "__main__":
    unittest.main()
