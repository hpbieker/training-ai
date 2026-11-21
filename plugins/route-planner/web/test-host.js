// Local test host uses the official bridge, not a custom approximation.
import { AppBridge, PostMessageTransport } from '@modelcontextprotocol/ext-apps/app-bridge';
const data = JSON.parse(document.getElementById('test-data').textContent);
const iframe = document.getElementById('app');
const status = document.getElementById('test-status');
const bridge = new AppBridge(null, { name: 'Route Planner local preview', version: '0.2.2' }, { openLinks: {}, serverTools: {} }, {
  hostContext: { theme: 'light', displayMode: 'fullscreen', availableDisplayModes: ['fullscreen'], locale: 'nb-NO' },
});
bridge.oncalltool = async (request) => {
  const response = await fetch('/tool', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(request)});
  return await response.json();
};
bridge.oninitialized = async () => {
  await bridge.sendToolInput({ arguments: data.arguments });
  await bridge.sendToolResult(data.result);
  status.textContent = 'MCP Apps: tilkoblet · show_route levert';
};
// The browser window sizes this preview. Inline chat may use the app's preferred height.
bridge.onsizechange = () => {};
bridge.onopenlink = async ({ url }) => {
  if (!/^https:\/\//.test(url)) return { isError: true };
  window.open(url, '_blank', 'noopener');
  return {};
};
bridge.onerror = (error) => { status.textContent = `MCP Apps-feil: ${error.message}`; };
(async () => {
  await bridge.connect(new PostMessageTransport(iframe.contentWindow, iframe.contentWindow));
  // An HTTP document gives provider embeds the preview's actual origin.
  iframe.src = '/app';
})().catch(error => { status.textContent = error.message; });
