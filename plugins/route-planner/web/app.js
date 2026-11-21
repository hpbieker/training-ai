import { App } from '@modelcontextprotocol/ext-apps';
import L from 'leaflet';
import { enablePointerZoom } from './wheel_zoom.js';
const el = (id) => document.getElementById(id);
const app = new App({ name: 'Route Planner', version: '0.2.13' }, {}, { autoResize: false });
const header = document.querySelector('header');
const main = document.querySelector('main');
const mapWrap = document.querySelector('.map-wrap');
const expandButton = el('expand');
const routeMessage = el('route-message');
const tileMessage = el('tile-message');
const surfaceLegend = el('surface-legend');
const RouteRenderer = L.SVG.extend({
  getEvents() {
    return { ...L.SVG.prototype.getEvents.call(this), move: this.updateDuringPan };
  },

  updateDuringPan() {
    const map = this._map;
    if (!this._bounds || map.getZoom() !== this._zoom) return;

    // Leaflet clips the route to a padded viewport. Redraw once dragging
    // exposes an area beyond that viewport.
    const topLeft = map.containerPointToLayerPoint([0, 0]);
    const bottomRight = topLeft.add(map.getSize());
    if (!this._bounds.contains(topLeft) || !this._bounds.contains(bottomRight)) {
      this._update();
    }
  },
});
const map = L.map('map', {
  attributionControl: false,
  zoomControl: false,
  scrollWheelZoom: false,
  zoomSnap: 0,
  wheelPxPerZoomLevel: 120,
  zoomAnimation: true,
  renderer: new RouteRenderer(),
});
const disablePointerZoom = enablePointerZoom(map);
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
const tiles = new Tiles({ maxZoom: 19, updateWhenZooming: true, updateWhenIdle: false });
let routeLayers = L.featureGroup().addTo(map);
let routeBounds;
let displayedRoute;
let refreshTimer;
let closed = false;
let connected = false;
let preferredHeight;
let refreshFailures = 0;
let failedTiles = false;
tiles.on('loading', () => { failedTiles = false; });
tiles.on('tileerror', () => {
  failedTiles = true;
  tileMessage.hidden = false;
});
tiles.on('load', () => { tileMessage.hidden = !failedTiles; });

const metricIcons = {
  distance: '<path d="M3 12h18M7 8l-4 4 4 4m10-8 4 4-4 4"/>',
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

const POINT_ICON_SIZE = [26, 26];
// Override Leaflet's screen-Y ordering when waypoint icons overlap.
const WAYPOINT_STACK_STEP = 32;
const ROUTE_BLUE = '#2656b1';
const ROUTE_WIDTH = 4.5;
function endpoint(point, marker, label, order) {
  const badge = document.createElement('span');
  badge.className = 'endpoint-badge';
  badge.dataset.endpoint = marker;
  badge.setAttribute('aria-hidden', 'true');
  badge.textContent = marker;
  L.marker(point, {
    icon: L.divIcon({className: 'route-endpoint', html: badge, iconSize: [24, 24]}),
    title: label, alt: label, zIndexOffset: -order * WAYPOINT_STACK_STEP,
  }).addTo(routeLayers);
}

function addWaypoint(point, order) {
  const label = `Waypoint #${point.index}`;
  const number = document.createElement('span');
  number.textContent = String(point.index);
  L.marker([point.on_route.lat, point.on_route.lon], {
    icon: L.divIcon({className: 'route-waypoint', html: number, iconSize: POINT_ICON_SIZE}),
    title: label, alt: label, zIndexOffset: -order * WAYPOINT_STACK_STEP,
  }).addTo(routeLayers);
}

function fit() {
  if (!routeBounds) return;
  map.fitBounds(routeBounds, { padding: [12, 12], maxZoom: 19, animate: false });
}

function reportPreferredHeight() {
  if (!connected || closed || main.classList.contains('fullscreen')) return;
  const mapHeight = parseFloat(getComputedStyle(mapWrap).getPropertyValue('--preferred-map-height'));
  const height = Math.ceil(header.getBoundingClientRect().height + mapHeight);
  if (height === preferredHeight) return;
  preferredHeight = height;
  void app.sendSizeChanged({ height }).catch(() => {
    if (preferredHeight === height) preferredHeight = undefined;
  });
}

el('fit').addEventListener('click', fit);
let hidingWithKey = false;

function releaseRouteKey() {
  if (!hidingWithKey) return;
  hidingWithKey = false;
  routeLayers.addTo(map);
  mapWrap.classList.remove('route-hidden');
}
document.addEventListener('keydown', event => {
  if (event.defaultPrevented || event.repeat || event.ctrlKey || event.metaKey || event.altKey
      || event.target?.closest?.('input, textarea, select, [contenteditable]')) return;
  if (event.key.toLowerCase() === 'm' && displayedRoute) {
    event.preventDefault();
    hidingWithKey = true;
    routeLayers.remove();
    mapWrap.classList.add('route-hidden');
    map.closePopup();
  }
});
document.addEventListener('keyup', event => {
  if (event.key.toLowerCase() === 'm') releaseRouteKey();
});
window.addEventListener('blur', releaseRouteKey);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) releaseRouteKey();
});
expandButton.addEventListener('click', () => {
  const expanded = main.classList.toggle('expanded');
  const label = expanded ? 'Smaller map' : 'Larger map';
  expandButton.title = label;
  expandButton.setAttribute('aria-label', label);
  expandButton.setAttribute('aria-expanded', String(expanded));
  map.invalidateSize();
  reportPreferredHeight();
});

function render(route) {
  if (route?.geometry?.type !== 'MultiLineString' || !route.geometry.coordinates?.length) {
    throw new Error('Could not load the route data.');
  }
  const sameRoute = route.route_id && route.route_id === displayedRoute?.route_id;
  if (sameRoute && route.revision <= displayedRoute.revision) return;
  const segments = route.geometry.coordinates.map(line => line.map(([lon, lat]) => [lat, lon]));
  map.closePopup();
  routeLayers.clearLayers();
  document.querySelector('h1').textContent = route.title || 'Route';
  header.hidden = false;
  el('date').textContent = route.date || '';
  el('date').hidden = !route.date;
  el('stats').replaceChildren();
  const fmt = (v, digits = 0) => new Intl.NumberFormat('en-GB', { maximumFractionDigits: digits }).format(v);
  if (Number.isFinite(route.distance_km)) metric(fmt(route.distance_km, 1), ' km', 'Distance', 'distance');
  const duration = route.estimated_time_s ?? route.moving_time_s;
  if (Number.isFinite(duration)) {
    const minutes = Math.round(duration / 60);
    const label = route.estimated_time_s === undefined ? 'Moving time' : 'Estimated time';
    metric(`${Math.floor(minutes / 60)} h ${minutes % 60} min`, '', label);
  }
  if (Number.isFinite(route.elevation_gain_m)) metric(fmt(route.elevation_gain_m), ' m', 'Elevation gain');
  const lineOptions = { opacity: 1, interactive: false, smoothFactor: 0 };
  L.polyline(segments, { ...lineOptions, color: '#fff', weight: ROUTE_WIDTH + 2 }).addTo(routeLayers);
  L.polyline(segments, { ...lineOptions, color: ROUTE_BLUE, weight: ROUTE_WIDTH }).addTo(routeLayers);
  for (const item of surfaceLegend.children) {
    const lines = route.surface_lines?.[item.dataset.surface];
    item.hidden = !lines?.length;
    if (item.hidden) continue;
    const latLngLines = lines.map(line => line.map(([lon, lat]) => [lat, lon]));
    L.polyline(latLngLines, {
      ...lineOptions,
      color: getComputedStyle(item).getPropertyValue('--surface-color').trim(),
      weight: ROUTE_WIDTH,
      lineCap: 'butt',
    }).addTo(routeLayers);
  }
  surfaceLegend.hidden = !surfaceLegend.querySelector('li:not([hidden])');
  if (route.ferry_lines?.length) {
    const ferries = route.ferry_lines.map(line => line.map(([lon, lat]) => [lat, lon]));
    L.polyline(ferries, { ...lineOptions, color: '#fff', weight: 2, lineCap: 'butt' }).addTo(routeLayers);
  }
  const start = segments[0][0], end = segments.at(-1).at(-1);
  endpoint(start, 'A', 'Start', 0);
  let order = 1;
  for (const point of route.points ?? []) {
    if (point.role === 'waypoint') addWaypoint(point, order++);
  }
  endpoint(end, 'B', 'Finish', order);
  routeBounds = routeLayers.getBounds();
  el('fit').disabled = false;
  map.invalidateSize();
  if (!map.hasLayer(tiles)) {
    tiles.addTo(map);
    document.querySelector('.map-credit').hidden = false;
  }
  if (!sameRoute) fit();
  displayedRoute = { route_id: route.route_id, revision: route.revision };
}

async function fetchRouteUpdate(current) {
  const result = await app.callServerTool({
    name: 'get_route_view',
    arguments: { route_id: current.route_id, after_revision: current.revision },
  });
  if (closed || current !== displayedRoute) return;
  if (result.isError || !result.structuredContent) throw new Error('Route refresh failed.');
  const next = result.structuredContent.route;
  if (next) {
    if (next.route_id !== current.route_id) throw new Error('Route refresh returned a different route.');
    render(next);
  }
  refreshFailures = 0;
  routeMessage.hidden = true;
}

async function refreshRoute() {
  const current = displayedRoute;
  try {
    if (!document.hidden && current?.route_id) await fetchRouteUpdate(current);
  } catch {
    if (!closed && current === displayedRoute && ++refreshFailures === 2) {
      routeMessage.textContent = 'The displayed route may be out of date.';
      routeMessage.hidden = false;
    }
  } finally {
    if (!closed) refreshTimer = setTimeout(refreshRoute, 2000);
  }
}

// Install handlers before connect: hosts can immediately send the initial result.
app.ontoolresult = (result) => {
  try {
    if (result.isError) throw new Error(result.content?.find(c => c.type === 'text')?.text || 'Could not display the route.');
    render(result.structuredContent?.route);
    refreshFailures = 0;
    routeMessage.hidden = true;
  } catch (error) {
    routeMessage.textContent = error.message;
    routeMessage.hidden = false;
  }
};
function applyHostContext(context) {
  if (!context) return;
  if (context.theme) document.documentElement.style.colorScheme = context.theme;
  const fullscreen = context.displayMode === 'fullscreen';
  if (context.displayMode && main.classList.contains('fullscreen') !== fullscreen) {
    main.classList.toggle('fullscreen', fullscreen);
    preferredHeight = undefined;
    reportPreferredHeight();
  }
}
app.onhostcontextchanged = applyHostContext;
app.onteardown = async () => {
  closed = true;
  clearTimeout(refreshTimer);
  disablePointerZoom();
  observer.disconnect();
  map.remove();
  return {};
};
const observer = new ResizeObserver(() => {
  map.invalidateSize();
  reportPreferredHeight();
});
observer.observe(el('map'));
observer.observe(header);
app.connect().then(() => {
  connected = true;
  applyHostContext(app.getHostContext());
  reportPreferredHeight();
  if (!closed) refreshTimer = setTimeout(refreshRoute, 2000);
}).catch(() => {
  routeMessage.textContent = 'Open this view through show_route in a host that supports MCP Apps.';
  routeMessage.hidden = false;
});
