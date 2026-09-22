import json
import sys
import unittest
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1] / "plugins/strava"
sys.path[:0] = [str(PLUGIN), str(PLUGIN / "scripts")]
import strava_activity_service as service


class KudosTests(unittest.TestCase):
    def fetch(self, body):
        with mock.patch.object(service, "StravaSession") as session:
            request = session.return_value.__enter__.return_value.request
            request.return_value = (body, 200, "")
            result = service.get_activity_kudos(activity_id="12")
            self.assertEqual(request.call_args.args[0], "https://www.strava.com/feed/activity/12/kudos")
            self.assertNotIn("method", request.call_args.kwargs)
            return result

    def test_nonempty_and_empty_kudos(self):
        for athletes in ([], [{"id": 123, "id_str": "123", "name": "Test Rider", "url": "/athletes/123"}]):
            with self.subTest(athletes=athletes):
                result = self.fetch(json.dumps({"athletes": athletes, "is_owner": True, "kudosable": False}).encode())
                self.assertEqual(result["count"], len(athletes))
                self.assertEqual(result["athletes"], athletes)
                self.assertTrue(result["is_owner"])
                self.assertFalse(result["kudosable"])

    def test_bad_response_is_not_zero_kudos(self):
        for body in (b'<html>login</html>', b'{}', b'[]', b'{"athletes":null}', b'{"athletes":[null]}', b'\xff'):
            with self.subTest(body=body), self.assertRaises(service.StravaError):
                self.fetch(body)

    def test_invalid_id_does_not_access_network(self):
        with mock.patch.object(service, "StravaSession") as session:
            with self.assertRaises(ValueError):
                service.get_activity_kudos(activity_id="12/other")
            session.assert_not_called()

    def test_auth_and_http_errors_are_preserved(self):
        for error in (service.StravaAuthRequired("expired"), service.StravaError("HTTP 404")):
            with mock.patch.object(service, "StravaSession") as session:
                session.return_value.__enter__.return_value.request.side_effect = error
                with self.assertRaises(type(error)):
                    service.get_activity_kudos(activity_id="12")


if __name__ == "__main__":
    unittest.main()
