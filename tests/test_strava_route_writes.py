from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1] / "plugins/strava"
sys.path.insert(0, str(PLUGIN))
sys.path.insert(0, str(PLUGIN / "scripts"))
import strava_mcp as mcp
import strava_route_service as routes


def editable():
    return {"id": "3517267791863546324", "title": "Original", "routeDescription": None,
            "isPrivate": False, "isStarred": True, "routeType": "Ride", "athlete": {"id": "12"},
            "routePrefs": {"surfaceType": "Paved", "elevation": 0, "popularity": 0.5, "straightLine": False},
            "elements": [{"elementType": "Waypoint", "waypoint": {"point": {"lat": 1, "lng": 2}, "metadata": None}},
                         {"elementType": "Waypoint", "waypoint": {"point": {"lat": 3, "lng": 4}, "metadata": None}}],
            "legs": [{"legType": "Search", "paths": [{"polyline": {"encoding": "Google", "data": "abcd"}, "length": 123.4}]}]}


class RouteWriteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patch = mock.patch.object(routes, "StravaSession")
        self.session = patch.start().return_value.__enter__.return_value
        self.addCleanup(patch.stop)
        self.session.tmp_dir = Path(self.temp.name)
        self.session.authenticate.return_value = {"athlete_id": 12}
        self.route = editable()
        self.props = routes._write_props(self.route)
        self.id = self.route["id"]

    def write(self, operation, args, before=None, after=None):
        after = after or self.route
        states = [before or self.route, after] if operation == "update_route" else [after]
        self.session.api.return_value = {"updateRoute": None} if operation == "update_route" else {"createRoute": self.id}
        with mock.patch.object(routes, "_editable_route", side_effect=states), mock.patch.object(routes, "get_route", return_value=after):
            return mcp.StravaToolService().call_tool(operation, args)

    def test_create_native_payload_and_default_private(self):
        props = copy.deepcopy(self.props)
        for field in ["visibility", "description", "starred"]:
            props.pop(field)
        saved = {**self.route, "isPrivate": True, "isStarred": False}
        result = self.write("create_route", {"props": props, "confirm": True}, after=saved)
        self.assertEqual(result, saved)
        sent = json.loads((self.session.tmp_dir / "route-write-request.json").read_text())["props"]
        self.assertEqual(sent["visibility"], "OnlyMe")
        self.assertEqual(sent["athleteId"], 12)
        self.assertEqual(sent["legs"], props["legs"])
        self.assertNotIn("athleteId", props)
        self.session.api.assert_called_once()

    def test_build_preserves_native_request_and_response_without_saving(self):
        requests = [{"elements": self.props["elements"], "routePrefs": self.props["routePrefs"]}]
        response = {"buildRoute": [{"legs": self.props["legs"], "futureField": None}], "extra": [1, False]}
        self.session.api.return_value = response
        result = mcp.StravaToolService().call_tool("build_route", {"requests": requests})
        self.assertIs(result, response)
        sent = json.loads((self.session.tmp_dir / "route-build-request.json").read_text())
        self.assertEqual(sent, {"requests": requests})
        self.session.api.assert_called_once()
        self.assertEqual(self.session.api.call_args.args[0], "build")

    def test_build_rejects_incomplete_source_response(self):
        requests = [{"elements": self.props["elements"], "routePrefs": self.props["routePrefs"]}]
        for response in [{}, {"buildRoute": []}, {"buildRoute": [None]},
                         {"buildRoute": [{"legs": []}]}, {"buildRoute": [{"legs": [{"paths": []}]}]},
                         {"errors": [{"message": "private"}], "buildRoute": [{"legs": self.props["legs"]}]}]:
            with self.subTest(response=response), self.assertRaises(mcp.ToolFailure) as error:
                self.session.api.return_value = response
                mcp.StravaToolService().call_tool("build_route", {"requests": requests})
            self.assertEqual(error.exception.code, "tool_error")
            self.assertNotIn("private", str(error.exception))

    def test_build_rejects_invalid_waypoint_requests_before_network(self):
        good = {"elements": self.props["elements"], "routePrefs": self.props["routePrefs"]}
        for args in [{"requests": []}, {"requests": [good], "target_km": 60},
                     {"requests": [{**good, "elements": good["elements"][:1]}]},
                     {"requests": [{**good, "elements": good["elements"] * 2}]},
                     {"requests": [{**good, "routePrefs": {"routeType": "Ride"}}]}]:
            with self.subTest(args=args), self.assertRaises(mcp.ToolFailure) as error:
                mcp.StravaToolService().call_tool("build_route", args)
            self.assertEqual(error.exception.code, "invalid_arguments")
        self.session.api.assert_not_called()

    def test_update_preserves_omitted_values_and_merges_preferences(self):
        saved = copy.deepcopy(self.route)
        saved["title"] = "New title"
        saved["routePrefs"]["popularity"] = 0
        self.write("update_route", {"route_id": self.id, "patch": {"name": "New title", "routePrefs": {"popularity": 0}}, "confirm": True}, after=saved)
        sent = json.loads((self.session.tmp_dir / "route-write-request.json").read_text())["props"]
        self.assertEqual(sent["routeId"], self.id)
        self.assertEqual(sent["visibility"], "Everyone")
        self.assertTrue(sent["starred"])
        self.assertEqual(sent["elements"], self.route["elements"])
        self.assertEqual(sent["routePrefs"], {**self.props["routePrefs"], "popularity": 0})
        self.assertEqual(self.route["title"], "Original")

    def test_clear_description_and_false_starred(self):
        saved = {**self.route, "isStarred": False}
        self.write("update_route", {"route_id": self.id, "patch": {"description": "", "starred": False}, "confirm": True}, after=saved)

    def test_geometry_replacement(self):
        saved = copy.deepcopy(self.route)
        saved["elements"][1]["waypoint"]["point"]["lng"] = 5
        saved["legs"][0]["paths"][0]["polyline"]["data"] = "efgh"
        new_props = routes._write_props(saved)
        self.write("update_route", {"route_id": self.id, "patch": {k: new_props[k] for k in ["elements", "legs"]}, "confirm": True}, after=saved)

    def test_rejects_not_owned_route_before_write(self):
        other = {**self.route, "athlete": {"id": "99"}}
        with mock.patch.object(routes, "_editable_route", return_value=other), self.assertRaises(mcp.ToolFailure) as error:
            mcp.StravaToolService().call_tool("update_route", {"route_id": self.id, "patch": {"name": "No"}, "confirm": True})
        self.assertEqual(error.exception.code, "invalid_arguments")
        self.session.api.assert_not_called()

    def test_schema_rejects_unsafe_or_incomplete_inputs(self):
        samples = [
            ("create_route", {"props": self.props, "confirm": False}),
            ("create_route", {"props": {**self.props, "athleteId": 99}, "confirm": True}),
            ("create_route", {"props": {"name": "No geometry"}, "confirm": True}),
            ("update_route", {"route_id": self.id, "patch": {}, "confirm": True}),
            ("update_route", {"route_id": self.id, "patch": {"elements": self.props["elements"]}, "confirm": True}),
            ("update_route", {"route_id": self.id, "patch": {"title": "Wrong field"}, "confirm": True}),
        ]
        for tool, args in samples:
            with self.subTest(tool=tool, args=args), self.assertRaises(mcp.ToolFailure) as error:
                mcp.StravaToolService().call_tool(tool, args)
            self.assertEqual(error.exception.code, "invalid_arguments")
        self.session.authenticate.assert_not_called()

    def test_rejects_inconsistent_geometry_before_create(self):
        props = copy.deepcopy(self.props)
        props["legs"][0]["startElement"] = 1
        with self.assertRaises(mcp.ToolFailure):
            mcp.StravaToolService().call_tool("create_route", {"props": props, "confirm": True})
        self.session.authenticate.assert_not_called()

    def test_readback_failure_retains_created_id_without_retry(self):
        self.session.api.return_value = {"createRoute": self.id}
        with mock.patch.object(routes, "_editable_route", side_effect=routes.StravaError("unavailable")), self.assertRaises(mcp.ToolFailure) as error:
            mcp.StravaToolService().call_tool("create_route", {"props": self.props, "confirm": True})
        self.assertEqual(error.exception.code, "write_unverified")
        self.assertEqual(error.exception.details["route_id"], self.id)
        self.assertEqual(error.exception.details["stage"], "readback")
        self.session.api.assert_called_once()

    def test_post_failure_is_uncertain_and_never_retried(self):
        self.session.api.side_effect = routes.StravaError("connection lost")
        with self.assertRaises(mcp.ToolFailure) as error:
            mcp.StravaToolService().call_tool("create_route", {"props": self.props, "confirm": True})
        self.assertTrue(error.exception.details["outcome_uncertain"])
        self.assertIsNone(error.exception.details["route_id"])
        self.session.api.assert_called_once()

    def test_mismatched_readback_cannot_report_success(self):
        for key in ["title", "isPrivate", "legs", "routePrefs"]:
            saved = copy.deepcopy(self.route)
            if key == "title": saved[key] = "Unexpected"
            elif key == "isPrivate": saved[key] = True
            elif key == "legs": saved[key][0]["paths"][0]["polyline"]["data"] = "different"
            else: saved[key]["popularity"] = 1
            with self.subTest(key=key), self.assertRaises(mcp.ToolFailure) as error:
                self.write("update_route", {"route_id": self.id, "patch": {"description": ""}, "confirm": True}, after=saved)
            self.assertEqual(error.exception.code, "write_unverified")

    def test_delete_requires_not_found_and_authenticated_readback(self):
        self.session.csrf = "test-token"
        for status in [404, 410]:
            with self.subTest(status=status):
                self.session.request.reset_mock()
                self.session.request.side_effect = [(b"", 204, "https://www.strava.com/routes/" + self.id), routes.StravaHttpError(status)]
                with mock.patch.object(routes, "_editable_route", return_value=self.route):
                    result = mcp.StravaToolService().call_tool("delete_route", {"route_id": self.id, "confirm": True})
                self.assertEqual(result, {"route_id": self.id, "deleted": True})
                calls = self.session.request.call_args_list
                self.assertEqual(calls[0].kwargs["method"], "DELETE")
                self.assertEqual(calls[0].kwargs["secret_headers"], ["X-CSRF-Token: test-token"])
                self.assertEqual(calls[1].args[0], "https://www.strava.com/routes/" + self.id)
                self.assertEqual(len(calls), 2)
        self.assertEqual(self.session.authenticate.call_count, 4)

    def test_delete_rejects_other_owner_and_missing_confirmation(self):
        other = {**self.route, "athlete": {"id": "99"}}
        with mock.patch.object(routes, "_editable_route", return_value=other), self.assertRaises(mcp.ToolFailure):
            mcp.StravaToolService().call_tool("delete_route", {"route_id": self.id, "confirm": True})
        for args in [{"route_id": self.id}, {"route_id": self.id, "confirm": False}, {"route_id": "../12", "confirm": True}]:
            with self.subTest(args=args), self.assertRaises(mcp.ToolFailure) as error:
                mcp.StravaToolService().call_tool("delete_route", args)
            self.assertEqual(error.exception.code, "invalid_arguments")
        self.session.request.assert_not_called()

    def test_delete_does_not_treat_server_error_or_existing_page_as_success(self):
        for readback in [(b"still here", 200, "https://www.strava.com/routes/" + self.id),
                         routes.StravaHttpError(403), routes.StravaHttpError(500)]:
            with self.subTest(readback=readback):
                self.session.request.reset_mock()
                self.session.request.side_effect = [(b"", 204, "https://www.strava.com/routes/" + self.id), readback]
                with mock.patch.object(routes, "_editable_route", return_value=self.route), self.assertRaises(mcp.ToolFailure) as error:
                    mcp.StravaToolService().call_tool("delete_route", {"route_id": self.id, "confirm": True})
                self.assertEqual(error.exception.code, "write_unverified")
                self.assertEqual(error.exception.details["route_id"], self.id)
                self.assertEqual(error.exception.details["stage"], "readback")
                self.assertEqual(self.session.request.call_count, 2)

    def test_delete_cannot_verify_after_authentication_is_lost(self):
        self.session.authenticate.side_effect = [{"athlete_id": 12}, routes.StravaError("Session lost")]
        self.session.request.side_effect = [(b"", 204, "https://www.strava.com/routes/" + self.id), routes.StravaHttpError(404)]
        with mock.patch.object(routes, "_editable_route", return_value=self.route), self.assertRaises(mcp.ToolFailure) as error:
            mcp.StravaToolService().call_tool("delete_route", {"route_id": self.id, "confirm": True})
        self.assertEqual(error.exception.code, "write_unverified")

    def test_delete_submit_failure_retains_id_and_does_not_retry(self):
        self.session.request.side_effect = routes.StravaError("Connection lost")
        with mock.patch.object(routes, "_editable_route", return_value=self.route), self.assertRaises(mcp.ToolFailure) as error:
            mcp.StravaToolService().call_tool("delete_route", {"route_id": self.id, "confirm": True})
        self.assertEqual(error.exception.details["operation"], "delete")
        self.assertEqual(error.exception.details["stage"], "submit")
        self.assertEqual(error.exception.details["route_id"], self.id)
        self.session.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
