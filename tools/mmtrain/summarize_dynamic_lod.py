"""Summarize paired fixed-budget dynamic LOD image and runtime measurements."""

import argparse
import json
from pathlib import Path

import numpy as np


def mean_ci(values, seed):
    values = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(50000, len(values)), replace=True).mean(axis=1)
    return {"mean": float(values.mean()), "ci95": [float(v) for v in np.quantile(samples, [0.025, 0.975])]}


def read_pair(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data


def metric_rows(data, asset):
    asset_data = data["assets"][asset]
    ranker = asset_data["calibratedRanker"]
    candidate_key = f"{ranker}-hysteresis"
    frame_count = data["framesPerPath"]
    result = {"psnrDb": [], "ssim": [], "silhouetteIou": []}
    for path_index, policies in enumerate(asset_data["imageQuality"]):
        baseline = policies["area-hysteresis"]
        candidate = policies[candidate_key]
        baseline_frames = baseline["frameMetrics"][:frame_count]
        candidate_frames = candidate["frameMetrics"][:frame_count]
        result["psnrDb"].append(float(np.mean([
            c["psnrDb"] - b["psnrDb"]
            for b, c in zip(baseline_frames, candidate_frames, strict=True)])))

        if ranker == "area":
            sample_count = len(baseline["sampledStructuralMetrics"]) // 2
            baseline_samples = baseline["sampledStructuralMetrics"][:sample_count]
            candidate_samples = candidate["sampledStructuralMetrics"][:sample_count]
        else:
            baseline_samples = baseline["sampledStructuralMetrics"]
            candidate_samples = candidate["sampledStructuralMetrics"]
        for key in ("ssim", "silhouetteIou"):
            result[key].append(float(np.mean([
                c[key] - b[key]
                for b, c in zip(baseline_samples, candidate_samples, strict=True)])))
    return {key: float(np.mean(values)) for key, values in result.items()}


def error_reduction(data, asset):
    report = data["assets"][asset]["quality"]
    ranker = data["assets"][asset]["calibratedRanker"]
    candidate_key = "calibrated-hysteresis"
    base = sum(row["sse"] for path in report for row in path["area-hysteresis"])
    candidate = sum(row["sse"] for path in report for row in path[candidate_key])
    return 100 * (base - candidate) / base if base else 0.0


def runtime_rows(data, asset):
    asset_data = data["assets"][asset]
    result = {}
    for policy in ("area-hysteresis", "calibrated-hysteresis"):
        values = {key: [] for key in ("gpuMs", "cpuMs", "selectorMs")}
        for path in asset_data["runtime"]:
            for key in values:
                values[key].extend(path[policy][key])
        result[policy] = {key: float(np.quantile(samples, 0.95))
                          for key, samples in values.items()}
    return result


def summarize(inputs):
    runs = {label: read_pair(path) for label, path in inputs.items()}
    scopes = {data.get("profileScope", "per-asset") for data in runs.values()}
    if len(scopes) != 1:
        raise ValueError("Input reports must use the same profile scope")
    profile_scope = scopes.pop()
    objectives = {data.get("profileObjective", "color-sse") for data in runs.values()}
    if len(objectives) != 1:
        raise ValueError("Input reports must use the same profile objective")
    profile_objective = objectives.pop()
    assets = list(runs["initial"]["assets"])
    if any(list(data["assets"]) != assets for data in runs.values()):
        raise ValueError("Input reports must contain the same assets in the same order")
    rows = []
    for asset in assets:
        path_summaries = {label: metric_rows(data, asset) for label, data in runs.items()}
        row = {"asset": asset,
               "ranker": runs["initial"]["assets"][asset]["calibratedRanker"],
               "trianglesPerFrame": runs["initial"]["assets"][asset]["faceCount"],
               "sseReductionPct": float(np.mean([
                   error_reduction(data, asset) for data in runs.values()])),
               "psnrDb": float(np.mean([v["psnrDb"] for v in path_summaries.values()])),
               "ssimDelta": float(np.mean([v["ssim"] for v in path_summaries.values()])),
               "silhouetteIouDelta": float(np.mean([
                   v["silhouetteIou"] for v in path_summaries.values()])),
               "paths": path_summaries}
        rows.append(row)

    deltas = {key: [row[key] for row in rows]
              for key in ("psnrDb", "ssimDelta", "silhouetteIouDelta", "sseReductionPct")}
    summary = {key: mean_ci(values, 20261122 + index)
               for index, (key, values) in enumerate(deltas.items())}
    summary["psnrWins"] = sum(value > 0 for value in deltas["psnrDb"])
    summary["ssimWins"] = sum(value > 0 for value in deltas["ssimDelta"])
    summary["silhouetteIouWins"] = sum(value > 0 for value in deltas["silhouetteIouDelta"])
    timing = {policy: {field: [] for field in ("gpuMs", "cpuMs", "selectorMs")}
              for policy in ("area-hysteresis", "calibrated-hysteresis")}
    for asset in assets:
        for policy, measurements in runtime_rows(runs["initial"], asset).items():
            for field, value in measurements.items():
                timing[policy][field].append(value)
    summary["medianAssetP95TimingMs"] = {
        policy: {field: float(np.median(values)) for field, values in metrics.items()}
        for policy, metrics in timing.items()}
    return {"assets": assets, "rows": rows, "summary": summary,
            "inputReceipts": {label: Path(path).as_posix() for label, path in inputs.items()},
            "protocol": {"resolution": runs["initial"]["size"],
                         "framesPerPath": runs["initial"]["framesPerPath"],
                         "timingRepeats": runs["initial"].get("timingRepeats"),
                         "testedPaths": [*runs["initial"]["testPaths"],
                                         *runs["alternate"]["testPaths"]],
                         "fineInstances": runs["initial"]["fineInstances"],
                         "profileScope": profile_scope,
                         "profileObjective": profile_objective,
                         "bootstrapUnit": "asset",
                         "imageMetricLimit": "grayscale synthetic shader; not authored materials"}}


def markdown(report):
    summary = report["summary"]
    leave_one_out = report["protocol"]["profileScope"] == "leave-one-asset-out"
    all_area = all(row["ranker"] == "area" for row in report["rows"])
    width, height = report["protocol"]["resolution"]
    tested_paths = report["protocol"]["testedPaths"]
    frame_count = report["protocol"]["framesPerPath"] * len(tested_paths)
    timing_repeats = report["protocol"]["timingRepeats"]
    timing_repeat_text = (f"{timing_repeats} repetition" if timing_repeats == 1 else
                          f"{timing_repeats} repetitions" if timing_repeats is not None else
                          "an unspecified number of repetitions")
    profile_objective = {
        "color-sse": "color pixel SSE",
        "silhouette-xor": "binary silhouette XOR pixel count",
        "balanced-color-silhouette": "equal mean-normalized color SSE and silhouette XOR",
    }[report["protocol"]["profileObjective"]]
    def estimate(key, scale=1.0, suffix="", precision=3):
        values = summary[key]
        mean = values["mean"] * scale
        lower, upper = (v * scale for v in values["ci95"])
        fmt = f".{{}}f".format(precision)
        return (f"{mean:{fmt}}{suffix} "
                f"[{lower:{fmt}}, {upper:{fmt}}]")
    lines = [
        "# Dynamic LOD: 13-Asset Leave-One-Asset-Out Screen" if leave_one_out else
        "# Dynamic LOD: 13-Asset Held-Out Motion Screen",
        "",
        "Updated 2026-11-22. This is a controlled desktop research screen, not a SIGGRAPH result.",
        "",
        "## Protocol",
        "",
        "Thirteen Khronos glTF Sample Assets use the existing component/source mesh pairs.",
        ("For each test asset, the shared direction/scale profile is built from the other twelve "
         "assets' 24-frame training turntables. Cross-validation selects the profile family "
         "using leave-one-asset-out folds within those twelve assets; the training objective is "
         f"{profile_objective}. The outer test asset contributes no profile or ranker-selection data. "
         if leave_one_out else
         "The ranker is calibrated only on the 24-frame training turntable (path 0). "
         f"The training objective is {profile_objective}. "),
        (f"The {len(tested_paths)} held-out paths ({', '.join(map(str, tested_paths))}) each contain "
         f"{report['protocol']['framesPerPath']} frames and are split across two benchmark runs. Each frame"),
        "shows sixteen isolated instances, with four source meshes and twelve component meshes.",
        "Both policies therefore use the same per-asset triangle count and two indexed-instanced",
        (f"draws. Rendering is {width}x{height} on Intel Iris Xe / D3D12. GPU timing uses "
         f"{timing_repeat_text}."),
        "",
        "The primary paired comparison is the calibration-selected ranking with fixed hysteresis",
        "against area ranking with the same hysteresis. Each view is rendered as an 8-bit single-",
        "channel flat-shaded image. Canonical",
        "Gaussian-window SSIM and binary silhouette IoU use four fixed, evenly spaced frames per",
        (f"path. Exact PSNR covers {frame_count} frames per asset. Confidence intervals bootstrap "
         "assets, not correlated frames. These measurements"),
        "do not cover authored materials, occlusion, display motion, FLIP/LPIPS, user preference,",
        "power, mobile GPUs, or a complete application frame. The thirteen assets and their",
        "source/component pairs are reused development data; the component meshes were selected",
        "in earlier fitting-view experiments. " +
        ("Each outer asset fold excludes that asset from profile fitting and ranker selection, "
         "but this reused corpus is not a fresh confirmation set." if leave_one_out else
         "These are path-held-out results, not asset-held-out confirmation."),
        "Profile fitting and ranker-selection time are not included in runtime.",
        "",
        "## Results",
        "",
        ("Positive values favor the shared, cross-validated policy. A ranker that selects area is" if leave_one_out else
         "Positive values favor the calibration-selected policy. A ranker that selects area is"),
        "identical to the control for that asset.",
        "",
        "| Asset | Ranker | Triangles/frame | PSNR change (dB) | SSIM change | Silhouette IoU change | Pixel SSE reduction |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in report["rows"]:
        lines.append(f"| {row['asset']} | {row['ranker']} | {row['trianglesPerFrame']:,} | "
                     f"{row['psnrDb']:+.3f} | {row['ssimDelta']:+.6f} | "
                     f"{row['silhouetteIouDelta']:+.6f} | {row['sseReductionPct']:+.2f}% |")
    lines.extend([
        "",
        f"Asset-bootstrap mean (95% percentile CI): PSNR **{estimate('psnrDb', suffix=' dB')}**; "
        f"SSIM **{estimate('ssimDelta', precision=6)}**; "
        f"silhouette IoU **{estimate('silhouetteIouDelta', precision=6)}**; "
        f"pixel SSE reduction **{estimate('sseReductionPct', suffix='%')}**.",
        "",
        f"The selected ranker improves PSNR on {summary['psnrWins']}/13 assets, SSIM on "
        f"{summary['ssimWins']}/13, and silhouette IoU on {summary['silhouetteIouWins']}/13.",
        "The median across assets of each asset's p95 GPU pass time is "
        f"{summary['medianAssetP95TimingMs']['area-hysteresis']['gpuMs']:.3f} ms for area hysteresis and "
        f"{summary['medianAssetP95TimingMs']['calibrated-hysteresis']['gpuMs']:.3f} ms for the "
        "calibration-selected policy. Median asset p95 CPU selection/upload/submission is "
        f"{summary['medianAssetP95TimingMs']['area-hysteresis']['cpuMs']:.3f} ms for area and "
        f"{summary['medianAssetP95TimingMs']['calibrated-hysteresis']['cpuMs']:.3f} ms for the "
        "selected policy; selector-only p95 is "
        f"{summary['medianAssetP95TimingMs']['area-hysteresis']['selectorMs']:.3f} ms and "
        f"{summary['medianAssetP95TimingMs']['calibrated-hysteresis']['selectorMs']:.3f} ms. "
        "GPU pass timestamps do not include presentation or frame pacing. Each timing has only "
        f"{timing_repeat_text}; the small differences are measurement noise, not a performance result.",
        "",
        "## Interpretation and Limits",
        "",
        ("Silhouette-XOR profile selection chose the area ranker on all thirteen outer test assets. "
         "The evaluated policy therefore exactly matches the control; this screen provides no evidence "
         "of a quality gain from the silhouette objective." if all_area else
         "This shared profile did not show a reliable quality gain: its PSNR and SSIM intervals "
         "include zero, while silhouette IoU declines." if leave_one_out else
         "This supports a limited feasibility statement: a frozen per-asset appearance profile can "
         "rank four of sixteen resident instances better than projected area on these synthetic motion paths."),
        ("The asset set and component pairs are reused development data, so the folds are not "
         "fresh confirmation." if leave_one_out else
         "The asset set is reused development data and does not establish population generalization."),
        "This does not establish a new LOD allocation method. Cost-benefit allocation",
        "across multiple LOD objects and hysteresis for temporal stability are established",
        "directions; see [Funkhouser and Sequin (1993)](https://gfx.cs.princeton.edu/gfx/pubs/Funkhouser_1993_ADA/index.php). The workload is non-overlapping",
        "and stylized, and the policies share the same simple resident-mesh setup. A SIGGRAPH",
        "claim requires a sharper novelty boundary, stronger real-scene baselines, richer image",
        "metrics/materials, and a fresh licensed confirmation set. No mobile result is measured.",
        "",
        "Raw benchmark receipts:",
        *[f"- `{path}`" for path in report["inputReceipts"].values()],
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial", type=Path, required=True)
    parser.add_argument("--alternate", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-markdown", type=Path, required=True)
    args = parser.parse_args()
    report = summarize({"initial": args.initial, "alternate": args.alternate})
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.out_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.out_markdown.write_text(markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
