"""Validate scene receipt invariants and summarize the measured quality frontiers."""

import argparse
import json
from pathlib import Path

import numpy as np


MODES = {
    "source-native": "Source native", "source-msaa4": "Source 4× MSAA",
    "source-smaa": "Source SMAA", "source-linear": "Source 2× linear",
    "source-cubic": "Source 2× cubic", "qem-msaa4": "QEM 4× MSAA",
    "qem-smaa": "QEM SMAA", "parts-msaa4": "Component 4× MSAA",
    "parts-smaa": "Component SMAA", "cluster1-msaa4": "Cluster depth 1, 4× MSAA",
    "cluster2-msaa4": "Cluster depth 2, 4× MSAA",
}
METRICS = {"flip": -1, "psnr_db": 1, "ssim": 1}


def frontier(rows, metric):
    sign = METRICS[metric]
    places = sorted(rows, key=lambda k: (rows[k]["p50"], -sign * rows[k][metric], k))
    best = -np.inf
    eligible = []
    for name in places:
        value = sign * rows[name][metric]
        if value > best:
            best = value
            eligible.append(name)
    return eligible


def summarise(report):
    frames = report["frames_per_batch"] * report["batches"]
    pixels = np.prod(report["size"])
    out = {}
    for scene, desc in report["scenes"].items():
        counts = desc["triangle_counts"]
        if counts["source"] < 1_000_000 or counts["qem"] != counts["parts"]:
            raise ValueError(f"Scale or face-match failure in {scene}")
        if len(desc["asset_order"]) != desc["indexed_draws"] or len(desc["asset_order"]) < 5:
            raise ValueError(f"Invalid draw grouping in {scene}")
        observed = []
        for view in desc["views"]:
            if set(view["modes"]) != MODES.keys():
                raise ValueError(f"Missing modes in {scene}")
            if not (0 <= view["cross_asset_overlap_pixels"] <= view["coverage_pixels"] <= pixels
                    and len(view["group_coverage_pixels"]) == desc["indexed_draws"]
                    and all(view["group_coverage_pixels"])):
                raise ValueError(f"Invalid overlap or visibility in {scene}")
            measured = {}
            for key, row in view["modes"].items():
                t = np.asarray(row["gpu_ms"])
                if len(t) != frames or np.any(~np.isfinite(t)) or np.any(t <= 0):
                    raise ValueError(f"Invalid GPU samples in {scene}/{key}")
                measured[key] = {"p50": float(np.median(t)), "p95": float(np.percentile(t, 95)),
                                 **row["quality"], "silhouette_xor": row["silhouette_xor_fraction"]}
            observed.append({"eye": view["eye"], "modes": measured,
                             "overlap_fraction": view["cross_asset_overlap_pixels"] / view["coverage_pixels"],
                             "frontier": {m: frontier(measured, m) for m in METRICS}})
        medians = {k: {m: float(np.median([v["modes"][k][m] for v in observed]))
                       for m in next(iter(observed))["modes"][k]} for k in MODES}
        out[scene] = {"triangles": counts, "instances": sum(map(len, desc["instance_transforms"].values())),
                      "asset_count": desc["indexed_draws"], "views": observed,
                      "median_across_views": medians}
    return out


def plot(scenes, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(scenes), figsize=(12, 4.6), squeeze=False, sharey=True)
    markers = ("o", "s", "D", "^", "v", "s", "D", "s", "D", "P", "X")
    colors = ("#455a64",) * 5 + ("#3068af",) * 2 + ("#258463",) * 2 + ("#b64c1c",) * 2
    for axis, (scene, data) in zip(axes[0], scenes.items()):
        axis.set_title(scene.replace("-", " ").title(), fontsize=11)
        axis.set_xlabel("GPU time (ms)")
        axis.grid(color="#e3e8eb", zorder=0)
        rows = data["median_across_views"]
        edge = [rows[k] for k in frontier(rows, "flip")]
        axis.plot([r["p50"] for r in edge], [r["flip"] for r in edge],
                  color="#a7adb4", linewidth=1, zorder=1)
        for (key, label), marker, color in zip(MODES.items(), markers, colors, strict=True):
            row = rows[key]
            axis.scatter(row["p50"], row["flip"], label=label, color=color, marker=marker,
                         zorder=2, s=33, linewidths=0.5, edgecolors="white")
        axis.spines[["right", "top"]].set_visible(False)
    axes[0][0].set_ylabel("LDR-FLIP error (lower is better)")
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=4, fontsize=8, frameon=False, bbox_to_anchor=(.5, .015))
    fig.subplots_adjust(wspace=.1, bottom=.25, top=.84, left=.08, right=.98)
    fig.suptitle("Mixed-scene AA and geometry baselines on Intel Iris Xe", fontsize=14, y=.96)
    fig.savefig(path, dpi=160, facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plot", type=Path)
    args = parser.parse_args()
    report = json.loads(args.receipt.read_bytes())
    summary = summarise(report)
    args.out.write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if args.plot:
        plot(summary, args.plot)


if __name__ == "__main__":
    main()
