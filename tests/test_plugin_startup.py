"""Exercise the distributed MCP launch commands, without fetching athlete data."""

import asyncio
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


class PluginStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_plugin_manifests_initialize_and_list_tools(self):
        manifests = sorted((ROOT / "plugins").glob("*/.mcp.json"))
        self.assertTrue(manifests, "No plugin launch manifests found")
        marketplace = json.loads((ROOT / ".agents/plugins/marketplace.json").read_text())
        bundles = {
            plugin["name"]: ROOT / plugin["source"]["path"]
            for plugin in marketplace["plugins"]
            if plugin["source"].get("path", "").startswith("./dist/")
        }
        for manifest in manifests:
            plugin = manifest.parent.name
            if plugin in bundles:
                if sys.platform != "darwin" or platform.machine() != "arm64":
                    with self.subTest(plugin=plugin):
                        self.skipTest("Plugin builds for macOS arm64")
                    continue
                subprocess.run(
                    [sys.executable, "-B", str(ROOT / "scripts/build_plugin.py"), plugin],
                    cwd=ROOT, check=True,
                )
                manifest = bundles[plugin] / ".mcp.json"
            for name, config in json.loads(manifest.read_text())["mcpServers"].items():
                with self.subTest(plugin=name), tempfile.TemporaryFile(mode="w+") as stderr:
                    params = StdioServerParameters(
                        command=config["command"],
                        args=config["args"],
                        cwd=str((manifest.parent / config.get("cwd", ".")).resolve()),
                        env=config.get("env"),
                    )
                    try:
                        async with asyncio.timeout(60):
                            async with stdio_client(params, errlog=stderr) as (read, write):
                                async with ClientSession(read, write) as client:
                                    initialized = await client.initialize()
                                    self.assertEqual(initialized.serverInfo.name, name)
                                    catalog = await client.list_tools()
                                    self.assertTrue(catalog.tools)
                    except Exception:
                        stderr.seek(0)
                        self.fail(f"{name} failed to start via {manifest}:\n{stderr.read()}")
                    for tool in catalog.tools:
                        with self.subTest(tool=tool.name):
                            hints = tool.annotations
                            self.assertIsNotNone(hints)
                            self.assertTrue(tool.title or hints.title)
                            self.assertIsInstance(hints.readOnlyHint, bool)
                            self.assertIsInstance(hints.openWorldHint, bool)
                            if hints.readOnlyHint:
                                self.assertIsNone(hints.destructiveHint)
                                self.assertIsNone(hints.idempotentHint)
                            else:
                                self.assertIsInstance(hints.destructiveHint, bool)
                                self.assertIsInstance(hints.idempotentHint, bool)
                            properties = tool.inputSchema.get("properties", {})
                            if {"save_full", "save_session", "save_series"} & properties.keys():
                                self.assertFalse(hints.readOnlyHint)
                                self.assertFalse(hints.destructiveHint)
                                self.assertFalse(hints.idempotentHint)
                            if "overwrite" in properties:
                                self.assertFalse(hints.readOnlyHint)
                                self.assertTrue(hints.destructiveHint)
