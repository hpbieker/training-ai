import importlib.util
from pathlib import Path
import sys
import unittest


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "xert"
sys.path.insert(0, str(PLUGIN_ROOT))
spec = importlib.util.spec_from_file_location(
    "preview", PLUGIN_ROOT / "xert_beta_preview.py"
)
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


class BetaPreviewTests(unittest.TestCase):
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

    def test_only_expected_beta_origin(self):
        for url in ["https://example.com/a", "http://beta.xertonline.com/a", None]:
            with self.assertRaises(ValueError):
                P._beta_url(url)
        self.assertEqual(P._beta_url("https://beta.xertonline.com/a"), "https://beta.xertonline.com/a")
