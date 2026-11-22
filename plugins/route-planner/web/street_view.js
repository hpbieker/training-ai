let libraryPromise;

function loadStreetView(key) {
  if (globalThis.google?.maps?.importLibrary) {
    return google.maps.importLibrary('streetView');
  }
  if (!libraryPromise) {
    libraryPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      const fail = () => {
        clearTimeout(timeout);
        script.remove();
        reject(new Error('Could not load Google Street View.'));
      };
      const timeout = setTimeout(fail, 12000);
      // Google's loader calls these globals after loading or an auth error.
      globalThis.gm_authFailure = fail;
      globalThis.routePlannerMapsReady = () => {
        google.maps.importLibrary('streetView').then(library => {
          clearTimeout(timeout);
          resolve(library);
        }, fail);
      };
      script.async = true;
      script.referrerPolicy = 'strict-origin-when-cross-origin';
      script.src = 'https://maps.googleapis.com/maps/api/js?' + new URLSearchParams({
        key, loading: 'async', callback: 'routePlannerMapsReady', auth_referrer_policy: 'origin',
      });
      script.onerror = fail;
      document.head.append(script);
    }).catch(error => {
      libraryPromise = undefined;
      throw error;
    });
  }
  return libraryPromise;
}

export async function findStreetView(key, { lat, lng }, signal) {
  const { StreetViewService, StreetViewPreference } = await loadStreetView(key);
  signal.throwIfAborted();
  const service = new StreetViewService();
  return new Promise((resolve, reject) => {
    const unavailable = new Error('Could not check Street View coverage.');
    const fail = () => {
      clearTimeout(timeout);
      reject(unavailable);
    };
    const timeout = setTimeout(fail, 12000);
    service.getPanorama({
      location: { lat, lng }, radius: 50, preference: StreetViewPreference.NEAREST,
    }, (data, status) => {
      clearTimeout(timeout);
      if (status === 'ZERO_RESULTS') resolve(null);
      else if (status === 'OK' && data?.location?.pano) resolve(data.location);
      else fail();
    }).catch(fail);
  });
}

function streetViewHeading(panorama) {
  const photographer = panorama.getPhotographerPov()?.heading;
  const directions = (panorama.getLinks() ?? []).map(link => link.heading).filter(Number.isFinite);
  if (!directions.length) return photographer;
  if (!Number.isFinite(photographer)) return directions[0];
  const difference = heading => Math.abs((heading - photographer + 540) % 360 - 180);
  return directions.reduce((best, heading) => difference(heading) < difference(best) ? heading : best);
}

export async function showLiveStreetView(container, key, pano, routeHeading, signal, onView, onUnavailable) {
  const { StreetViewPanorama } = await loadStreetView(key);
  if (signal.aborted) return;

  const panorama = new StreetViewPanorama(container, {
    addressControl: false, enableCloseButton: false, fullscreenControl: false,
    motionTracking: false, motionTrackingControl: false, panControl: false,
    zoomControl: false, visible: false,
  });
  let ready = false;
  let initialized = false;
  function report() {
    if (!ready || signal.aborted) return;
    const location = panorama.getLocation();
    // Navigation can announce the new pano before its location is available.
    if (!location?.latLng || location.pano !== panorama.getPano()) return;
    if (!initialized) {
      initialized = true;
      const heading = routeHeading ?? streetViewHeading(panorama);
      if (Number.isFinite(heading)) panorama.setPov({ heading, pitch: 0 });
    }
    const heading = panorama.getPov()?.heading;
    onView(location.latLng.toJSON(), heading);
  }
  const timeout = setTimeout(onUnavailable, 12000);
  const listeners = [
    panorama.addListener('pov_changed', report),
    panorama.addListener('pano_changed', report),
    panorama.addListener('position_changed', report),
    panorama.addListener('links_changed', report),
    panorama.addListener('status_changed', () => {
      clearTimeout(timeout);
      if (panorama.getStatus() !== 'OK') {
        onUnavailable();
        return;
      }
      ready = true;
      report();
    }),
  ];
  const resize = new ResizeObserver(() => google.maps.event.trigger(panorama, 'resize'));
  resize.observe(container);
  signal.addEventListener('abort', () => {
    clearTimeout(timeout);
    resize.disconnect();
    for (const listener of listeners) listener.remove();
    panorama.setVisible(false);
    container.replaceChildren();
  }, { once: true });
  panorama.setPano(pano);
  if (!signal.aborted) panorama.setVisible(true);
}
