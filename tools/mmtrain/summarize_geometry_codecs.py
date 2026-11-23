"""Summarize and plot the measured geometry codec tradeoffs."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FixedLocator, FuncFormatter, NullLocator
import numpy as np


def feasible(row):
    return (not row.get("error") and not row.get("topology_error")
            and not row["input_topology_error"] and row.get("oriented_grid_faces_match") is True)


def frontier(rows):
    valid = [row for row in rows if feasible(row)]
    return [row for row in valid if not any(
        candidate["bytes"] <= row["bytes"] and candidate["mean"]["flip"] <= row["mean"]["flip"]
        and (candidate["bytes"] < row["bytes"] or candidate["mean"]["flip"] < row["mean"]["flip"])
        for candidate in valid)]


def plot(report, path):
    assets = report["assets"]
    columns = min(4, len(assets))
    rows = (len(assets) + columns - 1) // columns
    figure, axes = plt.subplots(rows, columns, figsize=(3.7 * columns, 2.85 * rows + 0.7),
                               squeeze=False, layout="constrained")
    colors = {"draco": "#2b648b", "meshopt": "#a24b25"}
    markers = {"full": "o", "meshopt70": "s"}
    for axis, asset in zip(axes.flat, assets):
        for row in asset["rows"]:
            if "mean" in row:
                color = colors[row["codec"]]
                axis.scatter(row["bytes"], row["mean"]["flip"], marker=markers[row["input"]],
                             s=36, facecolor=color if feasible(row) else "none", edgecolor=color)
        line = sorted(frontier(asset["rows"]), key=lambda row: row["bytes"])
        if line:
            axis.plot([row["bytes"] for row in line], [row["mean"]["flip"] for row in line],
                      color="#565d56", alpha=.55, zorder=0)
        axis.set(xscale="log", title=f"Thingi10K {asset['asset']} · {asset['source_faces']:,} faces",
                 xlabel="Geometry payload (kB)", ylabel="Mean LDR-FLIP ↓")
        low, high = axis.get_xlim()
        axis.xaxis.set_major_locator(FixedLocator(np.geomspace(low, high, 5)[1:-1]))
        axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1000:.1f}"))
        axis.xaxis.set_minor_locator(NullLocator())
        axis.grid(alpha=.18)
    for axis in list(axes.flat)[len(assets):]:
        axis.set_visible(False)
    handles = [
        Line2D([], [], linestyle="", marker="o", color=color, label=label)
        for color, label in ((colors["draco"], "Draco"), (colors["meshopt"], "Meshopt codec"))
    ]
    handles += [Line2D([], [], linestyle="", marker="s", color="#4f5454", label="Simplified input"),
                Line2D([], [], linestyle="", marker="o", color="#4f5454", markerfacecolor="none",
                       label="Check failed"),
                Line2D([], [], color="#565d56", alpha=.55, label="Feasible frontier")]
    figure.legend(handles=handles, loc="outside lower center", ncols=min(5, len(handles)),
                  frameon=False)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--plot", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.receipt.read_text(encoding="utf-8"))
    plot(report, args.plot)
    assets = report["assets"]
    for label in ("full", "meshopt70"):
        for bits in report["protocol"]["bits"]:
            pairs = [
                {row["codec"]: row for row in asset["rows"]
                 if row["input"] == label and row["bits"] == bits}
                for asset in assets
            ]
            print(label, bits)
            for codec in ("draco", "meshopt"):
                rows = [pair[codec] for pair in pairs]
                decoded = [row for row in rows if "mean" in row]
                print(codec, f"{sum(map(feasible, rows))}/{len(rows)} feasible",
                      "medians", {key: float(np.median([row[key] for row in decoded])) if decoded else None
                                  for key in ("bytes", "median_decode_ms")},
                      "FLIP", float(np.median([row["mean"]["flip"] for row in decoded])) if decoded else None)
            paired = [pair for pair in pairs if all(map(feasible, pair.values()))]
            if paired:
                print("paired feasible Draco / meshopt bytes",
                      float(np.median([pair["draco"]["bytes"] / pair["meshopt"]["bytes"]
                                       for pair in paired])))
    for asset in assets:
        print(asset["asset"], [(row["codec"], row["input"], row["bits"], row["bytes"],
                                round(row["mean"]["flip"], 6)) for row in frontier(asset["rows"])])


if __name__ == "__main__":
    main()
