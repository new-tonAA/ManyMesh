"""Hash and aggregate the paired contour priority benchmark receipts."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

import numpy as np


def summarize(views, arm):
    rows = [row[arm] for row in views]
    mse = statistics.mean(row["mse"] for row in rows)
    psnr = -10 * math.log10(mse) if mse else None
    finite_psnr = [row["psnr_db"] for row in rows if row["psnr_db"] is not None]
    result = {
        "psnr_db": {"mean": psnr, "worst": min(finite_psnr, default=None)},
    }
    for key in ("flip", "silhouette_xor_fraction", "coverage_mae", "ssim"):
        values = [row[key] for row in rows]
        result[key] = {"mean": statistics.mean(values),
                       "worst": min(values) if key == "ssim" else max(values)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assets = {}
    paired = []
    for name in ("AnisotropyBarnLamp", "DiffuseTransmissionTeacup", "GlassBrokenWindow",
                 "GlassHurricaneCandleHolder", "MaterialsVariantsShoe", "PotOfCoals",
                 "SpecularSilkPouf"):
        entries = {kind: (args.run_dir / kind / f"{name}.json").read_bytes()
                   for kind in ("scored", "controls")}
        scored, controls = (json.loads(entries[kind]) for kind in ("scored", "controls"))
        if (scored["source_sha256"] != controls["source_sha256"]
                or scored["target_faces"] != controls["target_faces"]):
            raise ValueError(f"Different reference or face target for {name}")
        metrics = {}
        for receipt in (scored, controls):
            views = receipt["views"]
            if not views:
                continue
            if [(row["view"], row["screen_scale"]) for row in views] != [
                    (view, scale) for scale in (1.0, 0.55) for view in range(12)]:
                raise ValueError(f"Unexpected view layout for {name}")
            for arm in receipt["arms"]:
                if arm in views[0]:
                    metrics[arm] = summarize(views, arm)
        deltas = {}
        if "contour_priority" in metrics:
            deltas = {key: {stat: metrics["contour_priority"][key][stat]
                            - metrics["qem"][key][stat] for stat in ("mean", "worst")}
                      for key in metrics["qem"]}
            paired.append({key: row["mean"] for key, row in deltas.items()})
        assets[name] = {
            "metrics": metrics, "contour_minus_qem": deltas,
            "receipt_sha256": {key: hashlib.sha256(value).hexdigest()
                               for key, value in entries.items()},
            "scored": scored, "controls": controls,
        }
    rng = np.random.default_rng(20261123)
    draws = rng.integers(0, len(paired), size=(10000, len(paired)))
    aggregate = {}
    for key in paired[0]:
        values = np.asarray([row[key] for row in paired])
        aggregate[key] = {
            "mean": float(values.mean()),
            "bootstrap_percentile_95": np.percentile(values[draws].mean(axis=1), [2.5, 97.5]).tolist(),
        }
    result = {"scope": "reused development assets", "assets": assets,
              "paired_asset_count": len(paired), "equal_asset_weight_mean_delta": aggregate}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
