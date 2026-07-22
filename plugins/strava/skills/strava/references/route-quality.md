# Cycling Route Quality

Use these rules only when the caller requests steady road pacing or similar
constraints. Caller-provided surface preferences remain authoritative.

## Surface And Legality

- Reject known dirt, gravel, ground, or unpaved segments for a road-only route.
- Treat unknown surface as unresolved rather than silently paved.
- In Strava `surfaceTypeOffsets`, inspect both `Unknown` and `Unpaved`.
- Motorway and cycling-prohibited trunk candidates are invalid even when a
  car-oriented router reports fewer cycleways.
- A named bike or `Paved` preference does not prove the actual route surface.

## Pacing Interruptions

- Penalize footway, path, and pedestrian segments heavily.
- Penalize cycleways when crossings, driveways, pedestrians, blind turns, or
  shared use make steady pacing unlikely.
- Treat `foot=designated` on a cycleway/path/footway as a shared-flow warning,
  even when the surface is paved.
- Penalize uncontrolled crossings, traffic lights, barriers, kerbs, traffic
  calming, and ambiguous priority because they create stop/start load.
- Penalize fast major roads without adequate cycling access or shoulder.
- Smooth climbs can be suitable when they preserve flow and have few crossings.

## Evaluation

Use Strava's generated polyline as the route under review. Map-match or inspect
that geometry against OSM rather than judging the straight lines between
waypoints.

`score_brouter_vt1.py` is decision support, not a final verdict. Review route
class mix, unknown/unpaved distance, crossings, legality, and suspicious
connectors before accepting a candidate.
