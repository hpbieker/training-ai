#!/usr/bin/env python3
"""Test real stdio MCP discovery/call/resource and render via official AppBridge."""
import argparse
import json
from pathlib import Path
import sys
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import anyio
from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from map_tiles import get_map_tile
from route_planner_mcp import STREET_VIEW_EMBED_KEY, UPDATE_ROUTE, get_route_view, route_directory, update_route


async def prepare(arguments):
    env = {'ROUTE_PLANNER_ROUTES': str(route_directory())}
    server = StdioServerParameters(
        command=sys.executable, args=['-B', str(ROOT / 'route_planner_mcp.py')], env=env,
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool = next(t for t in tools.tools if t.name == 'show_route')
            result = await session.call_tool('show_route', arguments)
            if result.isError:
                raise ValueError(result.content)
            uri = tool.meta['ui']['resourceUri']
            resource = await session.read_resource(uri)
            html = resource.contents[0].text
            frame_src = 'https://www.google.com' if STREET_VIEW_EMBED_KEY else "'none'"
            return html, frame_src, {'arguments': arguments, 'result': result.model_dump(by_alias=True, exclude_none=True)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arguments', type=Path, required=True, help='JSON file containing show_route arguments.')
    parser.add_argument('--port', type=int, default=8767)
    opts = parser.parse_args()
    html, frame_src, payload = anyio.run(prepare, json.loads(opts.arguments.read_text()))

    csp = (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        f"img-src data:; base-uri 'none'; frame-src {frame_src}"
    )
    head = '<meta http-equiv="Content-Security-Policy" content="' + escape(csp, quote=True) + '">'
    app_html = html.replace('<head>', '<head>' + head, 1).encode()
    data = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')
    shell = (ROOT / 'web/test-host.html').read_text().replace('__TEST_DATA__', data)
    script = (ROOT / 'web/dist/test-host.js').read_bytes()
    preview_host = f'127.0.0.1:{opts.port}'
    preview_origin = f'http://{preview_host}'
    saved_route_id = payload['arguments'].get('route_id')
    validate_update = Draft202012Validator(UPDATE_ROUTE.inputSchema).is_valid

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/tool':
                self.send_error(404)
                return
            if (self.headers.get('Host') != preview_host
                    or self.headers.get('Origin') != preview_origin
                    or self.headers.get_content_type() != 'application/json'):
                self.send_error(403)
                return
            try:
                request = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                if request['name'] == 'get_map_tile':
                    data = get_map_tile(**request['arguments'])
                    result = {'content':[{'type':'text','text':'Map tile'}], '_meta':{'data_url':data}}
                elif request['name'] == 'get_route_view':
                    route = get_route_view(request['arguments'])
                    result = {'content': [], 'structuredContent': {'route': route} if route else {}}
                elif request['name'] == 'update_route':
                    changes = request['arguments']
                    if (
                        not saved_route_id
                        or not validate_update(changes)
                        or changes['route_id'] != saved_route_id
                        or set(changes) - {'route_id', 'expected_revision'} not in (
                            {'add_waypoint'}, {'move_waypoint'}, {'remove_waypoint_id'},
                        )
                    ):
                        raise ValueError('The preview only supports editing one waypoint on its saved route.')
                    result = {'content': [], 'structuredContent': update_route(changes)}
                else:
                    raise ValueError('Unknown test tool')
            except Exception as exc:
                result = {'isError':True,'content':[{'type':'text','text':str(exc)}]}
            content = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if self.headers.get('Host') != preview_host:
                self.send_error(403)
                return
            if self.path in {'/', '/mcp-test'}:
                content, mime = shell.encode(), 'text/html; charset=utf-8'
            elif self.path == '/app':
                content, mime = app_html, 'text/html; charset=utf-8'
            elif self.path == '/test-host.js':
                content, mime = script, 'text/javascript; charset=utf-8'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)

    print(f'MCP App test: http://127.0.0.1:{opts.port}/', flush=True)
    ThreadingHTTPServer(('127.0.0.1', opts.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
