import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from jsonschema import Draft202012Validator

PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "yr"
sys.path.insert(0, str(PLUGIN_ROOT))
import yr_mcp as MCP
import yr_observations as OBS


def station(id, lon):
    return {"id": id, "name": id, "geometry": {"coordinates": [lon, 59.9]}, "masl": 90}


def sample(source, at, value, element="air_temperature", offset="PT0H"):
    return {"sourceId": source + ":0", "referenceTime": at,
            "observations": [{"elementId": element, "value": value, "unit": "degC",
                              "timeOffset": offset, "timeResolution": "PT1H",
                              "level": {"levelType": "height_above_ground", "value": 2, "unit": "m"},
                              "qualityCode": 2, "timeSeriesId": 0}]}


class FakeFrost:
    def __init__(self):
        self.calls = []
        # Deliberately unordered; near station has metadata but missing samples.
        self.stations = [station("SN2", 10.72), station("SN1", 10.7)]
        self.series = [{"sourceId": s["id"] + ":0", "elementId": "air_temperature",
                        "validFrom": "2000-01-01T00:00:00Z", "timeResolution": "PT1H"}
                       for s in self.stations]
        self.observations = [sample("SN2", "2026-10-18T08:00:00Z", 4.6),
                             sample("SN2", "2026-10-18T09:00:00Z", 5.3)]

    def get(self, endpoint, params):
        self.calls.append((endpoint, params))
        if endpoint == "sources":
            return {"data": self.stations}
        if endpoint == "observations/availableTimeSeries":
            return {"data": self.series}
        return {"data": [r for r in self.observations if r["sourceId"].split(":")[0] in params["sources"].split(",")]}


class ObservationToolsTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeFrost()
        self.tools = MCP.YrToolService(frost_factory=lambda: self.fake)
        self.window = {"timezone": "Europe/Oslo", "from_local": "2026-10-18T10:00:00",
                       "to_local": "2026-10-18T11:00:00", "elements": ["air_temperature"]}

    def call(self, name, a):
        result = self.tools.call_tool(name, a)
        Draft202012Validator(OBS.TOOL_DEFINITIONS[name]["outputSchema"]).validate(result)
        return result

    def test_find_ranks_and_filters_actual_series_coverage(self):
        a = {**self.window, "latitude": 59.9, "longitude": 10.7}
        r = self.call("find_observation_stations", a)
        self.assertEqual([s["station_id"] for s in r["stations"]], ["SN1", "SN2"])
        self.assertEqual(r["stations"][0]["distance_km"], 0)
        self.fake.series.pop()
        # A new service has no metadata snapshot from the preceding query.
        self.tools = MCP.YrToolService(frost_factory=lambda: self.fake)
        r = self.call("find_observation_stations", a)
        self.assertEqual([s["station_id"] for s in r["stations"]], ["SN2"])
        source_params = self.fake.calls[0][1]
        self.assertEqual(source_params["validtime"], "2026-10-18/2026-10-18")
        self.assertEqual(source_params["elements"], "air_temperature")

    def test_series_preserves_quality_level_and_inclusive_end(self):
        r = self.call("get_observation_series", {**self.window, "station_ids": ["SN2"]})
        self.assertEqual(r["count"], 2)
        self.assertEqual(r["observations"][0]["time_local"], "2026-10-18T10:00:00+02:00")
        self.assertEqual(r["observations"][0]["quality_code"], 2)
        self.assertEqual(r["observations"][0]["level"]["value"], 2)
        self.assertEqual(self.fake.calls[-1][1]["referencetime"],
                         "2026-10-18T08:00:00Z/2026-10-18T09:00:01Z")
        self.assertEqual(self.fake.calls[-1][1]["levels"], "default")

    def test_subdaily_offset_is_not_added_to_reference_time(self):
        self.fake.observations[0]["observations"][0]["timeOffset"] = "PT6H"
        r = self.call("get_observation_series", {**self.window, "station_ids": ["SN2"]})
        self.assertEqual(r["observations"][0]["time_utc"], "2026-10-18T08:00:00Z")
        self.assertEqual(r["observations"][0]["time_offset"], "PT6H")

    def test_missing_is_explicit_and_not_zero(self):
        r = self.call("get_observation_series", {**self.window, "station_ids": ["SN1"]})
        self.assertEqual(r["observations"], [])
        self.assertIn("No observations", r["warnings"][0])

    def point_args(self):
        return {"timezone": "Europe/Oslo", "elements": ["air_temperature"],
                "requests": [{"id": "p", "latitude": 59.9, "longitude": 10.7,
                              "at_local": "2026-10-18T10:30:00"}]}

    def test_batch_falls_back_to_station_with_samples_and_earlier_tie(self):
        r = self.call("get_observations", self.point_args())
        self.assertEqual(r["success_count"], 1)
        point = r["results"][0]
        self.assertEqual(point["station"]["station_id"], "SN2")
        self.assertEqual(point["observations"][0]["time_local"], "2026-10-18T10:00:00+02:00")
        self.assertEqual(point["requested_at_local"], "2026-10-18T10:30:00+02:00")
        self.assertEqual([endpoint for endpoint, _ in self.fake.calls], ["sources", "observations"])
        self.assertEqual(self.fake.calls[0][1]["nearestmaxcount"], 3)
        self.assertEqual(set(self.fake.calls[1][1]["sources"].split(",")), {"SN1", "SN2"})

    def test_reuses_metadata_but_reads_observations_fresh(self):
        self.call("get_observations", self.point_args())
        self.fake.observations[0]["observations"][0]["value"] = 8.8
        second = self.call("get_observations", self.point_args())
        self.assertEqual(second["results"][0]["observations"][0]["value"], 8.8)
        self.assertEqual([e for e, _ in self.fake.calls], ["sources", "observations", "observations"])
        # An explicit series call reuses station metadata found by the point search.
        self.call("get_observation_series", {**self.window, "station_ids": ["SN2"]})
        self.assertEqual([e for e, _ in self.fake.calls][-1], "observations")
        self.assertEqual(len(self.fake.calls), 4)

    def test_expands_only_for_missing_samples_and_fetches_only_new_stations(self):
        self.fake.stations = [station(f"SN{i}", 10.7+i/100) for i in range(1, 5)]
        self.fake.observations = [sample("SN4", "2026-10-18T08:00:00Z", 7)]
        original = self.fake.get
        def get(endpoint, params):
            result = original(endpoint, params)
            if endpoint == "sources" and "nearestmaxcount" in params:
                return {"data": result["data"][:params["nearestmaxcount"]]}
            return result
        self.fake.get = get
        result = self.call("get_observations", self.point_args())
        self.assertEqual(result["results"][0]["station"]["station_id"], "SN4")
        self.assertEqual([p["nearestmaxcount"] for e,p in self.fake.calls if e == "sources"], [3, 10])
        queries = [p["sources"] for e,p in self.fake.calls if e == "observations"]
        self.assertEqual(queries, ["SN1,SN2,SN3", "SN4"])

    def test_explicit_find_also_expands_only_for_missing_series(self):
        self.fake.stations = [station(f"SN{i}", 10.7+i/100) for i in range(1, 5)]
        self.fake.series = [{"sourceId": "SN4:0", "elementId": "air_temperature"}]
        original = self.fake.get
        def get(endpoint, params):
            result = original(endpoint, params)
            if endpoint == "sources":
                return {"data": result["data"][:params["nearestmaxcount"]]}
            return result
        self.fake.get = get
        result = self.call("find_observation_stations", {
            **self.window, "latitude": 59.9, "longitude": 10.7, "limit": 1})
        self.assertEqual(result["stations"][0]["station_id"], "SN4")
        self.assertEqual([p["nearestmaxcount"] for e,p in self.fake.calls if e == "sources"], [3, 10])

    def test_partial_elements_remain_at_one_station(self):
        self.fake.observations = [sample("SN1", "2026-10-18T08:00:00Z", 4),
                                  sample("SN2", "2026-10-18T08:00:00Z", 2, "wind_speed")]
        args = {**self.point_args(), "elements": ["air_temperature", "wind_speed"]}
        result = self.call("get_observations", args)["results"][0]
        self.assertEqual(result["station"]["station_id"], "SN1")
        self.assertEqual(result["missing_elements"], ["wind_speed"])
        self.assertIsNotNone(result["error"])

    def test_expansion_failure_preserves_partial_coverage(self):
        self.fake.stations = [station(f"SN{i}", 10.7+i/100) for i in range(1, 5)]
        self.fake.observations = [sample("SN1", "2026-10-18T08:00:00Z", 4)]
        original = self.fake.get
        def get(endpoint, params):
            if endpoint == "sources" and params.get("nearestmaxcount") == 10:
                raise OBS.ObservationFailure("source_error", "offline")
            result = original(endpoint, params)
            if endpoint == "sources":
                return {"data": result["data"][:params["nearestmaxcount"]]}
            return result
        self.fake.get = get
        result = self.call("get_observations", {
            **self.point_args(), "elements": ["air_temperature", "wind_speed"]})["results"][0]
        self.assertEqual(result["station"]["station_id"], "SN1")
        self.assertEqual(result["missing_elements"], ["wind_speed"])
        self.assertEqual(result["error"], "offline")

    def test_batch_tolerance_missing_data_and_point_failure(self):
        a = {**self.point_args(), "tolerance_minutes": 10}
        r = self.call("get_observations", a)
        self.assertEqual(r["error_count"], 1)
        self.assertEqual(r["results"][0]["missing_elements"], ["air_temperature"])
        self.assertIsNone(r["results"][0]["station"])

    def test_invalid_batch_validated_before_io(self):
        a = self.point_args()
        a["requests"].append(dict(a["requests"][0]))
        with self.assertRaisesRegex(MCP.ToolFailure, "Duplicate"):
            self.tools.call_tool("get_observations", a)
        self.assertEqual(self.fake.calls, [])

    def test_invalid_window_coordinates_ids_and_extra_arguments(self):
        base = {**self.window, "station_ids": ["SN2"]}
        for changes in [{"to_local": "2026-10-18T09:00:00"}, {"from_local": "2026-08-01T00:00:00"},
                        {"station_ids": ["SN2,*"]}, {"secret": "not allowed"},
                        {"elements": ["air_*"]}, {"timezone": "bad/zone"},
                        {"time_resolution": "P1D"}]:
            with self.subTest(changes=changes), self.assertRaises(MCP.ToolFailure):
                self.tools.call_tool("get_observation_series", {**base, **changes})
        self.assertEqual(self.fake.calls, [])

    def test_dst_ambiguity_requires_offset_and_converts_explicit_time(self):
        a = self.point_args()
        a["requests"][0]["at_local"] = "2026-10-25T02:30:00"
        with self.assertRaisesRegex(MCP.ToolFailure, "offset"):
            self.tools.call_tool("get_observations", a)
        a["requests"][0]["at_local"] = "2026-10-25T02:30:00+01:00"
        r = self.call("get_observations", a)
        self.assertEqual(r["results"][0]["requested_at_local"], "2026-10-25T02:30:00+01:00")

    def test_source_failure_stays_local_to_batch_member(self):
        original = self.fake.get
        def get(endpoint, params):
            if endpoint == "sources" and "POINT(0 " in params.get("geometry", ""):
                raise OBS.ObservationFailure("source_error", "Offline")
            return original(endpoint, params)
        self.fake.get = get
        a = self.point_args()
        a["requests"].append({**a["requests"][0], "id": "offline", "longitude": 0})
        r = self.call("get_observations", a)
        self.assertEqual((r["success_count"], r["error_count"]), (1, 1))
        self.assertEqual(r["results"][1]["error"], "Offline")

    def test_bounded_sample_count(self):
        with self.assertRaisesRegex(MCP.ToolFailure, "50000"):
            self.tools.call_tool("get_observation_series", {
                **self.window, "station_ids": [f"SN{i}" for i in range(10)],
                "elements": [f"element_{i}" for i in range(10)],
                "time_resolution": "PT10M", "to_local": "2026-11-17T10:00:00"})
        self.assertEqual(self.fake.calls, [])


class FrostTransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"
        self.path.write_text(json.dumps({"frost": {"client_id": "client-test", "client_secret": "never-send"}}))
        self.client = OBS.FrostClient(self.path)

    def test_only_client_id_sent_and_not_returned(self):
        with patch.object(OBS, "urlopen", return_value=io.BytesIO(b'{"data": []}')) as mocked:
            self.assertEqual(self.client.get("sources", {"ids": "SN1"}), {"data": []})
        request = mocked.call_args.args[0]
        auth = request.get_header("Authorization")
        self.assertEqual(base64.b64decode(auth.split()[1]).decode(), "client-test:")
        self.assertNotIn("never-send", request.full_url)

    def test_http_404_empty_but_auth_and_network_errors_are_not_empty(self):
        for code in [404, 401, 403, 500]:
            with patch.object(OBS, "urlopen", side_effect=HTTPError("url", code, "reason", {}, None)):
                if code == 404:
                    self.assertEqual(self.client.get("sources", {}), {"data": []})
                else:
                    with self.assertRaisesRegex(OBS.ObservationFailure, f"HTTP {code}"):
                        self.client.get("sources", {})
        with patch.object(OBS, "urlopen", side_effect=URLError("secret-detail")):
            with self.assertRaisesRegex(OBS.ObservationFailure, "connection failed") as raised:
                self.client.get("sources", {})
            self.assertNotIn("secret-detail", str(raised.exception))

    def test_missing_configuration_and_invalid_source_payload(self):
        self.path.unlink()
        with self.assertRaisesRegex(OBS.ObservationFailure, "frost.client_id"):
            self.client.get("sources", {})
        self.path.write_text('{"frost":{"client_id":"test"}}')
        for payload in [b'not-json', b'{"wrong": []}', b'{"data": [], "nextLink": "next"}']:
            with patch.object(OBS, "urlopen", return_value=io.BytesIO(payload)):
                with self.assertRaises(OBS.ObservationFailure):
                    self.client.get("sources", {})


class FrostMetadataCacheTests(unittest.TestCase):
    def test_expiry_date_scope_and_copy_isolation(self):
        fake = FakeFrost()
        now = [0]
        cached = OBS.CachedFrostClient(fake, ttl_seconds=10, clock=lambda: now[0])
        params = {"geometry": "nearest(POINT(10.7 59.9))", "validtime": "2026-10-18/2026-10-18"}
        first = cached.get("sources", params)
        first["data"][0]["name"] = "caller mutation"
        self.assertNotEqual(cached.get("sources", params)["data"][0]["name"], "caller mutation")
        self.assertEqual(len(fake.calls), 1)
        cached.get("sources", {"ids": "SN2", "validtime": params["validtime"]})
        self.assertEqual(len(fake.calls), 1)
        cached.get("sources", {"ids": "SN2", "validtime": "2026-10-19/2026-10-19"})
        self.assertEqual(len(fake.calls), 2)
        now[0] = 10
        cached.get("sources", params)
        self.assertEqual(len(fake.calls), 3)

    def test_cache_is_bounded_and_does_not_cache_failures(self):
        fake = FakeFrost()
        cached = OBS.CachedFrostClient(fake, max_entries=3)
        for i in range(5):
            cached.get("sources", {"query": i})
        self.assertLessEqual(len(cached._entries), 3)
        with patch.object(fake, "get", side_effect=OBS.ObservationFailure("source_error", "offline")):
            with self.assertRaises(OBS.ObservationFailure):
                cached.get("sources", {"query": "failed"})
        cached.get("sources", {"query": "failed"})


if __name__ == "__main__":
    unittest.main()
