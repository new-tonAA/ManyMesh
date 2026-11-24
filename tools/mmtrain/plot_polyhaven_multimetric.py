#!/usr/bin/env python3
"""Create a multi-metric forest plot from the frozen Poly Haven receipts."""

import argparse
import hashlib
import html
import json
from pathlib import Path


METRICS = (
    ("psnr_db", "PSNR", "dB", True, 3),
    ("ssim", "SSIM", "score", True, 3),
    ("flip", "LDR-FLIP", "score", False, 3),
    ("silhouette_xor_fraction", "Silhouette XOR", "fraction", False, 3),
    ("lpips_squeeze", "LPIPS (SqueezeNet)", "score", False, 3),
)
CONDITIONS = (
    ("native", "qem_preserve_border", "Native · QEM", "qem", "circle"),
    ("native", "meshoptimizer_lock_border", "Native · meshoptimizer", "meshoptimizer", "circle"),
    ("msaa4", "qem_preserve_border", "4× MSAA · QEM", "qem", "square"),
    ("msaa4", "meshoptimizer_lock_border", "4× MSAA · meshoptimizer", "meshoptimizer", "square"),
)
COLORS = {"qem": "#b45309", "meshoptimizer": "#176b87"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def effect(entry, lower_is_better):
    """Return the candidate-minus-control change with positive favoring ManyMesh."""
    mean = entry["group_mean_delta"]
    low, high = entry["percentile_95_ci"]
    if lower_is_better:
        return -mean, -high, -low
    return mean, low, high


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metrics", type=Path, default=Path("tools/mmtrain/polyhaven_quality_metrics_20261124.json"))
    parser.add_argument("--lpips", type=Path, default=Path("tools/mmtrain/polyhaven_lpips_supplement_20261125.json"))
    parser.add_argument("--multiplicity", type=Path, default=Path("tools/mmtrain/polyhaven_multiplicity_audit_20261125.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/manymesh/polyhaven-quality-metrics.svg"))
    args = parser.parse_args()

    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    lpips = json.loads(args.lpips.read_text(encoding="utf-8"))
    multiplicity = json.loads(args.multiplicity.read_text(encoding="utf-8"))
    if metrics["status"] != "complete" or lpips["status"] != "complete" or multiplicity["status"] != "complete":
        raise SystemExit("All input receipts must have status=complete")
    if metrics["assets"] != 21 or metrics["uncertainty_groups"] != 16:
        raise SystemExit("Unexpected baseline cohort size")
    if lpips["original_metrics_sha256"] != sha256(args.metrics):
        raise SystemExit("LPIPS supplement does not reference this metrics receipt")
    if multiplicity["source_metrics_sha256"] != sha256(args.metrics) or multiplicity["endpoints"] != 16:
        raise SystemExit("Multiplicity audit does not match this primary metrics receipt")
    multiplicity_by_endpoint = {
        (entry["mode"], entry["control"], entry["metric"]): entry
        for entry in multiplicity["results"]
    }

    # Each panel uses its native metric units. Rows must not be compared by length.
    panel_values = []
    for key, label, unit, higher_is_better, digits in METRICS:
        values = []
        for sampling, baseline, condition, color_key, marker in CONDITIONS:
            if key == "lpips_squeeze":
                entry = lpips["paired_group_deltas_manymesh_minus_control"][sampling][baseline]
                mean, low, high = effect(entry, True)
            else:
                entry = multiplicity_by_endpoint[(sampling, baseline, key)]
                mean = entry["manymesh_improvement_mean"]
                low, high = entry["simultaneous_max_t_95_ci"]
            values.append({"condition": condition, "color": COLORS[color_key], "marker": marker,
                           "mean": mean, "low": low, "high": high})
        panel_values.append((key, label, unit, digits, values))

    width, height = 1260, 920
    x0, x1 = 470, 970
    plot_width = x1 - x0
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Matched-face quality comparison across five image metrics</title>',
        '<desc id="desc">Direction-adjusted changes for ManyMesh versus QEM and meshoptimizer across 21 models. Positive favors ManyMesh. The four primary metrics and post-hoc LPIPS supplement all favor the controls.</desc>',
        f'<metadata>metrics_sha256={sha256(args.metrics)};lpips_sha256={sha256(args.lpips)};multiplicity_sha256={sha256(args.multiplicity)}</metadata>',
        '<rect width="100%" height="100%" fill="#f7f8fa"/>',
        '<text x="40" y="42" font-family="Arial,sans-serif" font-size="25" font-weight="700" fill="#182230">Matched-face image quality favors deterministic controls</text>',
        '<text x="40" y="72" font-family="Arial,sans-serif" font-size="14" fill="#526071">Direction-adjusted change; positive favors ManyMesh. Primary metrics use familywise 95% intervals.</text>',
    ]
    # Legend: comparator color and sampling marker are encoded independently.
    out += [
        '<circle cx="55" cy="103" r="6" fill="#b45309"/><text x="68" y="108" font-family="Arial,sans-serif" font-size="13" fill="#263445">QEM</text>',
        '<circle cx="135" cy="103" r="6" fill="#176b87"/><text x="148" y="108" font-family="Arial,sans-serif" font-size="13" fill="#263445">meshoptimizer</text>',
        '<circle cx="300" cy="103" r="6" fill="#526071"/><text x="313" y="108" font-family="Arial,sans-serif" font-size="13" fill="#263445">Native</text>',
        '<rect x="385" y="97" width="12" height="12" fill="#526071"/><text x="405" y="108" font-family="Arial,sans-serif" font-size="13" fill="#263445">4× MSAA</text>',
    ]

    panel_y0, panel_h = 128, 143
    for panel_index, (key, label, unit, digits, values) in enumerate(panel_values):
        top = panel_y0 + panel_index * panel_h
        bottom = top + panel_h - 18
        all_values = [x for v in values for x in (v["low"], v["high"])]
        extent = max(abs(x) for x in all_values) * 1.18
        extent = extent or 1e-12
        sx = lambda value: x0 + (value + extent) / (2 * extent) * plot_width
        out.append(f'<rect x="20" y="{top}" width="1220" height="{panel_h - 2}" rx="7" fill="{"#fff8ee" if key == "lpips_squeeze" else "#ffffff"}"/>')
        out.append(f'<text x="40" y="{top + 25}" font-family="Arial,sans-serif" font-size="17" font-weight="700" fill="#182230">{html.escape(label)}</text>')
        out.append(f'<text x="40" y="{top + 45}" font-family="Arial,sans-serif" font-size="12" fill="#647184">Improvement ({html.escape(unit)})</text>')
        if key == "lpips_squeeze":
            out.append(f'<text x="40" y="{top + 66}" font-family="Arial,sans-serif" font-size="11" fill="#8a4b08">Post-hoc; same cohort</text>')
        for value, tick_label in ((-extent, "−"), (0, "0"), (extent, "+")):
            xpos = sx(value)
            stroke = "#263445" if value == 0 else "#d9dee6"
            sw = 2 if value == 0 else 1
            out.append(f'<line x1="{xpos:.2f}" y1="{top + 12}" x2="{xpos:.2f}" y2="{bottom - 19}" stroke="{stroke}" stroke-width="{sw}"/>')
            out.append(f'<text x="{xpos:.2f}" y="{bottom - 3}" text-anchor="middle" font-family="Arial,sans-serif" font-size="11" fill="#647184">{tick_label}</text>')
        for row, v in enumerate(values):
            y = top + 24 + row * 23
            out.append(f'<text x="430" y="{y + 4}" text-anchor="end" font-family="Arial,sans-serif" font-size="12" fill="#263445">{html.escape(v["condition"])}</text>')
            out.append(f'<line x1="{sx(v["low"]):.2f}" y1="{y}" x2="{sx(v["high"]):.2f}" y2="{y}" stroke="{v["color"]}" stroke-width="3" stroke-linecap="round"/>')
            out.append(f'<line x1="{sx(v["low"]):.2f}" y1="{y - 5}" x2="{sx(v["low"]):.2f}" y2="{y + 5}" stroke="{v["color"]}" stroke-width="1.5"/>')
            out.append(f'<line x1="{sx(v["high"]):.2f}" y1="{y - 5}" x2="{sx(v["high"]):.2f}" y2="{y + 5}" stroke="{v["color"]}" stroke-width="1.5"/>')
            if v["marker"] == "circle":
                out.append(f'<circle cx="{sx(v["mean"]):.2f}" cy="{y}" r="5.3" fill="{v["color"]}" stroke="#ffffff" stroke-width="1.5"/>')
            else:
                out.append(f'<rect x="{sx(v["mean"]) - 4.8:.2f}" y="{y - 4.8}" width="9.6" height="9.6" fill="{v["color"]}" stroke="#ffffff" stroke-width="1.2"/>')
            out.append(f'<text x="990" y="{y + 4}" font-family="Arial,sans-serif" font-size="10" fill="#263445">{v["mean"]:+.{digits}g} [{v["low"]:+.{digits}g}, {v["high"]:+.{digits}g}]</text>')
        out.append(f'<text x="{x0}" y="{bottom + 13}" font-family="Arial,sans-serif" font-size="10" fill="#647184">worse</text>')
        out.append(f'<text x="{x1}" y="{bottom + 13}" text-anchor="end" font-family="Arial,sans-serif" font-size="10" fill="#647184">better</text>')

    out += [
        '<text x="40" y="862" font-family="Arial,sans-serif" font-size="12" fill="#526071">21 models; 16 source groups. Primary metric intervals are familywise 95% max-t; native units differ across panels.</text>',
        '<text x="40" y="883" font-family="Arial,sans-serif" font-size="12" fill="#526071">LPIPS uses an individual 95% interval as a post-hoc metric on this same cohort; it is not independent or human-preference evidence.</text>',
        '</svg>',
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(("\n".join(out) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
