#!/usr/bin/env python3
"""Read-only stdio MCP server serving one portable MCP App."""
import json
from pathlib import Path
import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server
from route_data import normalize_route
from map_tiles import get_map_tile
import httpx

ROOT = Path(__file__).resolve().parent
VERSION = json.loads((ROOT / '.codex-plugin/plugin.json').read_text())['version']
UI_URI = 'ui://training-visuals/show-route.html'
UI_MIME = 'text/html;profile=mcp-app'
UI_META = {'ui': {'prefersBorder': True, 'csp': {'resourceDomains': [], 'connectDomains': []}}}
PROPERTIES = {
    'geojson': {'type': 'object', 'description': 'GeoJSON LineString, MultiLineString, Feature or FeatureCollection. Coordinates are [longitude, latitude].'},
    'route_file': {'type': 'string', 'description': 'Absolute local path to an existing GPX, GeoJSON, or training-ai route JSON artifact. Prefer this for large GPS traces.'},
    'title': {'type': 'string', 'maxLength': 300},
    'date': {'type': 'string', 'maxLength': 300, 'description': 'Optional human-readable date label in English, e.g. 30 May 2026.'},
    'status': {'type': 'string', 'enum': ['planned', 'completed']},
    'distance_km': {'type': 'number', 'minimum': 0},
    'moving_time_s': {'type': 'number', 'minimum': 0},
    'elevation_gain_m': {'type': 'number', 'minimum': 0},
    'source_url': {'type': 'string', 'description': 'Optional HTTPS link to the source activity or route.'},
    'source_label': {'type': 'string', 'maxLength': 300, 'description': 'Source service name, e.g. Strava or Intervals.icu.'},
}
TOOL = {
    'name': 'show_route', 'title': 'Show cycling route',
    'description': 'Display a planned or completed cycling route in an interactive map. First obtain GPS geometry from an existing source tool or local file. Supply exactly one of geojson or route_file. Does not fetch activities, plan routes, or modify source data. Optional metrics must come from the source; omit unavailable values. Loads OpenStreetMap tiles in the UI.',
    'inputSchema': {'type': 'object', 'properties': PROPERTIES, 'additionalProperties': False, 'oneOf': [{'required': ['geojson'], 'not': {'required': ['route_file']}}, {'required': ['route_file'], 'not': {'required': ['geojson']}}]},
    'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': True},
    '_meta': {'ui': {'resourceUri': UI_URI}},
}


def show_route(arguments):
    route = normalize_route(arguments)
    lines = route['geometry']['coordinates']
    summary = {key: value for key, value in route.items() if key != 'geometry'}
    summary.update(point_count=sum(map(len, lines)), segment_count=len(lines))
    return types.CallToolResult(
        content=[types.TextContent(type='text', text=json.dumps(summary, ensure_ascii=False))],
        structuredContent=summary,
        # Full geometry reaches the view without duplicating the GPS trace in model context.
        _meta={'route': route},
    )


def create_server():
    server = Server('training-visuals', version=VERSION)

    @server.list_tools()
    async def list_tools():
        return [types.Tool.model_validate(TOOL), types.Tool(name='get_map_tile', description='Load one visible map tile. App-only; never prefetch.', inputSchema={'type':'object','properties':{k:{'type':'integer'} for k in ('z','x','y')},'required':['z','x','y'],'additionalProperties':False}, annotations=types.ToolAnnotations(readOnlyHint=True, openWorldHint=True), _meta={'ui':{'visibility':['app']}})]

    @server.call_tool()
    async def call_tool(name, arguments):
        try:
            if name == 'get_map_tile':
                data = await anyio.to_thread.run_sync(get_map_tile, arguments['z'], arguments['x'], arguments['y'])
                return types.CallToolResult(content=[types.TextContent(type='text', text='Map tile')], _meta={'data_url': data})
            if name != 'show_route':
                raise ValueError('Unknown tool: ' + name)
            return await anyio.to_thread.run_sync(show_route, arguments)
        except (ValueError, OSError, KeyError, TypeError, httpx.HTTPError) as exc:
            return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text=str(exc))])

    @server.list_resources()
    async def list_resources():
        return [types.Resource(uri=UI_URI, name='show-route', title='Cycling route', mimeType=UI_MIME, _meta=UI_META)]

    @server.read_resource()
    async def read_resource(uri):
        if str(uri) != UI_URI:
            raise ValueError('Unknown resource')
        return [ReadResourceContents((ROOT / 'web/dist/show-route.html').read_text(), UI_MIME, UI_META)]

    return server


async def main():
    server = create_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == '__main__':
    anyio.run(main)
