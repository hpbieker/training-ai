from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1] / "plugins/strava"
sys.path.insert(0, str(PLUGIN))
sys.path.insert(0, str(PLUGIN / "scripts"))
import strava_mcp as mcp_server
import strava_route_service as routes


def page(nodes, more=False, cursor=None):
    return json.dumps({"me": {"id": "12", "searchRoutes": {
        "nodes": nodes, "pageInfo": {"hasNextPage": more, "endCursor": cursor},
    }}}).encode(), 200, routes.ROUTES_API


def row(identifier="3517267791863546324", owner="12"):
    return {"id": identifier, "title": "Test route", "length": 12345.6,
            "elevationGain": 120.5, "routeType": "Ride", "athlete": {"id": owner},
            "isStarred": False, "isPrivate": True}


class StravaRoutesTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(routes, "StravaSession")
        self.session = patch.start().return_value.__enter__.return_value
        self.addCleanup(patch.stop)

    def responses(self, *pages):
        self.session.request.side_effect = [
            (b"<meta content='csrf&amp;value' name='csrf'>", 200, routes.ROUTES_PAGE),
            *pages,
        ]

    def test_get_route_preserves_native_metadata(self):
        source = {"id": "3517267791863546324", "title": "Lake & valley",
                  "routeDescription": None, "length": 123.456, "isPrivate": True,
                  "estimatedTime": {"expectedTime": 0}, "elements": [],
                  "polyline": [[37.1, -8.5]], "unknownFutureField": {"values": [1, None, False]}}
        payload = {"props": {"pageProps": {"route": source}, "sessionData": "must not return"}}
        html = '<script>{"ignore":true}</script><script type="application/json" id="__NEXT_DATA__">' + json.dumps(payload) + '</script>'
        self.session.request.return_value = (html.encode(), 200, "https://www.strava.com/routes/" + source["id"])
        result = mcp_server.StravaToolService().call_tool("get_route", {"route_id": source["id"]})
        self.assertEqual(result["route"], {k: v for k, v in source.items() if k not in {"elements", "polyline"}})
        self.assertEqual({x["path"] for x in result["omitted_arrays"]}, {"/elements", "/polyline"})
        self.session.request.assert_called_once_with("https://www.strava.com/routes/" + source["id"])

    def test_get_route_omits_fixed_arrays_regardless_of_size(self):
        for detail in ([], [1], list(range(2000))):
            source = {'id': '12', 'description': 'x' * 4000, 'isPrivate': True,
                      'unknown': list(range(2000)), 'nested': {'media': detail, 'null': None},
                      'routePolylineData': {'media': detail, 'other': None}}
            fields = {'elements', 'legs', 'segmentsOnRoute', 'segments',
                      'elevation', 'polyline', 'distanceStream'}
            source.update({key: detail for key in fields})
            with self.subTest(size=len(detail)), mock.patch.object(routes, '_get_route_full', return_value=source):
                result = mcp_server.StravaToolService().call_tool('get_route', {'route_id': '12'})
            self.assertEqual(result['route'], {
                'id': '12', 'description': 'x' * 4000, 'isPrivate': True,
                'unknown': list(range(2000)), 'nested': {'media': detail, 'null': None},
                'routePolylineData': {'other': None}})
            self.assertEqual({x['path'] for x in result['omitted_arrays']},
                             {'/' + key for key in fields} | {'/routePolylineData/media'})
            self.assertTrue(all(x['item_count'] == len(detail) for x in result['omitted_arrays']))
            self.assertEqual(source['legs'], detail)
            self.assertNotIn('full_route_file', result)

    def test_save_full_keeps_original_data_private_and_only_reads_once(self):
        import os
        source={'id':'12','legs':list(range(2000)),'nested':{'media':['x'*3000]}}
        with mock.patch.object(routes,'_get_route_full',return_value=source) as read:
            result=mcp_server.StravaToolService().call_tool('get_route',{'route_id':'12','save_full':True})
        file=Path(result['full_route_file']);self.addCleanup(file.unlink,missing_ok=True)
        self.assertEqual(json.loads(file.read_text()),{'route_id':'12','route':source})
        self.assertEqual(os.stat(file).st_mode & 0o777,0o600)
        self.assertEqual(result['full_route_byte_size'],file.stat().st_size)
        self.assertEqual(result['full_route_format'],'strava-route-v1')
        read.assert_called_once_with('12')
        self.assertNotIn('legs',result['route'])

    def test_save_full_rejects_non_boolean_before_network(self):
        for value in ('true',1,None):
            with self.subTest(value=value), self.assertRaises(mcp_server.ToolFailure):
                mcp_server.StravaToolService().call_tool('get_route',{'route_id':'12','save_full':value})
        self.session.request.assert_not_called()

    def test_save_full_failure_removes_partial_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            real=routes.tempfile.mkstemp
            def create(**kwargs):return real(dir=tmp,**kwargs)
            with mock.patch.object(routes,'_get_route_full',return_value={'id':'12'}), mock.patch.object(routes.tempfile,'mkstemp',side_effect=create), mock.patch.object(routes.json,'dump',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):routes.get_route('12',save_full=True)
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_get_route_rejects_missing_invalid_or_wrong_route(self):
        for data in ["not JSON private detail", "[]", '{}', '{"props":null}',
                     '{"props":{"pageProps":{"route":null}}}',
                     '{"props":{"pageProps":{"route":{"id":"99"}}}}']:
            with self.subTest(data=data):
                html = '<script id="__NEXT_DATA__">' + data + '</script>'
                self.session.request.return_value = (html.encode(), 200, "https://www.strava.com/routes/12")
                with self.assertRaises(routes.StravaError) as error:
                    routes.get_route("12")
                self.assertNotIn("private detail", str(error.exception))
        self.session.request.return_value = (b"<html></html>", 200, "https://www.strava.com/routes/12")
        with self.assertRaises(routes.StravaError):
            routes.get_route("12")

    def test_get_route_rejects_invalid_ids_before_network(self):
        for identifier in ["", "12/other", "https://example.com", 12, "١٢"]:
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                routes.get_route(identifier)
        self.session.request.assert_not_called()

    def test_pagination_deduplication_and_exact_ids(self):
        first = row()
        self.responses(page([first], True, "1"), page([first, row("987", "99")]))
        result = routes.list_routes()
        self.assertEqual([r["id"] for r in result["routes"]], [first["id"], "987"])
        self.assertEqual(result["pages_fetched"], 2)
        self.assertFalse(result["has_more"])
        self.assertIsNone(result["next_cursor"])
        route = result["routes"][0]
        self.assertEqual(route["distance_m"], 12345.6)
        self.assertEqual(route["elevation_gain_m"], 120.5)
        self.assertTrue(route["created_by_me"])
        self.assertFalse(result["routes"][1]["created_by_me"])
        self.assertIsNone(route["estimated_time_s"])
        calls = self.session.request.call_args_list
        self.assertEqual(json.loads(calls[2].kwargs["data"])["after"], "1")
        self.assertEqual(calls[1].kwargs["secret_headers"], ["X-CSRF-Token: csrf&value"])
        self.assertNotIn("csrf", json.dumps(result))

    def test_limit_cursor_and_source_filters(self):
        self.responses(page([row()], True, "8"))
        result = routes.list_routes(query="Lake", created_by="me", only_starred=True,
                                    route_types=["Ride"], max_pages=1, cursor="7")
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_cursor"], "8")
        body = json.loads(self.session.request.call_args.kwargs["data"])
        self.assertEqual(body["after"], "7")
        self.assertEqual(body["pageSize"], 16)
        self.assertEqual(body["searchArgs"]["createdBy"], "Athlete")
        self.assertEqual(body["searchArgs"]["query"], "Lake")
        self.assertEqual(body["searchArgs"]["routeTypes"], ["Ride"])
        self.assertTrue(body["searchArgs"]["onlyStarred"])

    def test_empty_collection_and_all_sports_default(self):
        self.responses(page([]))
        result = routes.list_routes()
        self.assertEqual(result["count"], 0)
        self.assertFalse(result["has_more"])
        body = json.loads(self.session.request.call_args.kwargs["data"])
        self.assertEqual(body["searchArgs"]["routeTypes"], routes.ROUTE_TYPES)

    def test_stalled_pagination_is_not_reported_as_complete(self):
        for nodes, cursor in [([row()], "0"), ([row()], None), ([], "1")]:
            with self.subTest(cursor=cursor, nodes=nodes):
                self.responses(page(nodes, True, cursor))
                with self.assertRaisesRegex(routes.StravaError, "did not advance"):
                    routes.list_routes()

    def test_invalid_response_is_not_an_empty_collection(self):
        for payload in [b"not JSON", b'{"errors":[{"message":"private detail"}]}',
                        b'{"me":null}', b'{"me":{"id":"12","searchRoutes":{"nodes":[]}}}']:
            with self.subTest(payload=payload):
                self.responses((payload, 200, routes.ROUTES_API))
                with self.assertRaises(routes.StravaError) as error:
                    routes.list_routes()
                self.assertNotIn("private detail", str(error.exception))

    def test_missing_csrf_stops_before_search(self):
        self.session.request.return_value = (b"<html></html>", 200, routes.ROUTES_PAGE)
        with self.assertRaisesRegex(routes.StravaError, "CSRF"):
            routes.list_routes()
        self.assertEqual(self.session.request.call_count, 1)

    def test_mcp_rejects_invalid_filters_before_network(self):
        service = mcp_server.StravaToolService()
        for args in [{"max_pages": 0}, {"page_size": 17}, {"cursor": ""},
                     {"created_by": "unknown"}, {"only_starred": "true"},
                     {"route_types": []}, {"route_types": ["invented"]},
                     {"cookie_file": "/tmp/secret"}]:
            with self.subTest(args=args), self.assertRaises(mcp_server.ToolFailure) as error:
                service.call_tool("list_routes", args)
            self.assertEqual(error.exception.code, "invalid_arguments")
        self.session.request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
