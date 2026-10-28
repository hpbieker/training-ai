"""Exercise the distributed MCP launch commands, without fetching athlete data."""

import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]


class PluginStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_plugin_manifests_initialize_and_list_tools(self):
        manifests = sorted((ROOT / "plugins").glob("*/.mcp.json"))
        self.assertTrue(manifests, "No plugin launch manifests found")
        for manifest in manifests:
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
