#!/usr/bin/env python3
"""Bundle browser libraries; installed MCP runtime only needs Python."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
DIST = WEB / 'dist'


def bundle(entry):
    return subprocess.check_output([
        str(WEB / 'node_modules/.bin/esbuild'), entry, '--bundle', '--minify',
        '--format=iife', '--target=es2022', '--legal-comments=inline',
    ], cwd=WEB, text=True)


def main():
    script = bundle('app.js').replace('</script', '<\\/script')
    css = (WEB / 'node_modules/leaflet/dist/leaflet.css').read_text()
    css = re.sub(r'url\([^)]*images/[^)]*\)', 'none', css)
    css += '\n' + (WEB / 'style.css').read_text()
    html = (WEB / 'show-route.html').read_text().replace('/*__STYLES__*/', css).replace('/*__SCRIPT__*/', script)
    DIST.mkdir(exist_ok=True)
    (DIST / 'show-route.html').write_text(html)
    (DIST / 'test-host.js').write_text(bundle('test-host.js'))
    print(f'Built show-route.html ({len(html.encode())} bytes) and test-host.js')


if __name__ == '__main__':
    main()
