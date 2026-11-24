"""Add LPIPS scores to the frozen Poly Haven matched-face image cohort."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/mmtrain"))
sys.path.insert(0, str(ROOT / "tools/mmmetrics"))

from bench_appearance_controls import (  # noqa: E402
    ARMS, DISTANCES, HEIGHT, MODES, WIDTH, camera_eyes, load_inputs,
)
from bench_bevy_smaa import score  # noqa: E402
from bench_component_gpu import Offscreen, linear_gray_to_srgb, select_adapter  # noqa: E402
from bench_contour_priority_aa import bind_camera, upload  # noqa: E402
from preflight_appearance_meshes import digest  # noqa: E402


BACKBONE_NAME = "squeezenet1_1-b8a52dc0.pth"
BACKBONE_SHA256 = "b8a52dc049b60e4b6ab68ad0df457362afab8b6304b2febdc1650a5dab4d7e7b"
CALIBRATION_SHA256 = "4a5350f23600cb79923ce65bb07cbf57dca461329894153e05a1346bd531cf76"
REPLAY_TOLERANCE = 1e-6
IMAGE_FIELDS = ("psnr_db", "ssim", "flip", "silhouette_xor_fraction")
BOOTSTRAP_SAMPLES = 10000
BOOTSTRAP_SEED = 20261125


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def compare_value(actual, expected):
    if actual is None or expected is None:
        return 0.0 if actual is expected else float("inf")
    return abs(float(actual) - float(expected))


def metric_tensor(torch, image):
    rgb = np.repeat(image[..., None], 3, axis=-1).astype(np.float32) / 255.0
    return torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0) * 2.0 - 1.0


def lpips_value(torch, model, reference, candidate):
    with torch.inference_mode():
        return float(model(metric_tensor(torch, reference),
                           metric_tensor(torch, candidate)).item())


def score_asset(slug, spec, args, torch, lpips_model, adapter):
    directory = ROOT / spec["geometry_dir"]
    frozen = spec["frozen_exports"]
    geometries = load_inputs(directory, frozen, None)
    raw_path = args.raw_dir / slug / "quality.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw_receipt = next(row for row in json.loads(
        args.cohort_receipt.read_text(encoding="utf-8"))["assets"]
        if row["asset"] == slug)
    if digest(raw_path) != raw_receipt["raw_sha256"]:
        raise ValueError(f"Original renderer receipt hash differs: {slug}")

    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = Offscreen(device, WIDTH, HEIGHT, 1, False)
    high = Offscreen(device, WIDTH * 2, HEIGHT * 2, 1, False)
    meshes = {name: upload(device, *geometry) for name, geometry in geometries.items()}
    scored_views = []
    max_delta = 0.0
    exact = True
    for index, (view, distance, eye) in enumerate(camera_eyes()):
        camera_buffers = [bind_camera(raster, eye), bind_camera(high, eye)]
        _, high_image = high.run(meshes["reference"], "msaa4", 1, True)
        merged = high_image.reshape(HEIGHT, 2, WIDTH, 2).mean(axis=(1, 3))
        reference = linear_gray_to_srgb(merged)
        per_mode = {}
        original_view = raw["views"][index]
        if (original_view["view"] != view or
                original_view["distance"] != distance):
            raise ValueError(f"Frozen camera schedule changed for {slug}/{index}")
        for label, mode in MODES:
            per_arm = {}
            for arm, mesh in meshes.items():
                _, gray = raster.run(mesh, mode, 1, True)
                image = linear_gray_to_srgb(gray)
                base = score(reference, image)
                base["silhouette_xor_fraction"] = float(
                    np.mean((gray > 0) != (merged > 0)))
                expected = original_view["quality"][arm][label]
                deltas = {field: compare_value(base[field], expected[field])
                          for field in IMAGE_FIELDS}
                view_max = max(deltas.values())
                max_delta = max(max_delta, view_max)
                if view_max > REPLAY_TOLERANCE:
                    exact = False
                per_arm[arm] = {
                    "lpips_squeeze": lpips_value(torch, lpips_model, reference, image),
                    "baseline_replay_max_abs_delta": view_max,
                }
            per_mode[label] = per_arm
        for buffer in camera_buffers:
            buffer.destroy()
        scored_views.append({"view": view, "distance": distance,
                             "lpips": per_mode})
        if (index + 1) % 6 == 0:
            print(slug, f"{index + 1}/24 views", flush=True)
    result = {"asset": slug, "class": spec["class"],
              "uncertainty_group": spec["uncertainty_group"],
              "source_sha256": spec["source_sha256"],
              "source_faces": frozen["source_faces"],
              "control_faces": frozen["control_target_faces"],
              "geometry_sha256": frozen["obj_exports_sha256"],
              "original_raw_sha256": raw_receipt["raw_sha256"],
              "baseline_replay": {"verified": exact,
                                  "tolerance": REPLAY_TOLERANCE,
                                  "max_abs_delta": max_delta,
                                  "fields": list(IMAGE_FIELDS)},
              "views": scored_views}
    per_asset_path = args.out_dir / f"{slug}.json"
    write_json(per_asset_path, result)
    if not exact:
        raise RuntimeError(f"Baseline metric replay mismatch for {slug}; LPIPS excluded")
    return result


def summarize(rows, manifest):
    asset_summaries = []
    for row in rows:
        means = {}
        for label, _ in MODES:
            means[label] = {}
            for arm in ("reference", *ARMS):
                values = [view["lpips"][label][arm]["lpips_squeeze"]
                          for view in row["views"]]
                means[label][arm] = float(np.mean(values))
        deltas = {label: {arm: means[label]["manymesh"] - means[label][arm]
                          for arm in ("qem_preserve_border", "meshoptimizer_lock_border")}
                  for label, _ in MODES}
        asset_summaries.append({"asset": row["asset"],
                                "uncertainty_group": row["uncertainty_group"],
                                "mean_lpips": means, "delta_manymesh_minus_control": deltas})
    groups = sorted({row["uncertainty_group"] for row in asset_summaries})
    if len(groups) != 16:
        raise ValueError(f"Frozen cohort has {len(groups)} uncertainty groups, expected 16")
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    paired = {}
    for label, _ in MODES:
        paired[label] = {}
        for arm in ("qem_preserve_border", "meshoptimizer_lock_border"):
            by_group = np.asarray([
                np.mean([row["delta_manymesh_minus_control"][label][arm]
                         for row in asset_summaries if row["uncertainty_group"] == group])
                for group in groups], dtype=np.float64)
            samples = rng.integers(0, len(by_group),
                                   size=(BOOTSTRAP_SAMPLES, len(by_group)))
            means = by_group[samples].mean(axis=1)
            paired[label][arm] = {
                "group_mean_delta": float(by_group.mean()),
                "percentile_95_ci": [float(np.quantile(means, .025)),
                                     float(np.quantile(means, .975))],
                "groups": len(by_group),
                "groups_won_by_manymesh": int(np.count_nonzero(by_group < 0)),
                "groups_tied": int(np.count_nonzero(by_group == 0)),
            }
    return {"asset_summaries": asset_summaries,
            "paired_group_deltas_manymesh_minus_control": paired,
            "bootstrap": {"unit": "source-collection group",
                          "samples": BOOTSTRAP_SAMPLES,
                          "seed": BOOTSTRAP_SEED,
                          "interval": "paired percentile 95% interval"}}


def write_markdown(path, receipt):
    lines = [
        "# Poly Haven matched-face LPIPS supplement", "",
        "Completed 2026-11-25. This post-hoc metric supplement reuses the",
        "already-scored 21-model fixed-view cohort; it is descriptive, not",
        "independent or confirmatory held-out evidence. Lower LPIPS is better.", "",
        "The PSNR, SSIM, LDR-FLIP, and silhouette-XOR replay matched every",
        "original per-view score within the frozen `1e-6` tolerance.", "",
        "ManyMesh minus control is reported below. Negative values favor",
        "ManyMesh on LPIPS; intervals bootstrap the 16 source-collection groups.", "",
        "| Sampling | Control | Mean paired delta | 95% group-bootstrap CI | Groups won / 16 |",
        "|---|---|---:|---:|---:|",
    ]
    paired = receipt["paired_group_deltas_manymesh_minus_control"]
    for label, _ in MODES:
        for arm, name in (("qem_preserve_border", "Border-preserving QEM"),
                          ("meshoptimizer_lock_border", "meshoptimizer LockBorder")):
            row = paired[label][arm]
            ci = row["percentile_95_ci"]
            lines.append(f"| {label} | {name} | {row['group_mean_delta']:+.8f} | "
                         f"[{ci[0]:+.8f}, {ci[1]:+.8f}] | "
                         f"{row['groups_won_by_manymesh']}/{row['groups']} |")
    lines += ["", "## Limits", "",
              "This reuses assets and fixed views already evaluated with other",
              "metrics. LPIPS is not a user study and does not establish",
              "perceptual preference. It cannot by itself reopen the tested",
              "ManyMesh cut or advance the unrun CUDA placement control.", "",
              "See the [frozen protocol](POLYHAVEN_LPIPS_SUPPLEMENT_20261125.md),",
              "[machine-readable receipt](polyhaven_lpips_supplement_20261125.json),",
              "and [original matched-face screen](POLYHAVEN_QUALITY_SCREEN_20261124.md).", ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cohort-receipt", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--torch-hub", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--asset", action="append")
    args = parser.parse_args()
    started = time.perf_counter()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cohort = json.loads(args.cohort_receipt.read_text(encoding="utf-8"))
    metrics_receipt = json.loads(args.metrics.read_text(encoding="utf-8"))
    manifest_sha = digest(args.manifest)
    if cohort.get("status") != "complete" or cohort.get("manifest_sha256") != manifest_sha:
        parser.error("The original cohort receipt is incomplete or uses a different manifest")
    if metrics_receipt.get("manifest_sha256") != manifest_sha:
        parser.error("The original aggregate metrics use a different frozen cohort")
    scorer = ROOT / "tools/mmtrain/bench_appearance_controls.py"
    if cohort.get("scorer_sha256") != digest(scorer):
        parser.error("The checked-in scorer differs from the original frozen screen")
    selected = list(manifest["assets"])
    if args.asset:
        requested = set(args.asset)
        selected = [slug for slug in selected if slug in requested]
        if set(selected) != requested:
            parser.error("Requested asset is absent from the frozen cohort")
    for slug in selected:
        row = next((item for item in cohort["assets"] if item["asset"] == slug), None)
        if not row or row.get("status") != "scored":
            parser.error(f"Missing original completed score: {slug}")
        raw = args.raw_dir / slug / "quality.json"
        if not raw.is_file() or digest(raw) != row.get("raw_sha256"):
            parser.error(f"Original raw receipt hash mismatch: {slug}")
        spec = manifest["assets"][slug]
        directory = ROOT / spec["geometry_dir"]
        for name, expected in spec["frozen_exports"]["obj_exports_sha256"].items():
            if digest(directory / name) != expected:
                parser.error(f"Frozen geometry hash mismatch: {slug}/{name}")

    import lpips
    import torch

    if torch.cuda.is_available():
        parser.error("This supplement is pinned to CPU LPIPS inference")
    torch.set_num_threads(2)
    torch_hub = args.torch_hub.resolve()
    backbone = torch_hub / "checkpoints" / BACKBONE_NAME
    calibration = Path(lpips.__file__).parent / "weights" / "v0.1" / "squeeze.pth"
    if digest(backbone) != BACKBONE_SHA256:
        parser.error("Cached official SqueezeNet checkpoint hash mismatch")
    if digest(calibration) != CALIBRATION_SHA256:
        parser.error("LPIPS calibration checkpoint hash mismatch")
    torch.hub.set_dir(str(torch_hub))
    model = lpips.LPIPS(net="squeeze", version="0.1", pretrained=True,
                        pnet_rand=False, verbose=False).eval()
    adapter = select_adapter("Intel(R) Iris(R) Xe Graphics", "D3D12")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print("adapter", dict(adapter.info), flush=True)
    results = []
    for index, slug in enumerate(selected, 1):
        result = score_asset(slug, manifest["assets"][slug], args, torch, model, adapter)
        results.append(result)
        print(index, slug, "verified", f"max delta {result['baseline_replay']['max_abs_delta']:.3g}",
              flush=True)

    if len(selected) != len(manifest["assets"]):
        print("Partial asset run; no cohort aggregate emitted", flush=True)
        return
    summary = summarize(results, manifest)
    receipt = {
        "schema": 1,
        "status": "complete",
        "scope": "post-hoc LPIPS metric supplement on an already-scored fixed-view cohort",
        "quality_scored": True,
        "manifest_sha256": manifest_sha,
        "cohort_receipt_sha256": digest(args.cohort_receipt),
        "original_metrics_sha256": digest(args.metrics),
        "scorer_sha256": digest(scorer),
        "script_sha256": digest(Path(__file__)),
        "support_script_sha256": {
            name: digest(ROOT / "tools/mmtrain" / name) for name in (
                "bench_appearance_controls.py", "bench_component_gpu.py",
                "bench_contour_priority_aa.py", "bench_bevy_smaa.py",
                "preflight_appearance_meshes.py")},
        "adapter": dict(adapter.info),
        "packages": {name: importlib.metadata.version(name) for name in (
            "numpy", "torch", "torchvision", "wgpu", "lpips",
            "flip-evaluator", "scikit-image")},
        "lpips": {"package": "lpips 0.1.4", "network": "calibrated SqueezeNet v0.1",
                  "input": "8-bit sRGB grayscale replicated to RGB, mapped to [-1,1]",
                  "backbone_sha256": digest(backbone),
                  "calibration_sha256": digest(calibration),
                  "lower_is_better": True},
        "rendering": {"resolution": [WIDTH, HEIGHT], "view_distance_pairs_per_asset": 24,
                      "reference": "source at 2x with 4x MSAA, linear box resolve",
                      "candidate_modes": [label for label, _ in MODES],
                      "arms": ["reference", *ARMS]},
        "replay_tolerance": REPLAY_TOLERANCE,
        "baseline_replay_verified": all(row["baseline_replay"]["verified"] for row in results),
        "assets": results,
        **summary,
        "elapsed_seconds": time.perf_counter() - started,
    }
    output = ROOT / "tools/mmtrain/polyhaven_lpips_supplement_20261125.json"
    report = ROOT / "tools/mmtrain/POLYHAVEN_LPIPS_SUPPLEMENT_RESULTS_20261125.md"
    write_json(output, receipt)
    write_markdown(report, receipt)
    print("wrote", output.relative_to(ROOT), flush=True)
    print("wrote", report.relative_to(ROOT), flush=True)


if __name__ == "__main__":
    main()
