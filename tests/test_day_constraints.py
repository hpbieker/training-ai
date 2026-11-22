"""Evidence, history and scope of dated workout constraints."""
from datetime import date
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from day_constraints import check_candidate, for_day, record, release


class DayConstraintsTests(unittest.TestCase):
    def test_verified_condition_releases_only_its_own_constraint(self):
        day = date(2026, 5, 3)
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "athlete.sqlite3"
            day_before = "2026-05-02T21:00:00+02:00"
            early = "2026-05-03T07:00:00+02:00"
            confirmed = "2026-05-03T08:00:00+02:00"
            args = (db, day, "No hard training unless the race is cancelled.", "chat#1",
                    day_before, ["quality"], "The organiser cancels the race.")
            key = record(*args)
            self.assertEqual(record(*args), key)
            record(db, day, "No sprints tomorrow.", "chat#2", day_before, ["sprint"])
            proof = (db, key, "condition", "Race cancelled", "organiser#notice", confirmed)
            release(*proof)
            release(*proof)
            entries = for_day(db, day, early)
            self.assertTrue(all(entry["active"] for entry in entries))
            with self.assertRaises(ValueError):
                check_candidate(entries, "vt1", planned_quality=True)
            entries = for_day(db, day, confirmed)
            check_candidate(entries, "vt2")
            with self.assertRaises(ValueError):
                check_candidate(entries, "sprint")
            self.assertEqual(entries[0]["release"]["evidence"], "Race cancelled")
            self.assertEqual(for_day(db, day, "2026-05-02T18:59:59Z"), [])
