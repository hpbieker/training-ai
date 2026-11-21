import L from 'leaflet';

export function routeHeadingAt(map, segments, location) {
  const target = map.project(location);
  let nearest;
  let nearestDistance = Infinity;
  for (const line of segments) {
    if (line.length < 2) continue;
    let previous = map.project(line[0]);
    for (let i = 1; i < line.length; i += 1) {
      const next = map.project(line[i]);
      if (!previous.equals(next)) {
        const point = L.LineUtil.closestPointOnSegment(target, previous, next);
        const distance = target.distanceTo(point);
        if (distance < nearestDistance) {
          nearest = { point, from: line[i - 1], to: line[i] };
          nearestDistance = distance;
        }
      }
      previous = next;
    }
  }
  if (!nearest || map.distance(location, map.unproject(nearest.point)) > 25) return undefined;

  const radians = Math.PI / 180;
  const startLat = nearest.from[0] * radians;
  const endLat = nearest.to[0] * radians;
  const longitudeChange = (nearest.to[1] - nearest.from[1]) * radians;
  const east = Math.sin(longitudeChange) * Math.cos(endLat);
  const north = Math.cos(startLat) * Math.sin(endLat)
    - Math.sin(startLat) * Math.cos(endLat) * Math.cos(longitudeChange);
  return (Math.atan2(east, north) / radians + 360) % 360;
}
