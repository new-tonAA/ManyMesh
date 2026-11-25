"""Post-hoc silhouette-error attribution on the scored Poly Haven cohort."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

import numpy as np

from bench_appearance_controls import (
    HEIGHT, WIDTH, bind_camera, camera_eyes, load_inputs,
)
from bench_component_gpu import Offscreen, select_adapter
from bench_contour_priority_aa import upload


ROOT = Path(__file__).resolve().parents[2]
METRICS_PATH = ROOT / "tools/mmtrain/polyhaven_quality_metrics_20261124.json"
MANIFEST_PATH = ROOT / "tools/mmtrain/polyhaven_quality_cohort_20261124.json"
RASTER_MODES = (("native", None), ("msaa4", "msaa4"))
MODES = tuple(label for label, _ in RASTER_MODES)
ARMS = ("manymesh", "qem_preserve_border", "meshoptimizer_lock_border")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_metrics():
    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    if metrics.get("status") != "complete" or metrics.get("assets") != 21:
        raise ValueError("Expected the completed, already-scored 21-model cohort")
    return metrics


def score_asset(device, high, raster, manifest, row):
    slug = row["asset"]
    asset = manifest["assets"][slug]
    geometry_dir = ROOT / asset["geometry_dir"]
    geometries = load_inputs(geometry_dir, asset["frozen_exports"], None)
    meshes = {name: upload(device, *geometries[name])
              for name in ("reference", *ARMS)}
    pooled = {arm: {
        mode: {"error_energy": 0.0, "xor_error_energy": 0.0,
               "xor_pixels": 0, "pixels": 0, "views": []}
        for mode in MODES
    } for arm in ARMS}

    for view, distance, eye in camera_eyes():
        camera_buffers = [bind_camera(raster, eye), bind_camera(high, eye)]
        _, high_gray = high.run(meshes["reference"], "msaa4", 1, True)
        reference = high_gray.reshape(HEIGHT, 2, WIDTH, 2).mean(axis=(1, 3))
        reference_mask = reference > 0
        for arm in ARMS:
            for mode, raster_mode in RASTER_MODES:
                _, candidate = raster.run(meshes[arm], raster_mode, 1, True)
                xor = np.logical_xor(reference_mask, candidate > 0)
                error = np.square(candidate.astype(np.float64) - reference.astype(np.float64))
                item = pooled[arm][mode]
                error_energy = float(error.sum(dtype=np.float64))
                xor_error_energy = float(error[xor].sum(dtype=np.float64))
                item["error_energy"] += error_energy
                item["xor_error_energy"] += xor_error_energy
                item["xor_pixels"] += int(xor.sum())
                item["pixels"] += int(xor.size)
                item["views"].append({
                    "view": view, "distance": distance,
                    "xor_fraction": float(xor.mean()),
                    "xor_error_share": (xor_error_energy / error_energy
                                        if error_energy > 0 else None),
                })
        for buffer in camera_buffers:
            buffer.destroy()

    result = {"asset": slug, "uncertainty_group": row["uncertainty_group"],
              "source_sha256": row["source_sha256"], "source_faces": row["source_faces"],
              "candidate_faces": row["control_faces"], "arms": {}}
    for arm, modes in pooled.items():
        result["arms"][arm] = {}
        for mode, item in modes.items():
            shares = [entry["xor_error_share"] for entry in item["views"]
                      if entry["xor_error_share"] is not None]
            result["arms"][arm][mode] = {
                "total_squared_error": item["error_energy"],
                "xor_squared_error": item["xor_error_energy"],
                "non_xor_squared_error": item["error_energy"] - item["xor_error_energy"],
                "pooled_xor_fraction": item["xor_pixels"] / item["pixels"],
                "pooled_xor_error_share": (item["xor_error_energy"] / item["error_energy"]
                                           if item["error_energy"] else None),
                "view_median_xor_error_share": statistics.median(shares) if shares else None,
                "view_min_xor_error_share": min(shares) if shares else None,
                "view_max_xor_error_share": max(shares) if shares else None,
                "views": item["views"],
            }
    return result


def bootstrap_group_mean(rows, arm, mode, seed=20261125, samples=10000):
    by_group = {}
    for row in rows:
        value = row["arms"][arm][mode]["pooled_xor_error_share"]
        by_group.setdefault(row["uncertainty_group"], []).append(value)
    groups = sorted(by_group)
    values = np.asarray([np.mean(by_group[group]) for group in groups], dtype=np.float64)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(samples, len(values)))
    means = values[indices].mean(axis=1)
    return {
        "group_count": len(groups), "group_mean": float(values.mean()),
        "group_bootstrap_95_percentile_ci": [float(x) for x in np.quantile(means, [0.025, 0.975])],
        "groups_above_half": int(np.count_nonzero(values > 0.5)),
        "group_values": {group: float(value) for group, value in zip(groups, values)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--adapter", default="Intel(R) Iris(R) Xe Graphics")
    parser.add_argument("--backend", default="D3D12")
    parser.add_argument("--asset", action="append", help="Optional diagnostic subset")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    metrics = load_metrics()
    selected = metrics["per_asset"]
    if args.asset:
        wanted = set(args.asset)
        selected = [row for row in selected if row["asset"] in wanted]
        if {row["asset"] for row in selected} != wanted:
            raise ValueError("Requested asset subset is not in the frozen scored cohort")

    adapter = select_adapter(args.adapter, args.backend)
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = Offscreen(device, WIDTH, HEIGHT, 1, False)
    high = Offscreen(device, WIDTH * 2, HEIGHT * 2, 1, False)
    rows = []
    for index, row in enumerate(selected, 1):
        started = time.perf_counter()
        result = score_asset(device, high, raster, manifest, row)
        rows.append(result)
        elapsed = time.perf_counter() - started
        print(index, result["asset"], f"{elapsed:.1f}s",
              {arm: {mode: result["arms"][arm][mode]["pooled_xor_error_share"]
                     for mode in MODES} for arm in ARMS},
              flush=True)

    summary = {arm: {mode: bootstrap_group_mean(rows, arm, mode)
                     for mode in MODES} for arm in ARMS}
    receipt = {
        "schema": 1,
        "status": "complete" if len(rows) == len(selected) else "partial",
        "analysis_role": "post-hoc diagnostic on the already-scored 21-model development cohort",
        "metric_definition": (
            "For each view, sum squared linear-gray render error only at pixels where the "
            "candidate and 2x-MSAA-resolved source binary coverage masks XOR; divide by total "
            "squared linear-gray error. Pool error energy across 24 frozen view-distance pairs "
            "within each asset, then average assets within each of the 16 source groups."
        ),
        "limitations": [
            "Same asset cohort was already inspected; this is not independent confirmation.",
            "The XOR attribution mask is a diagnostic definition, not a perceptual metric.",
            "Flat grayscale shading and fixed desktop views do not establish user preference or mobile behavior.",
        ],
        "protocol": {
            "manifest_sha256": digest(MANIFEST_PATH),
            "metrics_sha256": digest(METRICS_PATH),
            "script_sha256": digest(Path(__file__)),
            "adapter": dict(adapter.info), "python": platform.python_version(),
            "resolution": [WIDTH, HEIGHT], "view_distance_pairs_per_asset": 24,
            "candidates": list(ARMS),
            "reference": "full source at 2x resolution with 4x MSAA and linear box resolve",
            "modes": list(MODES), "group_bootstrap_samples": 10000,
            "group_bootstrap_seed": 20261125,
        },
        "assets": rows,
        "summary": summary,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print("receipt", args.out, "assets", len(rows), "groups",
          summary["manymesh"]["native"]["group_count"])


if __name__ == "__main__":
    main()
