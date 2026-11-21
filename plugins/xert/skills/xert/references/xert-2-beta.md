# Xert 2.0 Beta fields

Use the [tool workflow](tool-workflows.md#xert-20-beta) to choose an entry point.
The fields below describe the MCP adapter. The vendor's beta model can change
between frontend builds.

## Inputs and result metadata

| Field | Meaning |
| --- | --- |
| `activity_path` | Completed Xert activity to analyze. The activity result echoes its path and includes its `name`, which can be null. |
| `model_source_activity_path` | Completed activity that supplies the signature, options and carbohydrate bias for an unsaved workout. The workout result echoes this path. |
| `rows` | Complete synthetic workout structure. The result's `workout_duration_s` is the number of generated one-second power samples. |
| `initial_muscle_glycogen_balance_g` | Optional workout input in grams relative to full capacity. Use a negative value for depletion, zero for full, and a positive value for a loaded state. Accepted range is −4000 to +4000 g. The runner rounds to 0.1 g and limits the magnitude to the source signature's capacity. |
| `muscle_glucose_uptake_g_per_hour` | Optional workout input for Muscle Glucose Uptake Rate (MGUR), from 0 to 400 g/h. The runner rounds to 0.1 g/h. |
| `save_series` | Defaults to false. When true, `series_file`, `series_format` and `series_byte_size` describe the private JSON export and its byte size. |
| `source`, `bundle_sha256` | `xert_2_local_wasm` and the SHA-256 of the Xert frontend JavaScript bundle used for the calculation. |
| `experimental`, `standard_xert_comparable`, `caveats` | Model status, compatibility flag and interpretation notes. Use the standard Xert tools for Training Load or recovery calculations. |
| `signature_used`, `options_used` | Signature and calculation settings returned for provenance. See below. |

Omitted inputs inherit the source activity's values. The result and the
optional series file record applied values as `signature_used.initial_gmg_balance`
and `signature_used.glut4r`. Xert's native sign is positive for depletion and
negative for a loaded state, the reverse of the MCP balance input.
Overrides apply to that calculation only.

Each workout row requires `duration_seconds` and `power` and accepts
`name` and `power_type`. Supported work types are `absolute`, `relative_ftp`,
`ramp_absolute`, `ramp_ftp` and `ramp_ltp`. Use `power_second_value` for
the ramp endpoint. Absolute power is in watts. FTP and LTP values are
percentages of the source signature's TP and LTP.

`interval_count` defaults to one. `rib_duration_seconds`, `rib_power` and
`rib_power_type` specify rest after each repetition, including the last.
Recovery supports `absolute` and `relative_ftp`. Recovery duration and power
default to zero and the default power type is absolute. Work duration must
be a positive whole number of seconds. A zero repeat count skips the row.
The resulting workout must contain samples.

## Metrics and time series

`summarize_activities_xert_2` derives aggregates from each activity's
Xert 2.0 Beta Preview time series. It returns `path`, `status` and
`xert_2` per activity. The `xert_2` object
contains `xss`, `lactate_model_mmol_l`,
`muscle_glycogen_remaining_g`, `glycogen_depleted_g`, `total_carbs_g`
and `fat_g`. An unavailable Beta result has `status="unavailable"`
and `xert_2=null`. The response includes analyzed and unavailable counts.
When all successful analyses use the same frontend build, the response gives
`bundle_sha256` once at the top level. For mixed builds, each successful
`xert_2` summary includes its own hash.
The MCP process downloads each frontend bundle URL on first use and reuses
it across Beta Preview tools. Each calculation still reads the activity preview
for its own model inputs.

The private JSON contains `series`, `bundle_sha256`, `signature_used`,
`options_used` and source context. Activity files include `activity_path`.
Workout files include `model_source_activity_path` and `workout_rows`.
The format identifier is `xert-2-model-series-v1`. All series align by
index with `elapsed_s`. Activity timing comes from the model's sample
timestamps. Synthetic workouts use one-second samples.

| Field | Meaning | Compact `metrics` |
| --- | --- | --- |
| `elapsed_s` | Elapsed sample time in seconds | — |
| `power_w` | Input power profile as returned by the model, in W | — |
| `mpa_w` | Modeled Maximum Power Available, in W | Range and endpoints |
| `dynamic_tp_w` | Modeled Threshold Power over time, in W | Range and endpoints |
| `dynamic_hie_kj` | Modeled High Intensity Energy capacity over time, in kJ | Range and endpoints |
| `lactate_model_mmol_l` | Modeled blood lactate, in mmol/L. The current conversion adds a 1.0 mmol/L baseline to the model's blood lactate energy divided by the signature's conversion factor. A legacy signature uses its legacy factor without the offset. | Range, endpoints and time at or above each threshold from 1 to 8 mmol/L |
| `muscle_glycogen_remaining_g` | Modeled muscle glycogen remaining, in g. The adapter subtracts the modeled depletion series from signature capacity. | Range and endpoints |
| `muscle_glycogen_burned_g` | Cumulative modeled muscle glycogen burned, in g | Final value |
| `muscle_glycogen_replenished_g` | Cumulative modeled replenishment of muscle glycogen, in g | Final value |
| `glucose_regeneration_w` | Modeled power associated with glucose regeneration, in W | — |
| `fat_used_for_regeneration_w` | Modeled fat energy rate associated with glucose regeneration, in W | — |

Ranges report `start`, `minimum`, `minimum_at_s`, `maximum`,
`maximum_at_s` and `end`. Lactate's `duration_at_or_above_s` is
time-weighted using model timestamps. The last sample is assigned the same
duration as the preceding sample interval. `xss` reports 2.0 model strain
as `total`, `low`, `high` and `peak`.

## Substrate and energy totals

All gram values are model estimates. Use food logs to establish intake.
Muscle Glucose Uptake Rate (MGUR) describes modeled uptake by muscle.
[Xert's explanation](https://forum.xertonline.com/t/2-0-beta/49605?page=4)

| Field under `substrates_and_energy` | Meaning |
| --- | --- |
| `total_carbs_g`, `fat_g` | Total modeled carbohydrate and fat use, in g. |
| `calories_kcal` | Mechanical work divided by gross efficiency and converted to kcal. |
| `glycogen.burned_g` | Total modeled muscle glycogen burned, in g. |
| `glycogen.depleted_g` | Net muscle glycogen depletion reported by the model, in g. The fallback subtracts the final remaining glycogen from the starting value. |
| `glycogen.replenished_g` | Modeled muscle glycogen replenished, in g. |
| `glucose.used_g` | Total carbohydrate use minus net glycogen depletion, in g. |
| `glucose.burned_g` | Glucose burned directly according to the model, in g. The fallback subtracts glycogen burned from total carbohydrate use. |
| `carb_to_fat_ratio` | Carbohydrate grams divided by fat grams. Null when fat usage is zero. |
| `additional_energy.regenerated_glucose_g` | Modeled glucose regenerated, in g. Includes the adapter's assumption that residual blood lactate is converted after the session. |
| `additional_energy.fat_used_for_regeneration_g` | Modeled fat cost of glucose regeneration, in g. |

## Workout interval summaries

`intervals` contains one item per work repetition of a synthetic workout.
`row_index` is zero-based, `repetition` is one-based within that row and
`name` is the row label. `start_s` is inclusive, `end_s` is exclusive
and `duration_s` counts one-second samples. `power_w` contains
`average`, `minimum` and `maximum` in watts.

`lactate_model_mmol_l` and `muscle_glycogen.remaining_g` use the same
range fields as the compact metrics and include `delta` (end minus start).
`muscle_glycogen.burned_g` and `muscle_glycogen.replenished_g` are changes
in the cumulative values between the first and last samples in the interval.

When the row specifies recovery, `recovery` contains its own `start_s`,
`end_s`, `duration_s`, `lactate_model_mmol_l` and `muscle_glycogen`
in the same format. Its `power_w` is a single recovery target in watts.
For interval MPA, TP or HIE, select the corresponding samples from the
saved time series.

## Signature and settings

`signature_used` is an open Xert object. It combines the source signature,
the adapter's rounded or derived inputs, and the signature returned by WASM.
Where a field occurs in both, the WASM value takes precedence. The adapter
does not fit a new signature. Keys may vary by build or activity. This list
covers the keys observed in a live activity on 20 November 2026.

| Key | Meaning |
| --- | --- |
| `ftp`, `ltp`, `pp` | Threshold Power, Lower Threshold Power and Peak Power, in W. |
| `atc`, `hie` | Anaerobic capacity in J and the corresponding High Intensity Energy in kJ at model input. |
| `mgc`, `initial_gmg_balance` | Muscle glycogen capacity and the signed starting depletion relative to that capacity, in g. A positive native value means depleted and a negative one means loaded. |
| `glut4r`, `gross_eff` | Muscle Glucose Uptake Rate in g/h and gross efficiency as a fraction. |
| `amgf`, `carb_bias` | Model inputs for the aerobic fraction of glycogen use and the account's carbohydrate-use bias. |
| `active_muscle_kg_per_kg`, `blood_tank_l_per_kg` | Model scaling in kg of active muscle per kg and L of blood compartment per kg. |
| `blood_lactate_j_per_mmol`, `lt1_mmol` | Model factor used to convert blood lactate energy to concentration, and the model's LT1 lactate setting in mmol/L. |
| `muscle_lactate_oxidation_tau_s`, `muscle_blood_exchange_tau_s`, `nonworking_tissue_clearance_tau_s` | Time constants in seconds for muscle lactate oxidation, muscle–blood exchange and clearance through nonworking tissue. |
| `gng_tau_s`, `gng_max_w` | Glucose-regeneration time constant in seconds and model power cap in watts. |
| `pcrc`, `pnr`, `m` | Vendor phosphocreatine capacity and other model coefficients. The adapter derives input `pnr` as `atc / m`, using 30 if `m` is nonpositive. |
| `mass`, `one_hour_power` | Vendor mass and one-hour power fields. |
| `cpw_cp`, `cpw_wprime`, `cpw_success`, `tec_cp` | Vendor critical-power estimates, W′ and calculation status. The adapter passes through their native values. |
| `aCap`, `bga`, `cap`, `fcor`, `l`, `lcp`, `ltp0`, `mlss`, `pnp`, `roomCap`, `sLtp`, `ss`, `t1`, `v`, `version` | Other observed vendor fields. Their definitions, units and stability are unverified. |
| `l_mmol_factor` | Legacy conversion key supported by the adapter when the current blood lactate conversion factor is unavailable. |

`options_used` records the model switches and fitting settings loaded from
the activity for both tools.

| Keys | Meaning |
| --- | --- |
| `n_avg`, `pcrDelay`, `anchor_tte` | Activity chart averaging setting, vendor phosphocreatine delay, and the adapter's time-to-exhaustion anchor of 1,200 s. |
| `use_mg_depletion`, `use_mg_replenishment`, `allow_supercompensation` | Muscle glycogen depletion, replenishment and supercompensation switches. |
| `use_pcrc`, `use_nonPcr_power`, `use_lactate_fuel` | Vendor switches for the phosphocreatine component, non-phosphocreatine power and lactate as fuel. |
| `degree`, `max_param_change`, `single_param`, `min_proximity`, `params_to_fit` | Vendor fit controls passed to WASM. Their detailed contract is unverified. |
| `do_extractSig`, `debugLevel` | Signature fitting is disabled by the adapter. `debugLevel` records the vendor diagnostic setting. |

## Coverage of the beta interface

The exported glycogen, TP, HIE and MPA series cover key inputs to Xert's
**Durability Info** chart. Xert also shows a **Fitness → Chart** view with
a metabolic contribution and power curve that changes with glycogen depletion.
MCP has no equivalent curve or FatMax output. [Xert's chart explanation](https://forum.xertonline.com/t/2-0-beta/49605?page=3)

Xert lets users change the initial glycogen state and adjust model inputs
such as MGUR and gross efficiency for an activity. The workout simulator
accepts per-call overrides for start glycogen and MGUR.
The current frontend contains **Extract Signature** and controls for saving
signatures and options. The adapter performs a calculation using the loaded
signature and settings. [Xert's starting glycogen explanation](https://forum.xertonline.com/t/2-0-beta/49605?page=2)

The underlying WASM also returns carbohydrate and fat series, glucose burned,
muscle lactate and its oxidation, fatigue, HIE recharge, phosphocreatine-related
series and sample-level XSS components. MCP surfaces selected series and
session totals. The live model also returned a separate `metrics` object
with fields such as `xep`, `xds`, `t_over_mpa`, `hie_recharged_j`,
`final_tp`, `final_hie`, `post_activity_glucose_g` and
`post_activity_gng_fat_g`. The adapter currently calculates its
`additional_energy` fields from the series. Compare those results with
Xert's native fields and chart calculations before substituting native values
or promising equivalence.

Workout simulation uses local fixed or ramp power profiles. Full SMART
workout resolution and 2.0-based Forecast AI or Planner behavior have no
verified 2.0 integration here. The [public Xert API](https://www.xertonline.com/API.html)
does not document a 2.0 calculation endpoint.
