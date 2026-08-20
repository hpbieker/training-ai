# Config

This directory contains agent-readable context and helper/runtime config.

## Agent Context

- `practical-context.md`: locations, modalities, equipment, sensors, and route context.
- `coaching-preferences.md`: planning, workout, calendar, fueling, and presentation preferences.
- `cycling-clothing.md`: wardrobe context for outdoor recommendations.
- `plans/`: date-stamped medium-term training plans.

## Helper/Runtime Config

- `plan-state.json`: authoritative current plan progression and next role.
- `route-data-quality.json`: route data-quality registry.
- `sensor-data-quality.json`: sensor data-quality registry.

## Rule

Helpers must not read the Markdown context files directly. The agent passes
needed values through explicit arguments or normalized inputs. Date temporary
context and remove or revise it when it expires.
