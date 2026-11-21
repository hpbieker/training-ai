import { App } from '@modelcontextprotocol/ext-apps';
import L from 'leaflet';
import { enablePointerZoom } from './wheel_zoom.js';
import { routeHeadingAt } from './route_heading.js';
const el = (id) => document.getElementById(id);
const app = new App({ name: 'Route Planner', version: '0.2.14' }, {}, { autoResize: false });
const header = document.querySelector('header');
const main = document.querySelector('main');
const mapWrap = document.querySelector('.map-wrap');
const expandButton = el('expand');
const routeMessage = el('route-message');
const tileMessage = el('tile-message');
const mapElement = el('map');
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
const DRAG_PASSAGE_TOLERANCE_PX = 2;
let routeDrag;

function beginRouteDrag(event) {
  const route = displayedRoute;
  if (!event.isPrimary || event.button !== 0 || event.shiftKey || event.altKey || event.metaKey
      || event.ctrlKey || routeDrag || !route?.waypointTrackIndices
      || !event.target.closest('.route-drag-target')) return;

  const origin = map.mouseEventToContainerPoint(event);
  const line = route.segments[0];
  let previous = map.latLngToContainerPoint(line[0]);
  const legDistances = Array(route.waypointIds.length + 1).fill(Infinity);
  let leg = 0;
  for (let i = 1; i < line.length; i += 1) {
    if (route.waypointTrackIndices[leg] === i - 1) leg += 1;
    const next = map.latLngToContainerPoint(line[i]);
    const distance = L.LineUtil.pointToSegmentDistance(origin, previous, next);
    legDistances[leg] = Math.min(legDistances[leg], distance);
    previous = next;
  }
  const limit = Math.min(...legDistances) + DRAG_PASSAGE_TOLERANCE_PX;
  const legs = legDistances.flatMap((distance, index) => distance <= limit ? [index] : []);
  routeDrag = { route, origin, legs, pointerId: event.pointerId };
  event.preventDefault();
  event.stopPropagation();
  mapElement.setPointerCapture(event.pointerId);
}

function moveRouteDrag(event) {
  if (routeDrag?.pointerId !== event.pointerId) return;
  if (routeDrag.marker) {
    routeDrag.marker.setLatLng(map.mouseEventToLatLng(event));
  } else if (routeDrag.origin.distanceTo(map.mouseEventToContainerPoint(event)) >= 4) {
    map.closePopup();
    mapElement.classList.add('dragging-route');
    routeDrag.marker = L.circleMarker(map.mouseEventToLatLng(event), {
      radius: 7, color: 'white', weight: 2, fillColor: ROUTE_BLUE, fillOpacity: 1, interactive: false,
    }).addTo(routeLayers);
  }
}

function endRouteDrag() {
  const drag = routeDrag;
  if (!drag) return;
  routeDrag = undefined;
  mapElement.classList.remove('dragging-route');
  if (mapElement.hasPointerCapture(drag.pointerId)) mapElement.releasePointerCapture(drag.pointerId);
  return drag;
}

function cancelRouteDrag(event) {
  if (event && routeDrag?.pointerId !== event.pointerId) return;
  endRouteDrag()?.marker?.removeFrom(routeLayers);
}

async function dropRouteDrag(event) {
  if (routeDrag?.pointerId !== event.pointerId) return;
  const { route, legs, marker } = endRouteDrag();
  if (!marker) return;
  const drop = map.mouseEventToContainerPoint(event);
  if (closed || route !== displayedRoute || !L.bounds([0, 0], map.getSize()).contains(drop)) {
    routeLayers.removeLayer(marker);
    return;
  }
  const position = map.containerPointToLatLng(drop).wrap();
  marker.setLatLng(position);
  if (legs.length === 1) {
    await saveDraggedWaypoint(route, position, legs[0], marker);
    return;
  }
  const content = document.createElement('div');
  const title = document.createElement('h2');
  title.textContent = 'Choose route section';
  content.append(title);
  const popup = L.popup({ className: 'waypoint-popup route-section-popup', closeOnClick: false })
    .setLatLng(position).setContent(content);
  let selected = false;
  popup.on('remove', () => {
    if (!selected) routeLayers.removeLayer(marker);
  });
  for (const leg of legs) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'waypoint-action';
    const from = leg === 0 ? 'Start' : `Waypoint #${leg}`;
    const to = leg === route.waypointIds.length ? 'Finish' : `Waypoint #${leg + 1}`;
    button.textContent = `${from} → ${to}`;
    button.addEventListener('click', () => {
      selected = true;
      map.closePopup(popup);
      void saveDraggedWaypoint(route, position, leg, marker);
    });
    content.append(button);
  }
  popup.openOn(map);
}

async function saveDraggedWaypoint(route, { lat, lng: lon }, leg, marker) {
  try {
    if (closed || route !== displayedRoute) return;
    await updateWaypoint(route, {
      add_waypoint: { lat, lon, after_waypoint_id: route.waypointIds[leg - 1], snap_to_route: true },
    });
    await refreshEditedRoute(route);
  } catch {
    // A failed drop leaves the saved route as it was.
  } finally {
    routeLayers.removeLayer(marker);
  }
}

mapElement.addEventListener('pointerdown', beginRouteDrag, { capture: true });
mapElement.addEventListener('pointermove', moveRouteDrag);
mapElement.addEventListener('pointerup', dropRouteDrag);
mapElement.addEventListener('pointercancel', cancelRouteDrag);
mapElement.addEventListener('lostpointercapture', cancelRouteDrag);

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

function addWaypoint(point, order, route) {
  const label = `Waypoint #${point.index}`;
  const waypointId = route.route_id && Number.isInteger(route.revision) ? point.waypoint_id : undefined;
  const position = L.latLng(point.on_route.lat, point.on_route.lon);
  const number = document.createElement('span');
  number.textContent = String(point.index);
  const marker = L.marker(position, {
    icon: L.divIcon({className: 'route-waypoint', html: number, iconSize: POINT_ICON_SIZE}),
    draggable: Boolean(waypointId),
    zIndexOffset: -order * WAYPOINT_STACK_STEP,
  });
  marker.on('add', () => marker.getElement().setAttribute('aria-label', label)).addTo(routeLayers);
  let popup;
  marker.bindPopup(() => popup ??= waypointPopup(marker, label, waypointId, route), { className: 'waypoint-popup' });
  if (!waypointId) return;
  let saving = false;
  marker.on('dragend', async () => {
    const current = displayedRoute;
    if (saving || closed || !routeLayers.hasLayer(marker) || current?.route_id !== route.route_id
        || current.revision !== route.revision) return;
    const { lat, lng: lon } = marker.getLatLng().wrap();
    if (position.equals([lat, lon], 0)) return;
    saving = true;
    marker.getElement().inert = true;
    try {
      await updateWaypoint(route, { move_waypoint: { waypoint_id: waypointId, lat, lon, snap_to_route: true } });
    } catch {
      if (!closed && current === displayedRoute) {
        marker.setLatLng(position);
        if (marker.getElement()) marker.getElement().inert = false;
        saving = false;
      }
      return;
    }
    await refreshEditedRoute(route);
  });
}

async function updateWaypoint(route, change) {
  const result = await app.callServerTool({
    name: 'update_route',
    arguments: { route_id: route.route_id, expected_revision: route.revision, ...change },
  });
  if (result.isError) {
    throw new Error(result.content?.find(item => item.type === 'text')?.text || 'Could not update the route.');
  }
  if (result.structuredContent?.route_id !== route.route_id
      || !(result.structuredContent.revision > route.revision)) {
    throw new Error('Could not confirm the route update.');
  }
}

async function refreshEditedRoute(route) {
  const current = displayedRoute;
  if (closed || current?.route_id !== route.route_id || current.revision !== route.revision) return;
  try {
    await fetchRouteUpdate(current);
  } catch {
    // The regular route refresh retries if the update has already been saved.
  }
}

function waypointPopup(marker, label, waypointId, route) {
  const content = document.createElement('div');
  const title = document.createElement('h2');
  title.textContent = label;
  content.append(title);
  if (waypointId) {
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'waypoint-action';
    remove.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
      <path d="M4 7h16M9 7V4h6v3m3 0-1 13H7L6 7m4 3v7m4-7v7"/>
    </svg>Remove waypoint`;
    const status = document.createElement('p');
    status.className = 'waypoint-remove-status';
    status.setAttribute('role', 'status');
    status.hidden = true;
    remove.addEventListener('click', async () => {
      remove.disabled = true;
      status.hidden = true;
      try {
        await updateWaypoint(route, { remove_waypoint_id: waypointId });
      } catch (error) {
        status.textContent = error.message;
        status.hidden = false;
        remove.disabled = false;
        return;
      }
      marker.closePopup();
      await refreshEditedRoute(route);
    });
    content.append(remove, status);
  }
  return content;
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
const streetViewPanel = el('street-view-panel');
const streetViewFrame = el('street-view-frame');
const streetViewClose = el('street-view-close');
const streetViewStatus = el('street-view-status');
let streetViewEmbedKey;
let previousMapView;
let streetViewMarker;

function setStreetViewStatus(text) {
  streetViewStatus.textContent = text;
  streetViewStatus.hidden = !text;
}

function enterStreetView(latlng) {
  setStreetViewStatus('');
  map.closePopup();
  previousMapView = { center: map.getCenter(), zoom: map.getZoom() };
  streetViewPanel.hidden = false;
  map.stop();
  mapElement.classList.remove('selecting-street-view');
  mapElement.inert = true;
  mapWrap.classList.add('street-view-active');
  map.invalidateSize({ pan: false, animate: false });
  map.setView(latlng, 16, { animate: false });
  streetViewMarker = L.marker(latlng, {
    icon: L.divIcon({ className: 'street-view-position', iconSize: [16, 16] }),
    interactive: false, keyboard: false, zIndexOffset: 1000,
  }).addTo(map);
  streetViewPanel.focus({ preventScroll: true });
}

function openStreetView(latlng, viewpoint) {
  if (!streetViewEmbedKey) {
    setStreetViewStatus('Street View is missing its Google Maps Embed API key.');
    return;
  }
  enterStreetView(latlng);
  const query = new URLSearchParams({
    key: streetViewEmbedKey, location: viewpoint,
  });
  const heading = routeHeadingAt(map, displayedRoute.segments, latlng);
  if (Number.isFinite(heading)) query.set('heading', String(heading));
  streetViewFrame.src = 'https://www.google.com/maps/embed/v1/streetview?' + query;
}

function closeStreetView() {
  if (!previousMapView) return;
  map.closePopup();
  streetViewPanel.hidden = true;
  streetViewFrame.removeAttribute('src');
  streetViewMarker.remove();
  streetViewMarker = undefined;
  mapWrap.classList.remove('street-view-active');
  mapElement.inert = false;
  map.invalidateSize({ pan: false, animate: false });
  map.setView(previousMapView.center, previousMapView.zoom, { animate: false });
  previousMapView = undefined;
  mapElement.focus({ preventScroll: true });
}

function isStreetViewShortcut(event) {
  return displayedRoute && streetViewPanel.hidden && event.shiftKey
    && !event.altKey && !event.ctrlKey && !event.metaKey;
}

map.on('click', ({ latlng, originalEvent }) => {
  if (!isStreetViewShortcut(originalEvent)) return;
  const viewpoint = `${latlng.lat.toFixed(6)},${latlng.lng.toFixed(6)}`;
  openStreetView(latlng, viewpoint);
});

map.on('movestart', () => {
  if (!streetViewPanel.hidden) return;
  setStreetViewStatus('');
});

function updateStreetViewCursor(event) {
  const selecting = Boolean(isStreetViewShortcut(event) && !event.buttons);
  mapElement.classList.toggle('selecting-street-view', selecting);
}

function resetStreetViewCursor() {
  mapElement.classList.remove('selecting-street-view');
}

document.addEventListener('keydown', updateStreetViewCursor);
document.addEventListener('keyup', updateStreetViewCursor);
mapElement.addEventListener('pointerenter', updateStreetViewCursor);
mapElement.addEventListener('pointermove', updateStreetViewCursor);
mapElement.addEventListener('pointerleave', resetStreetViewCursor);
window.addEventListener('blur', resetStreetViewCursor);
streetViewClose.addEventListener('click', closeStreetView);

document.addEventListener('keydown', event => {
  if (event.defaultPrevented || event.repeat || event.ctrlKey || event.metaKey || event.altKey
      || event.target?.closest?.('input, textarea, select, [contenteditable]')) return;
  if (event.key.toLowerCase() === 'm' && displayedRoute && streetViewPanel.hidden) {
    event.preventDefault();
    cancelRouteDrag();
    hidingWithKey = true;
    routeLayers.remove();
    mapWrap.classList.add('route-hidden');
    map.closePopup();
  }
  if (event.key === 'Escape' && !streetViewPanel.hidden) closeStreetView();
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
  cancelRouteDrag();
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
  const waypointIds = (route.points ?? []).filter(point => point.role === 'waypoint').map(point => point.waypoint_id);
  const trackIndices = route.waypoint_track_indices;
  const canAddWaypoint = route.route_id && Number.isInteger(route.revision) && segments.length === 1
    && waypointIds.length < 500 && waypointIds.every(Boolean) && trackIndices?.length === waypointIds.length;
  if (canAddWaypoint) {
    L.polyline(segments, { weight: 14, opacity: 0, smoothFactor: 0, className: 'route-drag-target' }).addTo(routeLayers);
  }
  const start = segments[0][0], end = segments.at(-1).at(-1);
  endpoint(start, 'A', 'Start', 0);
  let order = 1;
  for (const point of route.points ?? []) {
    if (point.role === 'waypoint') addWaypoint(point, order++, route);
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
  displayedRoute = {
    route_id: route.route_id, revision: route.revision, segments, waypointIds,
    waypointTrackIndices: canAddWaypoint ? trackIndices : undefined,
  };
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
    closeStreetView();
    streetViewEmbedKey = result._meta?.street_view_embed_key;
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
  cancelRouteDrag();
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
