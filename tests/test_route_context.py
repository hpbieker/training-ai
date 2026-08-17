import argparse
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from route_context import (
    parse_route_context_json,
    parse_route_context_payload,
)
from route_recommendations import parse_execution_options_json


class RouteContextTests(unittest.TestCase):
    def test_execution_options_are_structured(self):
        options = parse_execution_options_json(
            '{"junction_source":"osm","rebuild_analysis_cache":true}'
        )
        self.assertEqual(options["junction_source"], "osm")
        self.assertTrue(options["rebuild_analysis_cache"])

    def test_normalizes_shared_route_context(self):
        context = parse_route_context_json(
            json.dumps(
                {
                    "start_anchor": {
                        "display_name": "Dagaliveien 17B, Oslo",
                        "lat": 59.95581576954476,
                        "lng": 10.688188956334665,
                        "radius_km": 0.25,
                    },
                    "surface_preference": "road",
                    "target_distance_km": 80,
                }
            )
        )

        self.assertEqual(context["surface_preference"], "road")
        self.assertEqual(context["target_distance_km"], 80.0)
        self.assertEqual(context["start_anchor"]["radius_km"], 0.25)
        self.assertFalse(context["allow_away"])

    def test_empty_context_has_explicit_defaults(self):
        self.assertEqual(
            parse_route_context_payload({}, argument_name="route"),
            {
                "start_anchor": None,
                "surface_preference": "road",
                "target_distance_km": None,
                "allow_away": False,
            },
        )

    def test_allow_away_is_explicit_boolean(self):
        self.assertTrue(
            parse_route_context_json('{"allow_away":true}')["allow_away"]
        )
        with self.assertRaisesRegex(argparse.ArgumentTypeError, "must be boolean"):
            parse_route_context_json('{"allow_away":"yes"}')

    def test_rejects_unknown_fields_and_invalid_coordinates(self):
        with self.assertRaisesRegex(
            argparse.ArgumentTypeError,
            "unsupported .* field",
        ):
            parse_route_context_json('{"surface":"road"}')
        with self.assertRaisesRegex(
            argparse.ArgumentTypeError,
            "between -90 and 90",
        ):
            parse_route_context_json(
                '{"start_anchor":{"lat":100,"lng":10}}'
            )


if __name__ == "__main__":
    unittest.main()
