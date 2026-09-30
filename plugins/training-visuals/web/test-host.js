// Local test host uses the official bridge, not a custom approximation.
import { AppBridge, PostMessageTransport } from '@modelcontextprotocol/ext-apps/app-bridge';
const data = JSON.parse(document.getElementById('test-data').textContent);
const iframe = document.getElementById('app');
const status = document.getElementById('test-status');
const bridge = new AppBridge(null, { name: 'Training Visuals local test', version: '0.1.0' }, { openLinks: {}, serverTools: {} }, {
  hostContext: { theme: 'light', displayMode: 'inline', availableDisplayModes: ['inline'], locale: 'nb-NO' },
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
bridge.onsizechange = ({ height }) => { if (height) iframe.style.height = `${Math.max(300, Math.min(height, 1600))}px`; };
bridge.onopenlink = async ({ url }) => {
  if (!/^https:\/\//.test(url)) return { isError: true };
  window.open(url, '_blank', 'noopener');
  return {};
};
bridge.onerror = (error) => { status.textContent = `MCP Apps-feil: ${error.message}`; };
(async () => {
  await bridge.connect(new PostMessageTransport(iframe.contentWindow, iframe.contentWindow));
  iframe.srcdoc = data.html;
})().catch(error => { status.textContent = error.message; });
