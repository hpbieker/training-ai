import { App } from '@modelcontextprotocol/ext-apps';
import L from 'leaflet';

const app = new App({ name: 'Training Visuals', version: '0.1.0' });
const el = (id) => document.getElementById(id);
const message = el('message');
const map = L.map('map', {
  zoomControl: false,
  scrollWheelZoom: true,
  zoomSnap: 0,
  wheelDebounceTime: 16,
  wheelPxPerZoomLevel: 120,
  // Apply small wheel updates immediately instead of queuing zoom animations.
  zoomAnimation: false,
});
L.control.zoom({ position: 'topright' }).addTo(map);
const Tiles = L.GridLayer.extend({
  createTile(coords, done) {
    const tile = document.createElement('img');
    tile.alt = '';
    tile.onload = () => done(null, tile);
    tile.onerror = () => done(new Error('Could not display map tile'), tile);
    app.callServerTool({name:'get_map_tile', arguments:{z:coords.z,x:coords.x,y:coords.y}})
      .then(result => {
        if (result.isError || !result._meta?.data_url) throw new Error('Could not load map tile');
        tile.src = result._meta.data_url;
      }).catch(error => done(error, tile));
    return tile;
  },
});
const tiles = new Tiles({maxZoom:19, attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'});
let routeLayers = L.featureGroup().addTo(map);
let routeBounds;
let failedTiles = 0;
tiles.on('loading', () => { failedTiles = 0; });
tiles.on('tileerror', () => {
  failedTiles += 1;
  message.textContent = 'Map tiles could not be loaded. Check your connection or the host’s map access.';
  message.hidden = false;
});
tiles.on('load', () => { if (!failedTiles && routeBounds) message.hidden = true; });

const metricIcons = {
  distance: '<path d="M3 12h18M7 8l-4 4 4 4m10-8 4 4-4 4"/>',
  elevation: '<path d="M5 19 19 5M7 5h12v12"/>',
};
function metric(value, suffix, label, icon) {
  const node = document.createElement('div');
  const strong = document.createElement('strong');
  strong.textContent = `${value}${suffix}`;
  if (icon) {
    const symbol = document.createElement('span');
    symbol.className = 'metric-icon';
    symbol.setAttribute('aria-hidden', 'true');
    symbol.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" focusable="false">${metricIcons[icon]}</svg>`;
    node.className = 'icon-metric';
    node.title = label;
    node.setAttribute('role', 'img');
    node.setAttribute('aria-label', `${label}: ${value}${suffix}`);
    node.append(symbol, strong);
  } else {
    const description = document.createElement('span');
    description.textContent = label;
    node.append(strong, description);
  }
  el('stats').append(node);
}

function endpoint(point, finish = false) {
  const label = finish ? 'Finish' : 'Start';
  const svg = finish
    ? '<svg viewBox="0 0 28 30" aria-hidden="true"><path d="M4 28V3" stroke="white" stroke-width="5"/><path d="M4 28V3" stroke="#222" stroke-width="2"/><path d="M5 3h20v16H5z" fill="white" stroke="#222" stroke-width="1.5"/><path d="M5 3h5v4H5zm10 0h5v4h-5zm-5 4h5v4h-5zm10 0h5v4h-5zM5 11h5v4H5zm10 0h5v4h-5zm-5 4h5v4h-5zm10 0h5v4h-5z" fill="#222"/></svg>'
    : '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7" fill="#27a65b" stroke="white" stroke-width="3"/></svg>';
  L.marker(point, {
    icon: L.divIcon({className: 'route-endpoint', html: svg,
      iconSize: finish ? [28, 30] : [20, 20], iconAnchor: finish ? [4, 28] : [10, 10]}),
    title: label, alt: label, zIndexOffset: finish ? 1000 : 900,
  }).addTo(routeLayers);
}
function fit() {
  if (!routeBounds) return;
  map.fitBounds(routeBounds, { padding: [12, 12], maxZoom: 19, animate: false });
}
el('fit').addEventListener('click', fit);
el('expand').addEventListener('click', () => {
  const expanded = document.querySelector('main').classList.toggle('expanded');
  el('expand').textContent = expanded ? 'Smaller map' : 'Larger map';
  el('expand').setAttribute('aria-expanded', String(expanded));
  map.invalidateSize();
  fit();
});

function render(route) {
  if (route?.geometry?.type !== 'MultiLineString' || !route.geometry.coordinates?.length) {
    throw new Error('Route data is missing from the tool result. Run show_route again.');
  }
  const segments = route.geometry.coordinates.map(line => line.map(([lon, lat]) => [lat, lon]));
  routeLayers.clearLayers();
  document.querySelector('h1').textContent = route.title || 'Cycling route';
  document.querySelector('header').hidden = false;
  el('date').textContent = route.date || '';
  el('date').hidden = !route.date;
  el('stats').replaceChildren();
  const fmt = (v, digits = 0) => new Intl.NumberFormat('en-GB', { maximumFractionDigits: digits }).format(v);
  if (Number.isFinite(route.distance_km)) metric(fmt(route.distance_km, 1), ' km', 'Distance', 'distance');
  if (Number.isFinite(route.moving_time_s)) {
    const minutes = Math.round(route.moving_time_s / 60);
    metric(`${Math.floor(minutes / 60)} h ${minutes % 60} min`, '', 'Moving time');
  }
  if (Number.isFinite(route.elevation_gain_m)) metric(fmt(route.elevation_gain_m), ' m', 'Elevation gain', 'elevation');
  for (const line of segments) {
    L.polyline(line, { color: '#fff', weight: 6, opacity: .9, interactive: false }).addTo(routeLayers);
    L.polyline(line, { color: '#e65c36', weight: 3, opacity: 1, interactive: false }).addTo(routeLayers);
  }
  const start = segments[0][0], end = segments.at(-1).at(-1);
  endpoint(start);
  endpoint(end, true);
  routeBounds = routeLayers.getBounds();
  el('fit').disabled = false;
  message.hidden = true;
  map.invalidateSize();
  if (!map.hasLayer(tiles)) tiles.addTo(map);
  fit();
}

// Install handlers before connect: hosts can immediately send the initial result.
app.ontoolresult = (result) => {
  try {
    if (result.isError) throw new Error(result.content?.find(c => c.type === 'text')?.text || 'Could not display the route.');
    render(result._meta?.route);
  } catch (error) {
    message.textContent = error.message;
    message.hidden = false;
  }
};
app.onhostcontextchanged = (context) => {
  if (context.theme) document.documentElement.style.colorScheme = context.theme;
};
app.onteardown = async () => { observer.disconnect(); map.remove(); return {}; };
const observer = new ResizeObserver(() => map.invalidateSize());
observer.observe(el('map'));
app.connect().then(() => {
  const context = app.getHostContext();
  if (context?.theme) document.documentElement.style.colorScheme = context.theme;
}).catch(() => {
  message.textContent = 'Open this view through show_route in a host that supports MCP Apps.';
  message.hidden = false;
});
