import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "xert"
sys.path.insert(0, str(PLUGIN_ROOT))
spec = importlib.util.spec_from_file_location(
    "preview", PLUGIN_ROOT / "xert_beta_preview.py"
)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


class BetaPreviewTests(unittest.TestCase):
    def test_unsupported_wasm_factory_is_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "supported WASM factory interface"):
            P._run_wasm({}, "unreviewed", "https://beta.xertonline.com/js/svelte.js")

    @unittest.skipUnless(P.shutil.which("node"), "Node.js required")
    def test_runner_matches_reviewed_signature_rounding_clamps_and_option_defaults(self):
        bundle = '''Module = (() => {
          return async () => ({mpaChartData: (...args) => ({signature: {ltp: 234.5}, args})});
        })();
      xert_default = Module;'''
        props = {
            "signature": {"ftp": 300.16, "pp": 900.16, "atc": 15000.4, "m": 0,
                          "initial_gmg_balance": -5000, "mgc": 5000, "pcrc": 200,
                          "glut4r": 500, "gross_eff": .23456, "lt1_mmol": 5,
                          "smgf": .999, "l_bmr": 1200.4, "l_tau": 400.6,
                          "l_ptolr": 38.4, "l_mmol_factor": 480.6},
            "initialOptions": {"movingAverage": 5, "min_proximity": 0, "use_pcrc": False},
            "carb_bias": 1.5,
            "activity": {"recordsData": {k: [0, 1] for k in
                         ("time", "dist", "lat", "lng", "spd", "cad", "power")}},
        }
        out = P._run_wasm(props, bundle, "https://beta.xertonline.com/js/svelte.js")
        sig, options = out["signature_used"], out["options_used"]
        for key, value in {"ftp": 300.2, "atc": 15000, "pnr": 500, "hie": 15,
                           "mgc": 4000, "initial_gmg_balance": -4000, "pcrc": 1000,
                           "glut4r": 400, "gross_eff": .235, "lt1_mmol": 4,
                           "smgf": .95, "l_tau": 401, "l_mmol_factor": 481,
                           "ltp": 234.5}.items():
            self.assertEqual(sig[key], value, key)
        self.assertEqual(options["min_proximity"], 0)
        self.assertFalse(options["use_pcrc"])
        self.assertTrue(options["use_mg_replenishment"])
        self.assertFalse(options["do_extractSig"])
        self.assertEqual(options["a_tte"], 1200)
        self.assertEqual(out["computed"]["args"][8], 0)
        self.assertEqual(out["computed"]["args"][-2:], [True, False])

    def test_props_read_global_user_settings_without_retaining_user(self):
        html = '''userParams: {"carb_bias": 1.7, "username": "private"}
new sessions.ActivityDetails({props: {
activity: {"name":"Example","path":"abc"},
signature: {"ftp":300},
initialOptions: {"movingAverage":5}
}})'''
        props = P._props(html)
        self.assertEqual(props["carb_bias"], 1.7)
        self.assertNotIn("userParams", props)

    def test_extrema_timestamps(self):
        result = P._stats([4, 2, 7, 3], [0, 1, 2, 3])
        self.assertEqual(result, dict(start=4, minimum=2, minimum_at_s=1, maximum=7, maximum_at_s=2, end=3))
        with self.assertRaises(ValueError):
            P._stats([4], [])

    def test_lactate_threshold_duration_uses_timestamps(self):
        values = [1, 3, 5, 1]
        times = [0, 2, 5, 9]
        self.assertEqual(P._duration_at_or_above(values, times, 2), 7)
        self.assertEqual(P._duration_at_or_above(values, times, 4), 4)
        self.assertEqual(P._duration_at_or_above(values, times, 7), 0)

    def test_lactate_conversion_supports_current_and_legacy_beta_signatures(self):
        self.assertEqual(P._lactate_mmol_l([0, 5416.0], {"blood_lactate_j_per_mmol": 5416}), [1.0, 2.0])
        self.assertEqual(P._lactate_mmol_l([481.0], {"l_mmol_factor": 481}), [1.0])
        with self.assertRaisesRegex(ValueError, "valid lactate conversion"):
            P._lactate_mmol_l([100], {"blood_lactate_j_per_mmol": 0})

    def test_only_expected_beta_origin(self):
        for url in ["https://example.com/a", "http://beta.xertonline.com/a", None]:
            with self.assertRaises(ValueError):
                P._beta_url(url)
        self.assertEqual(P._beta_url("https://beta.xertonline.com/a"), "https://beta.xertonline.com/a")

    def test_workout_rows_expand_repeats_ramps_and_final_rib(self):
        power = P._expand_workout_rows([
            {"duration_seconds": 3, "power": 100, "power_type": "ramp_absolute",
             "power_second_value": 200, "interval_count": 2,
             "rib_duration_seconds": 2, "rib_power": 50},
            {"duration_seconds": 2, "power": 80, "power_type": "relative_ftp"},
        ], {"ftp": 300, "ltp": 270})
        self.assertEqual(power, [100, 150, 200, 50, 50, 100, 150, 200, 50, 50, 240, 240])

    def test_workout_rows_reject_invalid_or_empty_structure(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            P._expand_workout_rows([], {"ftp": 300})
        with self.assertRaisesRegex(ValueError, "positive integer"):
            P._expand_workout_rows([{"duration_seconds": 0, "power": 200}], {"ftp": 300})

    def test_interval_summaries_show_work_rise_and_recovery_fall(self):
        _, intervals = P._expand_workout([
            {"name": "VT2", "duration_seconds": 3, "power": 290, "interval_count": 2,
             "rib_duration_seconds": 2, "rib_power": 120},
        ], {"ftp": 300})
        series = {
            "elapsed_s": list(range(10)), "power_w": [290, 290, 290, 120, 120] * 2,
            "lactate_model_mmol_l": [2, 3, 4, 3, 2, 2.5, 3.5, 4.5, 3.5, 2.5],
            "muscle_glycogen_remaining_g": [100, 99, 98, 98.2, 98.4, 98.4, 97, 96, 96.2, 96.4],
            "muscle_glycogen_burned_g": [0, 1, 2, 2, 2, 2, 3.4, 4.8, 4.8, 4.8],
            "muscle_glycogen_replenished_g": [0, 0, 0, .2, .4, .4, .4, .4, .6, .8],
        }
        summaries = P._interval_summaries(series, intervals)
        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["lactate_model_mmol_l"]["delta"], 2)
        self.assertEqual(summaries[0]["recovery"]["lactate_model_mmol_l"]["delta"], -1)
        self.assertEqual(summaries[0]["muscle_glycogen"]["burned_g"], 2)
        self.assertAlmostEqual(summaries[0]["recovery"]["muscle_glycogen"]["replenished_g"], .2)
        self.assertEqual(summaries[1]["repetition"], 2)
