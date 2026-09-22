"""Read-only adapter for the experimental Xert Beta 2 activity model.

The beta UI supplies an authenticated activity embed and runs a WebAssembly
model in the browser.  This module recreates that calculation
locally.  It deliberately has no mutation routes and never persists embed
HTML or its temporary access token.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from xert_common import _open_text
from xert_service import XertService


BETA = "https://beta.xertonline.com"
SERIES_FORMAT = "xert-beta-preview-series-v1"

RUNNER = r'''
const fs=require('fs'), vm=require('vm');
const input=JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ctx={window:{},import_meta:{url:input.bundle_url},console:{log:()=>{},warn:()=>{},error:()=>{}},
 atob,btoa,TextDecoder,TextEncoder,WebAssembly,performance,setTimeout,clearTimeout};
vm.createContext(ctx); vm.runInContext(fs.readFileSync(process.argv[3],'utf8'),ctx,{timeout:10000});
(async()=>{ const mod=await ctx.Module({print:()=>{},printErr:()=>{}}); const t=input.activity.recordsData,s=input.signature,e={...s};
 // Mirror the active frontend's initSigDisplay/buildEditedSignature.  The UI
 // round-trips its default g/h GLUT4R display values before every chart run.
 const rounded=(v,n)=>+Number(v).toFixed(n), clamp=(v,lo,hi)=>Math.min(hi,Math.max(lo,v));
 e.ftp=rounded(s.ftp,1); e.atc=rounded(s.atc,0); e.pp=rounded(s.pp,1);
 e.mgc=clamp(rounded(s.mgc,1),100,4000);
 e.initial_gmg_balance=clamp(rounded(s.initial_gmg_balance,1),-e.mgc,e.mgc);
 e.glut4r=clamp(rounded(s.glut4r,1),0,400); e.pcrc=clamp(rounded(s.pcrc,1),1000,20000);
 e.gross_eff=s.gross_eff==null?0.23:clamp(rounded(s.gross_eff*100,1)/100,0.15,0.3);
 e.active_muscle_kg_per_kg=clamp(rounded(s.active_muscle_kg_per_kg,2),0.05,0.4);
 e.blood_tank_l_per_kg=clamp(rounded(s.blood_tank_l_per_kg,3),0.1,0.7);
 const factor=s.blood_lactate_j_per_mmol/(s.blood_tank_l_per_kg*s.gross_eff);
 e.blood_lactate_j_per_mmol=Number.isFinite(factor)&&factor>0
   ?factor*e.blood_tank_l_per_kg*e.gross_eff:s.blood_lactate_j_per_mmol;
 e.muscle_lactate_oxidation_tau_s=clamp(rounded(s.muscle_lactate_oxidation_tau_s,0),10,300);
 e.muscle_blood_exchange_tau_s=clamp(rounded(s.muscle_blood_exchange_tau_s,0),20,1200);
 e.nonworking_tissue_clearance_tau_s=clamp(rounded(s.nonworking_tissue_clearance_tau_s,0),200,6000);
 e.gng_tau_s=clamp(rounded(s.gng_tau_s,0),200,3600); e.gng_max_w=clamp(rounded(s.gng_max_w,0),0,40);
 e.lt1_mmol=s.lt1_mmol==null?1.2:clamp(rounded(s.lt1_mmol,2),1,4);
 e.amgf=s.amgf==null?0:clamp(rounded(s.amgf,2),0.05,0.95);
 e.hie=e.atc/1000;e.pnr=e.atc/(e.m>0?e.m:30);e.carb_bias=input.carb_bias;
 const o=input.initialOptions;
 const defaults={degree:2,max_param_change:0.04,use_pcrc:true,single_param:false,debugLevel:0,
 use_mg_depletion:true,pcrDelay:5,min_proximity:0.8,params_to_fit:15,use_nonPcr_power:false,
 use_mg_replenishment:true,allow_supercompensation:false,use_lactate_fuel:true};
 const options=Object.fromEntries(Object.entries(defaults).map(([k,v])=>[k,o[k]??v]));
 Object.assign(options,{n_avg:o.movingAverage,anchor_tte:1200,do_extractSig:false});
 const b=mod.mpaChartData(t.time,t.dist,t.lat,t.lng,t.spd,t.cad,t.power,options,0,e,true,false);
 process.stdout.write(JSON.stringify({computed:b,signature_used:{...e,...b.signature},options_used:options}));
})().catch(()=>{process.stderr.write('Xert WASM calculation failed\\n');process.exitCode=1});
'''


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.frame: str | None = None
        self.bundle: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "iframe" and values.get("id") == "activity-embed-iframe":
            self.frame = values.get("src")
        if tag == "script" and "/js/svelte.js?" in (values.get("src") or ""):
            self.bundle = urljoin(BETA, values["src"])


def _beta_url(url: str | None) -> str:
    if not url or urlparse(url).scheme != "https" or urlparse(url).netloc != "beta.xertonline.com":
        raise ValueError("Expected an HTTPS beta.xertonline.com URL")
    return url


def _props(html: str) -> dict[str, Any]:
    section = html[html.index("new sessions.ActivityDetails"):]
    props: dict[str, Any] = {}
    for match in re.finditer(r"^\s*(\w+):\s*", section, re.M):
        if match[1] in {"activity", "signature", "initialOptions"}:
            props[match[1]] = json.JSONDecoder().raw_decode(section[match.end():])[0]
    user_match = re.search(r"\buserParams:\s*", html)
    if not user_match:
        raise ValueError("Missing Beta user parameters")
    carb_bias = json.JSONDecoder().raw_decode(html[user_match.end():])[0].get("carb_bias")
    if not isinstance(carb_bias, (int, float)):
        raise ValueError("Missing numeric carbohydrate bias")
    props["carb_bias"] = carb_bias
    return props


def _stats(values: list[float], times: list[float]) -> dict[str, float]:
    if not values or len(values) != len(times):
        raise ValueError("Invalid Beta model series length")
    lo, hi = min(range(len(values)), key=values.__getitem__), max(range(len(values)), key=values.__getitem__)
    return {"start": values[0], "minimum": values[lo], "minimum_at_s": times[lo],
            "maximum": values[hi], "maximum_at_s": times[hi], "end": values[-1]}


def _duration_at_or_above(values: list[float], times: list[float], threshold: float) -> float:
    """Return model time at or above a threshold, using source timestamps."""
    if len(values) != len(times) or len(values) < 2:
        raise ValueError("Invalid Beta model series length")
    durations = [max(0.0, later - earlier) for earlier, later in zip(times, times[1:])]
    # The renderer treats the final sample as one ordinary sample interval.
    final_duration = durations[-1] if durations else 0.0
    return sum(duration for value, duration in zip(values, [*durations, final_duration]) if value >= threshold)


def _integral_kj(values: list[float], times: list[float]) -> float:
    """Integrate a model power series using source timestamps."""
    if len(values) != len(times) or len(values) < 2:
        raise ValueError("Invalid Beta model series length")
    durations = [max(0.0, later - earlier) for earlier, later in zip(times, times[1:])]
    final_duration = durations[-1]
    return sum(value * duration for value, duration in zip(values, [*durations, final_duration])) / 1000


def _substrates_and_energy(model: dict[str, Any], series: dict[str, list[float]],
                           times: list[float], signature: dict[str, Any]) -> dict[str, Any]:
    """Return the compact activity totals shown by the Beta substrates UI."""
    gross_eff = _number(signature.get("gross_eff"), "Beta signature gross_eff")
    if gross_eff <= 0:
        raise ValueError("Beta signature gross_eff must be positive")
    carbs_g = model["total_carbs_used"]
    fat_g = model["total_fat_used"]
    glycogen_burned_g = model.get("gmg_burned_total", series["muscle_glycogen_burned_g"][-1])
    glycogen_depleted_g = model.get("gmg_depleted_total", signature["mgc"] -
                                    series["muscle_glycogen_remaining_g"][-1])
    glycogen_replenished_g = model.get("gmg_replenished_total", series["muscle_glycogen_replenished_g"][-1])
    glucose_burned_g = model.get("gbg_burned_total", carbs_g - glycogen_burned_g)
    regeneration_kj = _integral_kj(series["glucose_regeneration_w"], times)
    regeneration_fat_kj = _integral_kj(series["fat_used_for_regeneration_w"], times)
    residual_lactate_j = model["lactates"][-1]
    return {
        "total_carbs_g": carbs_g,
        "fat_g": fat_g,
        "calories_kcal": _integral_kj(series["power_w"], times) / gross_eff / 4.184,
        "glycogen": {
            "burned_g": glycogen_burned_g,
            "depleted_g": glycogen_depleted_g,
            "replenished_g": glycogen_replenished_g,
        },
        "glucose": {
            "used_g": carbs_g - glycogen_depleted_g,
            "burned_g": glucose_burned_g,
        },
        "carb_to_fat_ratio": carbs_g / fat_g if fat_g else None,
        "additional_energy": {
            # Beta's UI also assumes the remaining blood lactate is converted after the activity.
            "regenerated_glucose_g": (regeneration_kj * 1000 / gross_eff + residual_lactate_j) / (4.184 * 4 * 1000),
            "fat_used_for_regeneration_g": regeneration_fat_kj * 1000 / gross_eff / (4.184 * 9 * 1000),
        },
    }


def _lactate_mmol_l(values: list[float], signature: dict[str, Any]) -> list[float]:
    """Convert the WASM lactate series using the frontend's active signature schema."""
    blood_lactate_j_per_mmol = signature.get("blood_lactate_j_per_mmol")
    if isinstance(blood_lactate_j_per_mmol, (int, float)) and blood_lactate_j_per_mmol > 0:
        # Current Beta UI: venous lactate = 1.0 mM baseline + blood tank / J per mmol.
        return [1.0 + value / blood_lactate_j_per_mmol for value in values]
    legacy_factor = signature.get("l_mmol_factor")
    if isinstance(legacy_factor, (int, float)) and legacy_factor > 0:
        return [value / legacy_factor for value in values]
    raise ValueError("Xert Beta signature lacks a valid lactate conversion factor")


def _wasm_factory(bundle: str) -> str:
    """Extract the reviewed Emscripten factory interface from a Beta bundle.

    Bundle hashes change with ordinary vendor deployments.  The adapter is
    therefore guarded by the interface it needs, while recording the observed
    hash in every output for traceability.
    """
    start_marker = "Module = (() => {"
    end_marker = "xert_default = Module;"
    try:
        start = bundle.index(start_marker)
        end = bundle.index(end_marker, start)
    except ValueError as error:
        raise ValueError("Xert Beta frontend lacks the supported WASM factory interface") from error
    if end <= start:
        raise ValueError("Xert Beta frontend has an invalid WASM factory interface")
    return "var " + bundle[start:end]


def _run_wasm(props: dict[str, Any], bundle: str, bundle_url: str) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js is required for Xert Beta preview")
    factory = _wasm_factory(bundle)
    props = {**props, "bundle_url": bundle_url}
    with tempfile.TemporaryDirectory(prefix="xert-beta-preview-") as temporary:
        root = Path(temporary)
        (root / "input.json").write_text(json.dumps(props))
        (root / "factory.js").write_text(factory)
        (root / "runner.cjs").write_text(RUNNER)
        result = subprocess.run([node, str(root / "runner.cjs"), str(root / "input.json"), str(root / "factory.js")],
                                capture_output=True, text=True, timeout=60, check=True)
    return json.loads(result.stdout)


def _load_activity_beta_props(activity_path: str) -> tuple[dict[str, Any], str, str, str]:
    """Read the Beta model state from one completed activity without retaining HTML."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", activity_path):
        raise ValueError("Expected an activity path, not a URL")
    service = XertService()
    preview = _open_text(service._auth.web_opener(), Request(
        f"https://www.xertonline.com/activities/{activity_path}/preview"), "Xert preview")
    outer = _Page(); outer.feed(preview)
    with urlopen(_beta_url(outer.frame), timeout=45) as response:
        embed = response.read().decode()
    page = _Page(); page.feed(embed)
    bundle_url = _beta_url(page.bundle)
    with urlopen(bundle_url, timeout=45) as response:
        bundle_bytes = response.read()
    bundle_sha256 = hashlib.sha256(bundle_bytes).hexdigest()
    bundle = bundle_bytes.decode()
    _wasm_factory(bundle)
    props = _props(embed)
    if props["activity"].get("path") != activity_path:
        raise ValueError("Preview activity identity does not match request")
    return props, bundle, bundle_url, bundle_sha256


def _interval_summaries(series: dict[str, list[float]], intervals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize calculated work repetitions and their following RIB recoveries."""
    def glycogen(start: int, end: int, times: list[float]) -> dict[str, Any]:
        remaining = _stats(series["muscle_glycogen_remaining_g"][start:end], times)
        remaining["delta"] = remaining["end"] - remaining["start"]
        return {
            "remaining_g": remaining,
            "burned_g": series["muscle_glycogen_burned_g"][end - 1] - series["muscle_glycogen_burned_g"][start],
            "replenished_g": series["muscle_glycogen_replenished_g"][end - 1] - series["muscle_glycogen_replenished_g"][start],
        }

    summaries: list[dict[str, Any]] = []
    for interval in intervals:
        start, end = interval["start_index"], interval["end_index"]
        times = series["elapsed_s"][start:end]
        power = series["power_w"][start:end]
        lactate = series["lactate_model_mmol_l"][start:end]
        if not times:
            raise ValueError("Workout interval has no Beta model samples")
        lactate_stats = _stats(lactate, times)
        lactate_stats["delta"] = lactate_stats["end"] - lactate_stats["start"]
        summary: dict[str, Any] = {
            "row_index": interval["row_index"], "repetition": interval["repetition"],
            "name": interval["name"], "start_s": times[0], "end_s": times[-1] + 1,
            "duration_s": len(times),
            "power_w": {"average": sum(power) / len(power), "minimum": min(power), "maximum": max(power)},
            "lactate_model_mmol_l": lactate_stats,
            "muscle_glycogen": glycogen(start, end, times),
        }
        recovery = interval.get("recovery")
        if recovery:
            recovery_times = series["elapsed_s"][recovery["start_index"]:recovery["end_index"]]
            recovery_lactate = series["lactate_model_mmol_l"][recovery["start_index"]:recovery["end_index"]]
            recovery_stats = _stats(recovery_lactate, recovery_times)
            recovery_stats["delta"] = recovery_stats["end"] - recovery_stats["start"]
            summary["recovery"] = {
                "start_s": recovery_times[0], "end_s": recovery_times[-1] + 1,
                "duration_s": len(recovery_times), "power_w": recovery["power_w"],
                "lactate_model_mmol_l": recovery_stats,
                "muscle_glycogen": glycogen(recovery["start_index"], recovery["end_index"], recovery_times),
            }
        summaries.append(summary)
    return summaries


def _series_and_output(*, result: dict[str, Any], source_fields: dict[str, Any], save_series: bool,
                       series_context: dict[str, Any], bundle_sha256: str,
                       intervals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    model, signature = result["computed"], result["signature_used"]
    times = [value / 1000 for value in model["ts"]]
    series = {
        "elapsed_s": times,
        "power_w": model["ps"], "mpa_w": model["mpas"],
        "dynamic_tp_w": model["ftps"], "dynamic_hie_kj": [value / 1000 for value in model["hies"]],
        "lactate_model_mmol_l": _lactate_mmol_l(model["lactates"], signature),
        "glucose_regeneration_w": model["gng"],
        "fat_used_for_regeneration_w": model["gngFat"],
        "muscle_glycogen_remaining_g": [signature["mgc"] - value for value in model["gmg_depleted"]],
        "muscle_glycogen_burned_g": model["gmg_burned"],
        "muscle_glycogen_replenished_g": model["gmg_replenished"],
    }
    metrics = {key: _stats(values, times) for key, values in series.items() if key not in {
        "elapsed_s", "power_w", "glucose_regeneration_w", "fat_used_for_regeneration_w",
        "muscle_glycogen_burned_g", "muscle_glycogen_replenished_g"}}
    metrics["lactate_model_mmol_l"]["duration_at_or_above_s"] = {
        f"{threshold:g}_mmol_l": _duration_at_or_above(series["lactate_model_mmol_l"], times, threshold)
        for threshold in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)
    }
    metrics["muscle_glycogen_burned_g"] = {"end": series["muscle_glycogen_burned_g"][-1]}
    metrics["muscle_glycogen_replenished_g"] = {"end": series["muscle_glycogen_replenished_g"][-1]}
    output: dict[str, Any] = {
        **source_fields,
        "source": "xert_beta_local_wasm", "experimental": True,
        "standard_xert_comparable": False,
        "caveats": ["Experimental Beta 2 model estimates, not physiological measurements.",
                    "Beta XSS and other calculated values can differ from standard Xert activity values.",
                    "No Beta signature, option, segment, or activity writes were performed."],
        "bundle_sha256": bundle_sha256, "options_used": result["options_used"],
        "signature_used": signature, "metrics": metrics,
        "xss": {key: model[value] for key, value in (("total", "xss"), ("low", "xlss"), ("high", "xhss"), ("peak", "xpss"))},
        "substrates_and_energy": _substrates_and_energy(model, series, times, signature),
    }
    if intervals is not None:
        output["intervals"] = _interval_summaries(series, intervals)
    if save_series:
        descriptor, file_name = tempfile.mkstemp(prefix="xert-beta-preview-series-", suffix=".json")
        with os.fdopen(descriptor, "w") as stream:
            json.dump({**series_context, "bundle_sha256": bundle_sha256,
                       "signature_used": signature, "options_used": result["options_used"], "series": series}, stream,
                      allow_nan=False)
        output.update({"series_file": file_name, "series_format": SERIES_FORMAT,
                       "series_byte_size": os.path.getsize(file_name)})
    return output


def get_activity_beta_preview(activity_path: str, *, save_series: bool = False) -> dict[str, Any]:
    """Compute an experimental, read-only Beta 2 preview for one activity."""
    props, bundle, bundle_url, bundle_sha256 = _load_activity_beta_props(activity_path)
    result = _run_wasm(props, bundle, bundle_url)
    return _series_and_output(
        result=result,
        source_fields={"activity_path": activity_path, "name": props["activity"].get("name")},
        save_series=save_series,
        series_context={"activity_path": activity_path},
        bundle_sha256=bundle_sha256,
    )


def _number(value: Any, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _power_values(row: dict[str, Any], *, signature: dict[str, Any], sequence: int) -> list[float]:
    """Expand one supported Workout Designer row into one-second power samples."""
    duration = _positive_int(row.get("duration_seconds"), f"rows[{sequence}].duration_seconds")
    power_type = row.get("power_type", "absolute")
    power = _number(row.get("power"), f"rows[{sequence}].power")
    ftp = _number(signature.get("ftp"), "Beta signature ftp")
    multiplier = {"absolute": 1.0, "relative_ftp": ftp / 100,
                  "ramp_absolute": 1.0, "ramp_ftp": ftp / 100}
    if power_type == "ramp_ltp":
        multiplier[power_type] = _number(signature.get("ltp"), "Beta signature ltp") / 100
    if power_type not in multiplier:
        raise ValueError(f"rows[{sequence}].power_type is unsupported by Beta preview")
    start = power * multiplier[power_type]
    if not power_type.startswith("ramp_"):
        return [start] * duration
    end = _number(row.get("power_second_value"), f"rows[{sequence}].power_second_value") * multiplier[power_type]
    return [start + (end - start) * index / max(1, duration - 1) for index in range(duration)]


def _expand_workout(rows: list[dict[str, Any]], signature: dict[str, Any]) -> tuple[list[float], list[dict[str, Any]]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows must be a non-empty array")
    samples: list[float] = []
    intervals: list[dict[str, Any]] = []
    for sequence, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"rows[{sequence}] must be an object")
        repeats = row.get("interval_count", 1)
        if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 0:
            raise ValueError(f"rows[{sequence}].interval_count must be a non-negative integer")
        work = _power_values(row, signature=signature, sequence=sequence)
        rib_duration = row.get("rib_duration_seconds", 0)
        if not isinstance(rib_duration, int) or isinstance(rib_duration, bool) or rib_duration < 0:
            raise ValueError(f"rows[{sequence}].rib_duration_seconds must be a non-negative integer")
        rib_type = row.get("rib_power_type", "absolute")
        rib_power = _number(row.get("rib_power", 0), f"rows[{sequence}].rib_power")
        if rib_type == "relative_ftp":
            rib_power *= _number(signature.get("ftp"), "Beta signature ftp") / 100
        elif rib_type != "absolute":
            raise ValueError(f"rows[{sequence}].rib_power_type is unsupported by Beta preview")
        for repetition in range(repeats):
            start = len(samples)
            samples.extend(work)
            interval: dict[str, Any] = {
                "row_index": sequence, "repetition": repetition + 1,
                "name": str(row.get("name") or f"Row {sequence + 1}"),
                "start_index": start, "end_index": len(samples),
            }
            if rib_duration:
                recovery_start = len(samples)
                interval["recovery"] = {
                    "start_index": recovery_start, "end_index": recovery_start + rib_duration,
                    "power_w": rib_power,
                }
            samples.extend([rib_power] * rib_duration)
            intervals.append(interval)
    if not samples:
        raise ValueError("Workout rows expand to no time-series samples")
    return samples, intervals


def _expand_workout_rows(rows: list[dict[str, Any]], signature: dict[str, Any]) -> list[float]:
    """Backward-compatible power-only workout expansion for internal callers/tests."""
    return _expand_workout(rows, signature)[0]


def calculate_workout_beta_preview(rows: list[dict[str, Any]], *, beta_model_source_activity_path: str,
                                   save_series: bool = False) -> dict[str, Any]:
    """Calculate an unsaved workout with the Beta state sourced from one activity."""
    props, bundle, bundle_url, bundle_sha256 = _load_activity_beta_props(beta_model_source_activity_path)
    power, intervals = _expand_workout(rows, props["signature"])
    count = len(power)
    records = {
        "time": [index * 1000 for index in range(count)], "dist": [0.0] * count,
        "lat": [None] * count, "lng": [None] * count, "spd": [0.0] * count,
        "cad": [0.0] * count, "power": power,
    }
    calculation_props = {**props, "activity": {"path": "unsaved-workout", "name": "Unsaved workout",
                                                   "recordsData": records}}
    result = _run_wasm(calculation_props, bundle, bundle_url)
    return _series_and_output(
        result=result,
        source_fields={"beta_model_source_activity_path": beta_model_source_activity_path,
                       "workout_duration_s": count},
        save_series=save_series,
        series_context={"beta_model_source_activity_path": beta_model_source_activity_path,
                        "workout_rows": rows},
        bundle_sha256=bundle_sha256,
        intervals=intervals,
    )
