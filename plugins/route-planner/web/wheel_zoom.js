import L from 'leaflet';

export function enablePointerZoom(map) {
  const container = map.getContainer();
  let anchor, pointer, targetZoom, frame, idleTimer;
  let zooming = false;

  function render() {
    frame = undefined;
    if (targetZoom === map.getZoom()) return;
    const offset = pointer.subtract(map.getSize().divideBy(2));
    const center = map.unproject(map.project(anchor, targetZoom).subtract(offset), targetZoom);
    // Use Leaflet's pinch path to retain existing tiles while the tile layer
    // loads each new integer level crossed during the gesture.
    if (!zooming) {
      map._moveStart(true);
      zooming = true;
    }
    map._move(center, targetZoom, { pinch: true });
  }

  function finish() {
    clearTimeout(idleTimer);
    if (frame !== undefined) {
      cancelAnimationFrame(frame);
      render();
    }
    if (zooming) {
      map.fire('zoom');
      map._moveEnd(true);
      zooming = false;
    }
    anchor = undefined;
  }

  function wheel(event) {
    if (!Number.isFinite(map.getZoom())) return;
    const delta = L.DomEvent.getWheelDelta(event);
    if (!delta) return;
    event.preventDefault();
    event.stopPropagation();

    const position = map.mouseEventToContainerPoint(event);
    if (!anchor || !position.equals(pointer)) {
      finish();
      map.stop();
      pointer = position;
      anchor = map.containerPointToLatLng(pointer);
      targetZoom = map.getZoom();
    }
    const change = Math.max(-1, Math.min(1, delta / map.options.wheelPxPerZoomLevel));
    targetZoom = Math.max(map.getMinZoom(), Math.min(map.getMaxZoom(), targetZoom + change));
    if (frame === undefined) frame = requestAnimationFrame(render);
    clearTimeout(idleTimer);
    idleTimer = setTimeout(finish, 150);
  }

  container.addEventListener('wheel', wheel, { passive: false });
  container.addEventListener('pointerdown', finish, true);
  map.on('resize', finish);
  return () => {
    clearTimeout(idleTimer);
    if (frame !== undefined) cancelAnimationFrame(frame);
    container.removeEventListener('wheel', wheel);
    container.removeEventListener('pointerdown', finish, true);
    map.off('resize', finish);
  };
}
