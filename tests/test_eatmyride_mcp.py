import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "eatmyride"
sys.path.insert(0, str(PLUGIN_ROOT))

import eatmyride_mcp as MCP  # noqa: E402
import eatmyride_api as API  # noqa: E402


class FakeEatMyRideService:
    def __init__(self) -> None:
        self.calls = []

    def list_activities(self, start_date, end_date):
        self.calls.append(("list_activities", start_date, end_date))
        return [{"id": "a1"}, {"id": "a2"}]

    def get_fueling(self, activity_id):
        self.calls.append(("get_fueling", activity_id))
        return {
            "activity": {"id": activity_id, "glycogen": {"min": 300, "end": 340}},
            "products": [{"label": "Drink", "occurrences": 1}],
            "summary": {"carbohydrates_grams": 60.0, "fluids_ml": 700.0},
            "intake_evidence": "recorded_food_plan_not_confirmed_consumption",
        }
    def get_foodplan(self, activity_id):
        self.calls.append(("get_foodplan", activity_id))
        return {"activity_id": activity_id, "event_count": 1, "events": [{"label": "Drink"}]}
    def search_products(self, query, *, product_filter=None):
        self.calls.append(("search_products", query, product_filter))
        return [{"id": 1, "label": "One"}, {"id": 2, "label": "Two"}]

    def list_products(self, source, *, activity_id=None, kind=None):
        self.calls.append(("list_products", source, activity_id, kind))
        return [
            {"id": 1, "label": "SiS Orange", "description": "Drink"},
            {"id": 2, "label": "Banana", "description": "Food"},
        ]

    def get_product(self, product_id):
        self.calls.append(("get_product", product_id))
        return {"id": product_id, "label": "Custom"}

    def create_product(self, values, *, confirm):
        self.calls.append(("create_product", values, confirm))
        return {"confirmed": confirm, "verified": confirm, "product": values}

    def update_product(self, product_id, values, *, confirm):
        self.calls.append(("update_product", product_id, values, confirm))
        return {
            "product_id": product_id,
            "confirmed": confirm,
            "verified": confirm,
            "before": {"id": product_id, "label": "Old"},
            "product": {"id": product_id, **values},
        }

    def delete_product(self, product_id, *, confirm):
        self.calls.append(("delete_product", product_id, confirm))
        return {"product_id": product_id, "confirmed": confirm, "verified_absent": confirm, "product": {"id": product_id}}

    def set_foodplan_products(self, activity_id, items, *, confirm):
        self.calls.append(("set_foodplan_products", activity_id, items, confirm))
        return {
            "activity_id": activity_id,
            "confirmed": confirm,
            "verified": confirm,
            "change": {"product_ids": [item["product_id"] for item in items]},
        }


class FakeCredentials:
    def login(self):
        return "token"


class CountingCredentials:
    def __init__(self) -> None:
        self.login_calls = 0

    def login(self):
        self.login_calls += 1
        return f"token-{self.login_calls}"


class EatMyRideMcpSchemaTests(unittest.TestCase):
    def test_exposes_selected_activity_fueling_and_product_tools(self) -> None:
        self.assertEqual(
            MCP.ALL_TOOL_NAMES,
            (
                "list_activities",
                "get_fueling",
                "get_foodplan",
                "search_products",
                "list_products",
                "get_product",
                "create_product",
                "update_product",
                "delete_product",
                "set_foodplan_products",
            ),
        )
        self.assertEqual(set(MCP.TOOL_SPECS), set(MCP.ALL_TOOL_NAMES))

    def test_every_tool_has_closed_inputs_outputs_and_read_annotations(self) -> None:
        for name in MCP.ALL_TOOL_NAMES:
            definition = MCP.TOOL_DEFINITIONS[name]
            self.assertFalse(definition["inputSchema"]["additionalProperties"], name)
            self.assertFalse(definition["outputSchema"]["additionalProperties"], name)
            for field, schema in definition["inputSchema"]["properties"].items():
                self.assertTrue(schema.get("description"), f"{name}.{field}")
            is_write = name in {
                "create_product", "update_product", "delete_product", "set_foodplan_products"
            }
            self.assertEqual(
                definition["annotations"],
                {
                    "title": MCP.TOOL_ANNOTATIONS[name]["title"],
                    "readOnlyHint": not is_write,
                    "destructiveHint": name in {
                        "update_product", "delete_product", "set_foodplan_products"
                    },
                    "idempotentHint": name not in {"create_product", "delete_product"},
                    "openWorldHint": True,
                },
            )

    def test_limited_lists_report_count_and_total_count(self) -> None:
        for name in ("list_activities", "search_products", "list_products"):
            properties = MCP.TOOL_DEFINITIONS[name]["outputSchema"]["properties"]
            self.assertIn("count", properties)
            self.assertIn("total_count", properties)
            self.assertNotIn("matched_count", properties)

    def test_sdk_accepts_every_tool_definition(self) -> None:
        server = MCP.create_sdk_server(MCP.EatMyRideToolService(FakeEatMyRideService))
        self.assertIsNotNone(server)


class EatMyRideMcpHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_initialize_and_list_tools(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-B", "./eatmyride_mcp.py"],
            cwd=str(PLUGIN_ROOT),
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()

        self.assertEqual([tool.name for tool in result.tools], list(MCP.ALL_TOOL_NAMES))


class EatMyRideMcpDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeEatMyRideService()
        self.tools = MCP.EatMyRideToolService(lambda: self.fake)

    def test_list_activities_is_bounded_and_reports_total(self) -> None:
        result = self.tools.call_tool(
            "list_activities",
            {"start_date": "2026-08-01", "end_date": "2026-08-02", "limit": 1},
        )
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["activities"][0]["id"], "a1")
        self.assertEqual(result["includeFields"], [])

    def test_lists_add_only_requested_activity_and_product_fields(self) -> None:
        self.fake.list_activities = lambda start, end: [
            {"id": "a1", "label": "Ride", "normalizedPower": 245, "warning": "raw"}
        ]
        activity = self.tools.call_tool(
            "list_activities",
            {"start_date": "2026-08-01", "end_date": "2026-08-01", "includeFields": ["normalizedPower"]},
        )["activities"][0]
        product = self.tools.call_tool(
            "search_products", {"query": "sis", "includeFields": ["carbohydrates"]}
        )["products"][0]
        self.assertEqual(activity["normalizedPower"], 245)
        self.assertNotIn("warning", activity)
        self.assertIn("carbohydrates", product)

    def test_get_fueling_combines_compact_state(self) -> None:
        result = self.tools.call_tool("get_fueling", {"activity_id": "a1"})
        self.assertEqual(result["activity"]["glycogen"]["min"], 300)
        self.assertEqual(result["activity"]["glycogen"]["end"], 340)
        self.assertEqual(result["summary"]["carbohydrates_grams"], 60.0)
        self.assertNotIn("events", result)

    def test_get_foodplan_returns_exact_events_separately(self) -> None:
        result = self.tools.call_tool("get_foodplan", {"activity_id": "a1"})
        self.assertEqual(result["event_count"], 1)
        self.assertEqual(result["events"][0]["label"], "Drink")

    def test_product_tools_filter_and_limit(self) -> None:
        searched = self.tools.call_tool(
            "search_products", {"query": "sis", "product_filter": "drinks", "limit": 1}
        )
        suggested = self.tools.call_tool(
            "list_products",
            {"source": "suggested", "activity_id": "a1", "kind": "drinks", "contains": "orange"},
        )
        self.assertEqual(searched["total_count"], 2)
        self.assertEqual(searched["count"], 1)
        self.assertEqual(suggested["total_count"], 1)
        self.assertEqual(suggested["products"][0]["id"], 1)

    def test_rejects_unknown_missing_and_invalid_arguments(self) -> None:
        with self.assertRaisesRegex(MCP.ToolFailure, "unknown argument"):
            self.tools.call_tool("search_products", {"query": "sis", "surprise": True})
        with self.assertRaisesRegex(MCP.ToolFailure, "missing required"):
            self.tools.call_tool("get_fueling", {})
        with self.assertRaisesRegex(MCP.ToolFailure, "limit must"):
            self.tools.call_tool("search_products", {"query": "sis", "limit": 0})
        with self.assertRaisesRegex(MCP.ToolFailure, "kind must"):
            self.tools.call_tool(
                "list_products", {"source": "suggested", "activity_id": "a1", "kind": "water"}
            )

    def test_custom_product_list_and_get_dispatch(self) -> None:
        listed = self.tools.call_tool("list_products", {"source": "custom", "limit": 1})
        product = self.tools.call_tool("get_product", {"product_id": 42})
        self.assertEqual(listed["source"], "custom")
        self.assertEqual(listed["count"], 1)
        self.assertEqual(product["product"]["id"], 42)

    def test_product_writes_preview_by_default_and_confirm_explicitly(self) -> None:
        created = self.tools.call_tool("create_product", {"label": "Gel"})
        updated = self.tools.call_tool(
            "update_product",
            {"product_id": 42, "label": "Gel 2", "carbohydrates_grams": 25, "confirm": True},
        )
        deleted = self.tools.call_tool(
            "delete_product", {"product_id": 42, "confirm": True}
        )
        self.assertFalse(created["confirmed"])
        self.assertTrue(updated["verified"])
        self.assertEqual(updated["product"]["carbohydrates_grams"], 25)
        self.assertTrue(deleted["verified_absent"])

    def test_foodplan_product_update_previews_by_default_and_confirms_explicitly(self) -> None:
        items = [{"product_id": 3111, "gram": 47, "ml": 700, "time_s": 1800}]
        preview = self.tools.call_tool(
            "set_foodplan_products", {"activity_id": "a1", "items": items}
        )
        applied = self.tools.call_tool(
            "set_foodplan_products",
            {"activity_id": "a1", "items": items, "confirm": True},
        )
        self.assertFalse(preview["confirmed"])
        self.assertTrue(applied["verified"])
        self.assertEqual(
            self.fake.calls[-1],
            ("set_foodplan_products", "a1", items, True),
        )

    def test_foodplan_product_update_validates_quantity_and_time_shape(self) -> None:
        with self.assertRaisesRegex(MCP.ToolFailure, "exactly one"):
            self.tools.call_tool(
                "set_foodplan_products",
                {"activity_id": "a1", "items": [{"product_id": 1}]},
            )
        with self.assertRaisesRegex(MCP.ToolFailure, "provided together"):
            self.tools.call_tool(
                "set_foodplan_products",
                {
                    "activity_id": "a1",
                    "items": [{"product_id": 1, "pieces": 2, "start_s": 10}],
                },
            )


class EatMyRideCredentialTests(unittest.TestCase):
    def test_fixed_user_config_is_shared_by_cli_and_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "eatmyride.json"
            config_file.write_text(
                '{"username":"file@example.com","password":"file-secret"}',
                encoding="utf-8",
            )
            with patch.object(API, "DEFAULT_CONFIG_PATH", config_file):
                credentials = MCP.discover_eatmyride_credentials()
        self.assertEqual(credentials.username, "file@example.com")
        self.assertEqual(credentials.password, "file-secret")


class EatMyRideLiveProductServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MCP.EatMyRideLiveService(lambda: FakeCredentials())

    def test_confirmed_create_and_update_read_back_exact_product(self) -> None:
        with (
            patch.object(MCP, "api_create_product", return_value={"id": 42}),
            patch.object(MCP, "api_update_product", return_value={"id": 42}),
            patch.object(MCP, "get_product", return_value={"id": 42, "label": "Verified"}) as read,
        ):
            created = self.service.create_product({"label": "Gel"}, confirm=True)
            updated = self.service.update_product(
                42, {"label": "Changed", "carbohydrates_grams": 25}, confirm=True
            )
        self.assertTrue(created["verified"])
        self.assertTrue(updated["verified"])
        self.assertEqual(read.call_count, 3)

    def test_update_preview_converts_only_explicit_user_facing_fields(self) -> None:
        current = {
            "id": 42,
            "label": "Old",
            "carbohydrates": 10000,
            "fat": 5000,
            "vitaminC": 123,
        }
        with patch.object(MCP, "get_product", return_value=current):
            result = self.service.update_product(
                42, {"carbohydrates_grams": 25}, confirm=False
            )
        self.assertEqual(result["before"], current)
        self.assertEqual(result["product"]["carbohydrates"], 25000)
        self.assertEqual(result["product"]["fat"], 5000)
        self.assertEqual(result["product"]["vitaminC"], 123)

    def test_confirmed_delete_verifies_404(self) -> None:
        missing = HTTPError("https://example.invalid/products/42", 404, "Not Found", {}, None)
        self.addCleanup(missing.close)
        with (
            patch.object(MCP, "api_delete_product", return_value="ok"),
            patch.object(
                MCP,
                "get_product",
                side_effect=[{"id": 42, "label": "Custom"}, missing],
            ),
        ):
            result = self.service.delete_product(42, confirm=True)
        self.assertTrue(result["verified_absent"])


class EatMyRideLiveFoodplanServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MCP.EatMyRideLiveService(lambda: FakeCredentials())

    def test_confirmed_write_handles_multiple_products_in_one_plan(self) -> None:
        products = {
            3111: {"id": 3111, "label": "SiS", "ingredientsQtyUnit": "gram"},
            10139011: {"id": 10139011, "label": "Seigmann", "ingredientsQtyUnit": "piece"},
        }
        verified = [
            {"productId": 3111, "product": products[3111], "gram": 60, "ml": 900, "time": 4101},
            *[
                {"productId": 10139011, "product": products[10139011], "gram": 1, "time": time_s}
                for time_s in (962, 1859, 2756, 3653, 4550, 5447, 6344, 7241)
            ],
        ]
        with (
            patch.object(MCP, "get_foodplan", side_effect=[[], verified]),
            patch.object(MCP, "get_product", side_effect=lambda product_id, **_: products[product_id]),
            patch.object(MCP, "get_activity", side_effect=[{"id": 6700333}, {"id": 6700333}]),
            patch.object(MCP, "post_foodplan", return_value={}) as write_plan,
            patch.object(MCP, "put_activity", return_value={}) as write_activity,
        ):
            result = self.service.set_foodplan_products(
                "6700333",
                [
                    {"product_id": 3111, "gram": 60, "ml": 900, "time_s": 4101},
                    {"product_id": 10139011, "pieces": 8, "start_s": 513, "end_s": 7689},
                ],
                confirm=True,
            )

        self.assertTrue(result["verified"])
        self.assertEqual(result["change"]["event_count_after"], 9)
        write_plan.assert_called_once()
        write_activity.assert_called_once()

    def test_failure_after_foodplan_write_exposes_partial_mutation_boundary(self) -> None:
        server_error = HTTPError(
            "https://example.invalid/activity/6700333", 500, "Server Error", {}, None
        )
        self.addCleanup(server_error.close)
        with (
            patch.object(MCP, "get_foodplan", return_value=[]),
            patch.object(MCP, "get_product", return_value={"id": 3111, "label": "SiS"}),
            patch.object(MCP, "get_activity", return_value={"id": 6700333}),
            patch.object(MCP, "post_foodplan", return_value={}) as write_plan,
            patch.object(MCP, "put_activity", side_effect=server_error) as write_activity,
        ):
            with self.assertRaises(HTTPError) as raised:
                self.service.set_foodplan_products(
                    "6700333",
                    [{"product_id": 3111, "gram": 60, "ml": 900, "time_s": 4101}],
                    confirm=True,
                )

        self.assertEqual(raised.exception.code, 500)
        write_plan.assert_called_once()
        write_activity.assert_called_once()


class EatMyRideAuthSessionTests(unittest.TestCase):
    def test_reuses_one_bearer_token_within_service_session(self) -> None:
        credentials = CountingCredentials()
        service = MCP.EatMyRideLiveService(lambda: credentials)
        observed = [service._auth.bearer_token(), service._auth.bearer_token()]
        self.assertEqual(credentials.login_calls, 1)
        self.assertEqual(observed, ["token-1", "token-1"])

    def test_rejected_token_is_invalidated_and_login_retried_once(self) -> None:
        credentials = CountingCredentials()
        service = MCP.EatMyRideLiveService(lambda: credentials)
        rejected = HTTPError("https://example.invalid", 401, "Unauthorized", {}, None)
        self.addCleanup(rejected.close)
        tokens = []

        def operation(token):
            tokens.append(token)
            if len(tokens) == 1:
                raise rejected
            return "ok"

        self.assertEqual(service._run(operation), "ok")
        self.assertEqual(credentials.login_calls, 2)
        self.assertEqual(tokens, ["token-1", "token-2"])

    def test_create_is_not_repeated_when_readback_refreshes_auth(self) -> None:
        credentials = CountingCredentials()
        service = MCP.EatMyRideLiveService(lambda: credentials)
        rejected = HTTPError("https://example.invalid", 401, "Unauthorized", {}, None)
        self.addCleanup(rejected.close)

        with (
            patch.object(MCP, "api_create_product", return_value={"id": 42}) as create,
            patch.object(
                MCP,
                "get_product",
                side_effect=[rejected, {"id": 42, "label": "Verified"}],
            ) as read,
        ):
            result = service.create_product({"label": "Gel"}, confirm=True)

        self.assertTrue(result["verified"])
        create.assert_called_once()
        self.assertEqual(read.call_count, 2)
        self.assertEqual(credentials.login_calls, 2)

    def test_separate_service_sessions_do_not_share_tokens(self) -> None:
        first_credentials = CountingCredentials()
        second_credentials = CountingCredentials()
        first = MCP.EatMyRideLiveService(lambda: first_credentials)
        second = MCP.EatMyRideLiveService(lambda: second_credentials)
        self.assertEqual(first._auth.bearer_token(), "token-1")
        self.assertEqual(second._auth.bearer_token(), "token-1")
        self.assertEqual(first_credentials.login_calls, 1)
        self.assertEqual(second_credentials.login_calls, 1)


if __name__ == "__main__":
    unittest.main()
