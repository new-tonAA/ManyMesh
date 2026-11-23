"""Aggregate paired GPU captures and check the measured quality and cost frontier."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

import numpy as np


FILTERS = ("native", "msaa4", "smaa", "cubic")
ASSETS = (
    "AnisotropyBarnLamp", "DiffuseTransmissionTeacup", "GlassBrokenWindow",
    "GlassHurricaneCandleHolder", "MaterialsVariantsShoe", "PotOfCoals", "SpecularSilkPouf",
)


def measures(views, label):
    rows = [view["modes"][label] for view in views]
    psnr = [row["quality"]["psnr_db"] for row in rows]
    mse = statistics.mean(0 if value is None else 10 ** (-value / 10) for value in psnr)
    return {
        "psnr_db": -10 * math.log10(mse) if mse else None,
        "flip": statistics.mean(row["quality"]["flip"] for row in rows),
        "ssim": statistics.mean(row["quality"]["ssim"] for row in rows),
        "worst_flip": max(row["quality"]["flip"] for row in rows),
        "gpu_ms_p50": statistics.median(t for row in rows for batch in row["batches"]
                                       for t in batch["gpuMs"]),
    }


def dominates(a, b):
    return (a["gpu_ms_p50"] <= b["gpu_ms_p50"] and a["flip"] <= b["flip"]
            and (a["gpu_ms_p50"], a["flip"]) != (b["gpu_ms_p50"], b["flip"]))


def batch_deltas(views, mode):
    return [
        statistics.median(t for view in views
                          for t in view["modes"][f"contour_priority/{mode}"]["batches"][batch]["gpuMs"])
        - statistics.median(t for view in views
                            for t in view["modes"][f"qem/{mode}"]["batches"][batch]["gpuMs"])
        for batch in (0, 1)
    ]


def image_hashes(views):
    return [(row["view"], row["reference_sha256"],
             {label: mode["image_sha256"] for label, mode in row["modes"].items()})
            for row in views]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scored", type=Path, required=True)
    parser.add_argument("--initial", type=Path,
                        help="Earlier receipts with captures and scores interleaved with batch two")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    expected = {f"{arm}/{mode}" for arm in ("source", "qem", "contour_priority")
                for mode in FILTERS}
    assets = {}
    for name in ASSETS:
        receipt = json.loads((args.scored / f"{name}.json").read_text(encoding="utf-8"))
        views = receipt["views"]
        if (receipt["asset"] != name or [view["view"] for view in views] != list(range(6))
                or any(set(view["modes"]) != expected for view in views)):
            raise ValueError(f"Unexpected benchmark arms or views: {name}")
        initial = None
        if args.initial is not None:
            initial_bytes = (args.initial / f"{name}.json").read_bytes()
            initial = json.loads(initial_bytes)
            if image_hashes(views) != image_hashes(initial["views"]):
                raise ValueError(f"The rendered captures changed across timing schedules: {name}")
        summary = {key: measures(views, key) for key in sorted(expected)}
        ordinary = [value for key, value in summary.items() if not key.startswith("contour_priority/")]
        improvement = {}
        for mode in FILTERS:
            candidate = summary[f"contour_priority/{mode}"]
            same_mode = summary[f"qem/{mode}"]
            improvement[mode] = {
                "delta": {key: candidate[key] - same_mode[key] for key in candidate},
                "dominated_by_ordinary": any(dominates(row, candidate) for row in ordinary),
                "batch_gpu_p50_deltas_ms": batch_deltas(views, mode),
            }
            if initial is not None:
                improvement[mode]["initial_batch_gpu_p50_deltas_ms"] = batch_deltas(
                    initial["views"], mode)
        assets[name] = {"measurements": summary, "comparisons": improvement, "receipt": receipt}
        if initial is not None:
            assets[name].update(initial_sha256=hashlib.sha256(initial_bytes).hexdigest(),
                                captures_bit_identical=True)

    rng = np.random.default_rng(20261123)
    draws = rng.integers(0, len(ASSETS), size=(10000, len(ASSETS)))
    aggregate = {}
    for mode in FILTERS:
        rows = [asset["comparisons"][mode] for asset in assets.values()]
        fields = {}
        for key in rows[0]["delta"]:
            values = np.asarray([row["delta"][key] for row in rows])
            fields[key] = {
                "mean_delta": float(values.mean()),
                "asset_bootstrap_95": np.percentile(values[draws].mean(axis=1), [2.5, 97.5]).tolist(),
                "negative_count": int(np.count_nonzero(values < 0)),
                "positive_count": int(np.count_nonzero(values > 0)),
            }
        aggregate[mode] = {
            "paired_metrics": fields,
            "dominated_count": sum(row["dominated_by_ordinary"] for row in rows),
            "mean_batch_gpu_p50_deltas_ms": [
                statistics.mean(row["batch_gpu_p50_deltas_ms"][i] for row in rows) for i in (0, 1)
            ],
        }
        if args.initial is not None:
            aggregate[mode]["initial_mean_batch_gpu_p50_deltas_ms"] = [
                statistics.mean(row["initial_batch_gpu_p50_deltas_ms"][i] for row in rows)
                for i in (0, 1)
            ]
    args.out.write_text(json.dumps({"assets": assets, "aggregate": aggregate}, indent=2) + "\n",
                        encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
