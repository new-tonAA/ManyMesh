"""Compare QEM, vendored meshoptimizer, and rank-8 output at matched faces."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys

import numpy as np
import scipy
import torch
from PIL import Image, ImageDraw

from cluster_decoder import Mesh, Model, decode
from cluster_decoder_quality import ImageMetrics, render
from cluster_decoder_surface_quality import surface_metrics
from fit_cluster_decoder import load_pair
from make_refinement_pairs import view_basis


IMAGE_KEYS = ("mse", "ssim", "flip", "lpips_squeeze", "silhouette_xor_fraction", "coverage_mae")
SURFACE_KEYS = ("chamfer_l1_mean", "chamfer_l2_squared_mean", "bidirectional_distance_p95",
                "bidirectional_distance_max_sampled", "normal_consistency_absdot")


def validation_decoder(pair, fit_root, quality_root, file_id):
    with np.load(fit_root / "fixed" / "model.npz", allow_pickle=False) as archive:
        model = Model(archive["weights"], float(archive["max_offset"]))
    sidecar = quality_root / f"validation-{file_id}" / f"{file_id}-fixed.sidecar"
    mesh = Mesh(pair["positions"], pair["triangles"], pair["face_clusters"])
    candidate, _ = decode(mesh, model, sidecar, len(mesh.triangles))
    return candidate.positions, candidate.triangles


def asset_metrics(reference, geometry, metric, views, size, samples, seed):
    per_view = []
    for view in range(views):
        basis = view_basis(view, views)
        ref_image, ref_coverage = render(*reference, basis, size, samples)
        image, coverage = render(*geometry, basis, size, samples)
        union = (ref_coverage > 0) | (coverage > 0)
        values = metric(ref_image / 255., image / 255., union)
        values.update({
            "silhouette_xor_fraction": float(np.mean((ref_coverage > 0) != (coverage > 0))),
            "coverage_mae": float(np.mean(np.abs(ref_coverage - coverage))),
        })
        per_view.append(values)
    mean = {key: float(np.mean([row[key] for row in per_view])) for key in IMAGE_KEYS}
    mse = mean["mse"]
    mean["psnr_db"] = None if mse == 0 else float(-10 * np.log10(mse))
    return mean, per_view


def paired_summary(records, bootstrap_count=2000, seed=20261121):
    summary = {}
    methods = ("qem", "meshoptimizer", "rank8_fixed")
    comparisons = (("meshoptimizer", "qem"), ("rank8_fixed", "qem"),
                   ("rank8_fixed", "meshoptimizer"))
    metrics = (*IMAGE_KEYS, "psnr_db", *SURFACE_KEYS)
    for split in ("train", "validation"):
        paired = [row for row in records if row["split"] == split and
                  all(row.get("methods", {}).get(method) is not None for method in methods)]
        section = {"all_three_paired_assets": len(paired), "methods": {}, "paired_deltas": {}}
        for method in methods:
            section["methods"][method] = {
                key: float(np.mean([row["methods"][method][key] for row in paired]))
                for key in metrics
            } if paired else {}
        for pair_index, (candidate, baseline) in enumerate(comparisons):
            for metric_index, key in enumerate(metrics):
                values = []
                for row in paired:
                    delta = row["methods"][candidate][key] - row["methods"][baseline][key]
                    if delta is not None:
                        values.append(delta)
                values = np.asarray(values, dtype=np.float64)
                label = f"{candidate}_minus_{baseline}:{key}"
                if not len(values):
                    section["paired_deltas"][label] = None
                    continue
                rng = np.random.default_rng(seed + pair_index * 1000 + metric_index +
                                            (10000 if split == "validation" else 0))
                boot = np.empty(bootstrap_count, dtype=np.float64)
                for index in range(bootstrap_count):
                    boot[index] = rng.choice(values, len(values), replace=True).mean()
                section["paired_deltas"][label] = {
                    "mean": float(values.mean()),
                    "bootstrap_95_percentile_ci": [float(x) for x in np.quantile(boot, (.025, .975))],
                    "assets_positive": int(np.count_nonzero(values > 0)),
                    "positive_delta_is_better": key == "psnr_db" or key == "normal_consistency_absdot",
                }
        summary[split] = section
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, action="append", required=True)
    parser.add_argument("--meshopt", type=Path, required=True,
                        help="folder containing meshoptimizer baseline manifest and NPZ meshes")
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--quality", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--views", type=int, default=12)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--surface-samples", type=int, default=20000)
    args = parser.parse_args()
    if args.views < 2 or not 32 <= args.size <= 1024 or args.samples not in (1, 2, 4):
        parser.error("Invalid image evaluation budget")
    args.out.mkdir(parents=True, exist_ok=True)
    meshopt_manifest_path = args.meshopt / "manifest.json"
    meshopt_report = json.loads(meshopt_manifest_path.read_text(encoding="utf-8"))
    meshopt_rows = {(r["split"], r["file_id"]): r for r in meshopt_report["records"]}
    fit_report = json.loads((args.fit / "report.json").read_text(encoding="utf-8"))
    fit_rows = {r["file_id"]: r for r in fit_report["modes"]["fixed"]["records"]}
    decoder_report = json.loads((args.quality / "report.json").read_text(encoding="utf-8"))
    decoder_rows = {(r["split"], r["file_id"]): r for r in decoder_report["records"]}
    metric = ImageMetrics()
    report = {
        "scope": "Frozen development comparison; QEM/meshoptimizer/rank-8 at matched final face count",
        "geometry": "Vendored meshoptimizer 0.18.1 WASM simplify with LockBorder; float32 positions",
        "image_protocol": {"views": args.views, "size": args.size,
                           "box_samples_per_pixel": args.samples ** 2,
                           "flat_shading": True, "metrics": metric.settings},
        "surface_protocol": {"samples_per_direction": args.surface_samples,
                             "method": "Area-uniform samples; nearest sampled-point-cloud distances"},
        "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                    "scipy": scipy.__version__, "torch": torch.__version__},
        "inputs": {"meshopt_manifest_sha256": hashlib.sha256(meshopt_manifest_path.read_bytes()).hexdigest(),
                   "fit_report_sha256": hashlib.sha256((args.fit / "report.json").read_bytes()).hexdigest(),
                   "decoder_report_sha256": hashlib.sha256((args.quality / "report.json").read_bytes()).hexdigest()},
        "records": [],
    }
    panels = []
    for manifest_path in args.pairs:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if any(r["source"]["split"] not in ("train", "validation") for r in manifest["records"]):
            raise ValueError("Final test geometry is refused by this comparison")
        for row in manifest["records"]:
            source = row["source"]
            key = (source["split"], source["file_id"])
            result = {"split": key[0], "file_id": key[1], "source_sha256": source["sha256"],
                      "preparation_status": row["status"], "meshoptimizer_status": None,
                      "decoder_status": None, "triangle_count": None, "methods": {}}
            if row["status"] != "prepared":
                result["reason"] = row["reason"]
                report["records"].append(result)
                continue
            pair = load_pair(manifest_path.parent, row)
            baseline = meshopt_rows.get(key, {})
            result["meshoptimizer_status"] = baseline.get("status", "missing")
            result["decoder_status"] = decoder_rows.get(key, {}).get("decode_status", {}).get("fixed", "missing")
            if baseline.get("status") != "usable":
                report["records"].append(result)
                continue
            if baseline.get("target_triangles") != len(pair["triangles"]):
                result["meshoptimizer_status"] = "face-count mismatch"
                report["records"].append(result)
                continue
            with np.load(args.meshopt / f"{key[0]}-{key[1]}.npz", allow_pickle=False) as archive:
                meshopt_geometry = (archive["positions"], archive["triangles"])
            variants = {"qem": (pair["positions"], pair["triangles"]),
                        "meshoptimizer": meshopt_geometry}
            if key[0] == "train":
                fit_row = fit_rows[key[1]]
                if fit_row["status"] == "decoded":
                    path = args.fit / "fixed" / f"{key[1]}-decoded.npz"
                    with np.load(path, allow_pickle=False) as archive:
                        variants["rank8_fixed"] = (archive["positions"], archive["triangles"])
            elif result["decoder_status"] == "decoded":
                variants["rank8_fixed"] = validation_decoder(pair, args.fit, args.quality, key[1])
            result["triangle_count"] = len(pair["triangles"])
            for method_name, geometry in variants.items():
                image_mean, per_view = asset_metrics(
                    (pair["source_positions"], pair["source_triangles"]), geometry,
                    metric, args.views, args.size, args.samples, key[1])
                surface = surface_metrics(
                    (pair["source_positions"], pair["source_triangles"]), geometry,
                    args.surface_samples, key[1])
                result["methods"][method_name] = image_mean | surface
                if method_name == "qem":
                    result["per_view"] = {method_name: per_view}
                else:
                    result.setdefault("per_view", {})[method_name] = per_view
            report["records"].append(result)
            if key[0] == "validation":
                folder = args.out / f"validation-{key[1]}"
                folder.mkdir(exist_ok=True)
                views = [render(pair["source_positions"], pair["source_triangles"], view_basis(0, args.views),
                                args.size, args.samples)[0]]
                for method_name in ("qem", "meshoptimizer", "rank8_fixed"):
                    if method_name in variants:
                        views.append(render(*variants[method_name], view_basis(0, args.views),
                                            args.size, args.samples)[0])
                panel = Image.new("RGB", (args.size * len(views), args.size + 32), "#20252b")
                draw = ImageDraw.Draw(panel)
                names = ("reference", "qem", "meshoptimizer", "rank8_fixed")
                for column, (name, image) in enumerate(zip(names, views)):
                    draw.text((column * args.size + 4, 5), f"{key[1]} | {name}", fill="white")
                    panel.paste(Image.fromarray(image), (column * args.size, 32))
                panels.append(panel)
            (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(f"{key[0]} {key[1]}: {','.join(variants)} at {len(pair['triangles'])} faces", flush=True)
    report["paired_summary"] = paired_summary(report["records"])
    (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if panels:
        sheet = Image.new("RGB", (panels[0].width, sum(p.height for p in panels)), "black")
        y = 0
        for panel in panels:
            sheet.paste(panel, (0, y))
            y += panel.height
        sheet.save(args.out / "validation-paired.png")


if __name__ == "__main__":
    main()
