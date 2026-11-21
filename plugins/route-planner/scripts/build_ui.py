#!/usr/bin/env python3
"""Build the standalone route map and bundle its browser libraries."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
DIST = WEB / 'dist'


def bundle(entry):
    return subprocess.check_output([
        str(WEB / 'node_modules/.bin/esbuild'), entry, '--bundle', '--minify',
        '--format=iife', '--target=es2022', '--legal-comments=inline',
    ], cwd=WEB, text=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preview', action='store_true', help='Also bundle the local MCP Apps test host.')
    options = parser.parse_args()
    script = bundle('app.js').replace('</script', '<\\/script')
    css = (WEB / 'node_modules/leaflet/dist/leaflet.css').read_text()
    css = re.sub(r'url\([^)]*images/[^)]*\)', 'none', css)
    css += '\n' + (WEB / 'style.css').read_text()
    html = (WEB / 'show-route.html').read_text().replace('/*__STYLES__*/', css).replace('/*__SCRIPT__*/', script)
    DIST.mkdir(exist_ok=True)
    if options.preview:
        (DIST / 'test-host.js').write_text(bundle('test-host.js'), encoding='utf-8')
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=DIST, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(html)
            output.close()
            temporary.replace(DIST / 'show-route.html')
        finally:
            temporary.unlink(missing_ok=True)
    print(f'Built show-route.html ({len(html.encode())} bytes)')


if __name__ == '__main__':
    main()
