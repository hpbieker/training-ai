#!/usr/bin/env python3
"""Test real stdio MCP discovery/call/resource and render via official AppBridge."""
import argparse
import json
from pathlib import Path
import sys
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from map_tiles import get_map_tile


async def prepare(arguments):
    async with stdio_client(StdioServerParameters(command=sys.executable, args=['-B', str(ROOT / 'training_visuals_mcp.py')])) as (read, write):
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
            csp = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: https://tile.openstreetmap.org; connect-src 'none'; base-uri 'none'; frame-src 'none'"
            html = html.replace('<head>', '<head><meta http-equiv="Content-Security-Policy" content="' + escape(csp, quote=True) + '">', 1)
            return {'html': html, 'arguments': arguments, 'result': result.model_dump(by_alias=True, exclude_none=True)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arguments', type=Path, required=True, help='JSON file containing show_route arguments.')
    parser.add_argument('--port', type=int, default=8767)
    opts = parser.parse_args()
    payload = anyio.run(prepare, json.loads(opts.arguments.read_text()))
    data = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')
    shell = (ROOT / 'web/test-host.html').read_text().replace('__TEST_DATA__', data)
    script = (ROOT / 'web/dist/test-host.js').read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/tool':
                self.send_error(404)
                return
            try:
                request = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
                if request['name'] != 'get_map_tile':
                    raise ValueError('Unknown test tool')
                data = get_map_tile(**request['arguments'])
                result = {'content':[{'type':'text','text':'Map tile'}], '_meta':{'data_url':data}}
            except Exception as exc:
                result = {'isError':True,'content':[{'type':'text','text':str(exc)}]}
            content = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            if self.path == '/':
                content, mime = shell.encode(), 'text/html; charset=utf-8'
            elif self.path == '/test-host.js':
                content, mime = script, 'text/javascript; charset=utf-8'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)

    print(f'MCP App test: http://127.0.0.1:{opts.port}/', flush=True)
    ThreadingHTTPServer(('127.0.0.1', opts.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
