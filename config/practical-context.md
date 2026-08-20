# Practical Context

This file is LLM/agent-readable practical training context only. Helper scripts
must not import, parse, or read this file directly. When a helper needs one of
these values, the LLM/agent should translate it into explicit CLI arguments,
normalized source inputs, or chat reasoning.

## LLM Usage

- Read by: LLM/agent only.
- Not for scripts: yes.
- Runtime contract: scripts receive explicit CLI arguments or normalized source
  inputs; they do not read this file.

## Locations

### Home

- Display name: `Dagaliveien 17B, Oslo`.
- Anchor: `59.95581576954476, 10.688188956334665`.
- Indoor available: yes.
- Outdoor available: yes.

### Etnedal Cabin

- Display name: `Bjødnafallet/Etnedal`.
- Indoor available: yes.
- Outdoor available: yes.

### Fjällbacka Cabin

- Display name: `Fjällbacka hytte`.
- Anchor: `58.606514, 11.282139`.
- Indoor available: no.
- Outdoor available: yes.
- Indoor unavailable reason: `no_indoor_equipment_at_current_location`.

## Route Context

- Default start/end radius: `0.25 km`.
- Weather fallback: `Sørkedalen`, anchor `60.0189, 10.5834`.

## Equipment

- Gear id `b10577453`: `Trek Madone 9`, road/landevei.
- Gear id `b11246236`: `Trek Checkpoint`, gravel/grus.

## Sensors

- Moxy is normally used on the right vastus lateralis, with the same placement
  between sessions.
- Available activity streams may include power, heart rate, VE, VT, BR, Moxy
  SmO2/THb, core and skin temperature, and environmental temperature and
  humidity.

## Bottles and Products

- Available bottle sizes: `750 ml` and `1000 ml`.
- One seigmann: about `5-6 g carbohydrate`.
- SiS GO Electrolyte Orange reference:
  - `20 g powder per 300 ml`, scaled from verified EatMyRide entries.
  - `900 ml` registered as `60 g powder` gave `54.6 g carbohydrate` in
    EatMyRide; treat SiS as roughly `0.9 g carbohydrate per gram powder`.
