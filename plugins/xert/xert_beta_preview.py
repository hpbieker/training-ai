"""Read-only adapter for the experimental Xert Beta 2 activity model.

The beta UI supplies an authenticated activity embed and runs a hash-pinned
WebAssembly model in the browser.  This module recreates that calculation
locally.  It deliberately has no mutation routes and never persists embed
HTML or its temporary access token.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
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
BUNDLE_SHA256 = "87f393f744cd3cbc2ffb1a1db51ed33d15f79f888995cb4a72eef6c60d207a11"
SERIES_FORMAT = "xert-beta-preview-series-v1"

RUNNER = r'''
const fs=require('fs'), vm=require('vm');
const input=JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const ctx={window:{},ykt:{url:input.bundle_url},console:{log:()=>{},warn:()=>{},error:()=>{}},
 atob,btoa,TextDecoder,TextEncoder,WebAssembly,performance,setTimeout,clearTimeout};
vm.createContext(ctx); vm.runInContext(fs.readFileSync(process.argv[3],'utf8'),ctx,{timeout:10000});
(async()=>{ const mod=await ctx.Tte({print:()=>{},printErr:()=>{}}); const t=input.activity.recordsData,e={...input.signature};
 for(const k of ['ftp','pp','initial_gmg_balance','glut4r','pcrc','mgc'])e[k]=+e[k].toFixed(1);
 e.atc=+e.atc.toFixed(0);e.hie=e.atc/1000;e.pnr=e.atc/e.m;e.carb_bias=input.carb_bias;
 const options={...input.initialOptions,n_avg:input.initialOptions.movingAverage,a_tte:1200,do_extractSig:false};
 const b=mod.mpaChartData(t.time,t.dist,t.lat,t.lng,t.spd,t.cad,t.power,options,0,e,true,false);
 process.stdout.write(JSON.stringify({computed:b,signature_used:e,options_used:options}));
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


def _run_wasm(props: dict[str, Any], bundle: str, bundle_url: str) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        raise ValueError("Node.js is required for Xert Beta preview")
    factory = "var " + bundle[bundle.index("Tte="):bundle.index(",qte=Tte")] + ";"
    props = {**props, "bundle_url": bundle_url}
    with tempfile.TemporaryDirectory(prefix="xert-beta-preview-") as temporary:
        root = Path(temporary)
        (root / "input.json").write_text(json.dumps(props))
        (root / "factory.js").write_text(factory)
        (root / "runner.cjs").write_text(RUNNER)
        result = subprocess.run([node, str(root / "runner.cjs"), str(root / "input.json"), str(root / "factory.js")],
                                capture_output=True, text=True, timeout=60, check=True)
    return json.loads(result.stdout)


def get_activity_beta_preview(activity_path: str, *, save_series: bool = False) -> dict[str, Any]:
    """Compute an experimental, read-only Beta 2 preview for one activity."""
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
    if hashlib.sha256(bundle_bytes).hexdigest() != BUNDLE_SHA256:
        raise ValueError("Xert Beta frontend changed; preview calculation is disabled pending adapter review")
    props = _props(embed)
    if props["activity"].get("path") != activity_path:
        raise ValueError("Preview activity identity does not match request")
    result = _run_wasm(props, bundle_bytes.decode(), bundle_url)
    model, signature = result["computed"], result["signature_used"]
    times = [value / 1000 for value in model["ts"]]
    series = {
        "elapsed_s": times,
        "power_w": model["ps"], "mpa_w": model["mpas"],
        "dynamic_tp_w": model["ftps"], "dynamic_hie_kj": [value / 1000 for value in model["hies"]],
        "lactate_model_mmol_l": [value / signature["l_mmol_factor"] for value in model["lactates"]],
        "muscle_glycogen_remaining_g": [signature["mgc"] - value for value in model["gmg_depleted"]],
        "muscle_glycogen_burned_g": model["gmg_burned"],
        "muscle_glycogen_replenished_g": model["gmg_replenished"],
    }
    metrics = {key: _stats(values, times) for key, values in series.items() if key not in {
        "elapsed_s", "power_w", "muscle_glycogen_burned_g", "muscle_glycogen_replenished_g"}}
    metrics["lactate_model_mmol_l"]["duration_at_or_above_s"] = {
        f"{threshold:g}_mmol_l": _duration_at_or_above(series["lactate_model_mmol_l"], times, threshold)
        for threshold in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)
    }
    metrics["muscle_glycogen_burned_g"] = {"end": series["muscle_glycogen_burned_g"][-1]}
    metrics["muscle_glycogen_replenished_g"] = {"end": series["muscle_glycogen_replenished_g"][-1]}
    output: dict[str, Any] = {
        "activity_path": activity_path, "name": props["activity"].get("name"),
        "source": "xert_beta_local_wasm", "experimental": True,
        "standard_xert_comparable": False,
        "caveats": ["Experimental Beta 2 model estimates, not physiological measurements.",
                    "Beta XSS and other calculated values can differ from standard Xert activity values.",
                    "No Beta signature, option, segment, or activity writes were performed."],
        "bundle_sha256": BUNDLE_SHA256, "options_used": result["options_used"],
        "signature_used": signature, "metrics": metrics,
        "xss": {key: model[value] for key, value in (("total", "xss"), ("low", "xlss"), ("high", "xhss"), ("peak", "xpss"))},
        "energy": {"carbs_g": model["total_carbs_used"], "fat_g": model["total_fat_used"]},
    }
    if save_series:
        descriptor, file_name = tempfile.mkstemp(prefix="xert-beta-preview-series-", suffix=".json")
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"activity_path": activity_path, "bundle_sha256": BUNDLE_SHA256,
                       "signature_used": signature, "options_used": result["options_used"], "series": series}, stream,
                      allow_nan=False)
        output.update({"series_file": file_name, "series_format": SERIES_FORMAT,
                       "series_byte_size": os.path.getsize(file_name)})
    return output
