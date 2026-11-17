"""Plot finite support fractions, explicitly excluding timing or speedup claims."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    fig, axes = plt.subplots(2, 3, figsize=(11, 6.2), sharey=True)
    configurations = (("historyBoxes", "All edit boxes", "#929ba5"),
                      ("endpointBoxes", "Endpoint difference boxes", "#d9a04e"),
                      ("coneFilteredBoxes", "Orientation-filtered edit boxes", "#2a7b9b"))
    for column, asset in enumerate(report["assets"]):
        levels = [asset["levels"][ratio] for ratio in ("0.75", "0.5", "0.25")]
        x = np.arange(3)
        for row, (field, denominator) in enumerate((
                ("fallbackInsideSourceRectangle", "sourceRectangleSamples"),
                ("fallbackOnFineHits", "fineHits"))):
            ax = axes[row, column]
            for index, (name, label, color) in enumerate(configurations):
                y = [100 * level["totals"][name][field] / level[denominator] for level in levels]
                ax.bar(x + (index - 1) * .25, y, .24, label=label, color=color)
            ax.set_xticks(x, [f"{100 * v['actualTriangles'] / asset['sourceTriangles']:.1f}%" for v in levels])
            ax.set_ylim(0, 104)
            ax.set_axisbelow(True)
            ax.grid(axis="y", color="#e5e5e5", linewidth=.7)
            ax.spines[["top", "right"]].set_visible(False)
            if row == 0:
                ax.set_title(asset["asset"].capitalize())
            else:
                ax.set_xlabel("Retained triangles")
    axes[0, 0].set_ylabel("Fallback within source\nrectangle (%)")
    axes[1, 0].set_ylabel("Fallback on fine hits (%)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(.5, .965))
    fig.suptitle("Conservative support for possible coverage changes", y=1, fontsize=14)
    fig.text(.5, .012, "Three development assets; 12 fixed orthographic views. Binary coverage only; query costs are unmeasured.",
             ha="center", fontsize=9, color="#444444")
    fig.tight_layout(rect=(0, .035, 1, .91))
    for suffix in ("png", "svg"):
        fig.savefig(args.report.parent / ("support-fractions." + suffix), dpi=180, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
