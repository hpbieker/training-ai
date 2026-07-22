# Cycling Clothing

This file is LLM/agent-readable wardrobe context for outdoor ride clothing
recommendations. Helper scripts must not import, parse, or read this file
directly.

## Source Notes

- Usage: practical wardrobe reference for outdoor ride clothing recommendations.
- Temperature ranges: Castelli temperature ranges are manufacturer ranges, not
  personal rules. Adjust for ride intensity, wind, rain, sun, route exposure,
  stop risk, and personal tolerance.
- Manufacturer ranges checked on: `2026-05-22`.
- Model confidence: exact current product pages were not found for the user's
  Climber jersey, blue vest, winter jacket, Slicker rain jacket, or
  Thermoflex/Termoflex leg warmer. Keep those as practical estimates until exact
  model names are known.

## Items

### Race Bib Shorts

- Id: `castelli_free_aero_bib_shorts`.
- Brand: Castelli.
- Model/status: Free Aero RC / Free Aero Race style bib shorts.
- Category: bib shorts.
- Model confidence: style verified.
- Manufacturer temperature range: `15-35 C`.
- Practical use: default for mild and warm rides. Add knee/leg warmers only
  when the start, rain, wind, or long descents justify it.

### Short-Sleeve Race Jersey

- Id: `castelli_aero_race_short_sleeve_jersey`.
- Brand: Castelli.
- Model/status: Aero Race short-sleeve style jersey.
- Category: short-sleeve jersey.
- Model confidence: style verified.
- Manufacturer temperature range: `18-35 C`.
- Practical use: default warm-weather jersey. For `15-18 C`, pair with a light
  base layer or vest instead of jumping straight to a jacket.

### Castelli Climber Jersey

- Id: `castelli_climber_jersey`.
- Brand: Castelli.
- Model/status: exact current model not verified.
- Category: light/hot-weather jersey.
- Model confidence: unverified.
- Manufacturer temperature range: not verified.
- Practical use: treat as a light/hot-weather jersey. Best when overheating is
  the bigger risk than wind chill.

### Castelli Pro Light Wind Vest

- Id: `castelli_pro_light_wind_vest`.
- Brand: Castelli.
- Model/status: Pro Light Wind Vest.
- Category: wind vest.
- Model confidence: verified.
- Manufacturer temperature range: `12-20 C`.
- Practical use: first-choice pocket layer for mild starts, descents, and
  coastal wind. Light front wind block, breathable back, low overheating risk.

### Castelli Blue Vest

- Id: `castelli_blue_vest`.
- Brand: Castelli.
- Model/status: exact model not verified.
- Category: vest.
- Model confidence: unverified.
- Manufacturer temperature range: not verified.
- Practical use: use like a light vest if it is a thin wind shell. If it is
  insulated, move it colder.

### Castelli Perfetto

- Id: `castelli_perfetto`.
- Brand: Castelli.
- Model/status: Perfetto RoS Long Sleeve style.
- Category: long-sleeve weather jersey.
- Model confidence: style verified.
- Manufacturer temperature range: `4-14 C`.
- Practical use: too warm as the main piece for steady riding above roughly
  `15-16 C` unless wet/windy or low intensity. Best for cool, windy, or damp
  rides.

### Castelli Winter Jacket

- Id: `castelli_winter_jacket`.
- Brand: Castelli.
- Model/status: exact model not verified.
- Category: winter jacket.
- Model confidence: unverified.
- Manufacturer temperature range: unknown, likely colder than Perfetto.
- Practical use: use only for genuinely cold rides. Need exact model name before
  giving precise temperature guidance.

### Castelli Emergency Rain Jacket

- Id: `castelli_emergency_rain_jacket`.
- Brand: Castelli.
- Model/status: Emergency 2/3 Rain Jacket.
- Category: rain shell.
- Model confidence: style verified.
- Manufacturer temperature range: `5-18 C`
  (`Emergency 3`: `5-18 C`; `Emergency 2`: `6-18 C`).
- Practical use: rain shell, not a normal dry-weather layer. Carry for rain or
  long exposed routes; expect it to feel warm if ridden hard in dry mild weather.

### Castelli Slicker Rain Jacket

- Id: `castelli_slicker_rain_jacket`.
- Brand: Castelli.
- Model/status: exact model not found in current Castelli search.
- Category: rain shell.
- Model confidence: unverified.
- Manufacturer temperature range: unknown.
- Practical use: treat as a rain shell until exact model is known. Likely for
  wet conditions, not routine dry layering.

### Castelli Prosecco Tech Short Sleeve

- Id: `castelli_prosecco_tech_short_sleeve_base_layer`.
- Brand: Castelli.
- Model/status: Prosecco Tech Short Sleeve base layer.
- Category: short-sleeve base layer.
- Model confidence: verified.
- Manufacturer temperature range: `10-20 C`.
- Practical use: warm/wicking cool-weather base layer. Can be too warm for mild
  high-output rides, especially under windproof layers.

### Castelli Thermoflex Kneewarmer

- Id: `castelli_thermoflex_knee_warmer`.
- Brand: Castelli.
- Model/status: Thermoflex 2 Knee Warmer.
- Category: knee warmer.
- Model confidence: style verified.
- Manufacturer temperature range: `8-20 C`.
- Practical use: dry-condition knee warmth. Useful for cool starts or long
  steady rides around `10-16 C`; can be unnecessary around `17-20 C` if
  intensity is steady.

### Castelli Termoflex Legwarmer

- Id: `castelli_thermoflex_legwarmer`.
- Brand: Castelli.
- Model/status: Thermoflex 2 Legwarmer.
- Category: leg warmer.
- Model confidence: style unverified.
- Manufacturer temperature range: no product-page range found; assume warmer
  than knee warmers.
- Practical use: use when full-leg warmth is needed. Usually too much for mild
  `17-20 C` rides unless rain, wind, or low intensity.

## Selection Rules

### Dry, 18-25 C

- Default kit:
  - `castelli_free_aero_bib_shorts`
  - `castelli_aero_race_short_sleeve_jersey`
- Notes: use light gloves. Vest only if wind, descents, or stops justify it.

### Dry, 15-20 C, Variable Or Coastal Exposure

- Default kit:
  - `castelli_free_aero_bib_shorts`
  - `castelli_aero_race_short_sleeve_jersey`
  - `castelli_pro_light_wind_vest`
- Notes: light vest in pocket or on at start. Consider knee warmers if knees get
  cold.

### Dry, 10-16 C

- Default kit:
  - `castelli_free_aero_bib_shorts`
  - `castelli_thermoflex_knee_warmer`
  - `castelli_prosecco_tech_short_sleeve_base_layer`
- Notes: use vest or Perfetto depending on wind and intensity; leg warmers if
  full-leg warmth is needed.

### Windy Or Damp, 5-14 C

- Default kit:
  - `castelli_perfetto`
- Notes: Perfetto territory. Add warmer base layer and consider full leg
  coverage.

### Rain Risk

- Default kit:
  - `castelli_emergency_rain_jacket`
- Alternate items:
  - `castelli_slicker_rain_jacket`
- Notes: carry a rain shell. Wear only when rain/wind makes it worth the heat
  cost.

## Example Contexts

### Oslo/Fjällbacka-Type Ride

- Conditions: route starting mild around `17 C`, warming near `19-20 C`, then
  cooling to `15-16 C` on the coast.
- Reasonable baseline:
  - `castelli_free_aero_bib_shorts`
  - `castelli_aero_race_short_sleeve_jersey`
  - `castelli_pro_light_wind_vest`
- Optional:
  - Light base layer or no base layer, depending start comfort.
  - Knee warmers only if cool knees are a known issue.
- Avoid unless forecast worsens:
  - `castelli_perfetto`
  - `castelli_winter_jacket`
  - `castelli_thermoflex_legwarmer`
  - shoe covers
