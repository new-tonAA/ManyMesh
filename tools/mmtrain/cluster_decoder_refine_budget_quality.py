"""Compare budgeted decoder refinement with meshoptimizer at the same face count."""

import argparse
import hashlib
import json
from pathlib import Path
import platform

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
METRIC_KEYS = (*IMAGE_KEYS, "psnr_db", "chamfer_l1_mean", "chamfer_l2_squared_mean",
               "bidirectional_distance_p95", "bidirectional_distance_max_sampled",
               "normal_consistency_absdot")


def validation_refinement(pair, fit_root, quality_root, file_id):
    with np.load(fit_root / "refine" / "model.npz", allow_pickle=False) as archive:
        model = Model(archive["weights"], float(archive["max_offset"]))
    sidecar = quality_root / f"validation-{file_id}" / f"{file_id}-refine.sidecar"
    with np.load(sidecar, allow_pickle=False) as archive:
        refinement_count = len(archive["refine_faces"])
    mesh = Mesh(pair["positions"], pair["triangles"], pair["face_clusters"])
    candidate, _ = decode(mesh, model, sidecar, len(mesh.triangles) + 2 * refinement_count)
    return candidate.positions, candidate.triangles


def measure(reference, geometry, metric, views, size, samples, surface_samples, seed):
    per_view = []
    for view in range(views):
        basis = view_basis(view, views)
        ref_image, ref_coverage = render(*reference, basis, size, samples)
        image, coverage = render(*geometry, basis, size, samples)
        union = (ref_coverage > 0) | (coverage > 0)
        values = metric(ref_image / 255., image / 255., union)
        values.update({
            "view": view,
            "silhouette_xor_fraction": float(np.mean((ref_coverage > 0) != (coverage > 0))),
            "coverage_mae": float(np.mean(np.abs(ref_coverage - coverage))),
        })
        per_view.append(values)
    mean = {key: float(np.mean([row[key] for row in per_view])) for key in IMAGE_KEYS}
    mean["psnr_db"] = None if mean["mse"] == 0 else float(-10 * np.log10(mean["mse"]))
    mean.update(surface_metrics(reference, geometry, surface_samples, seed))
    return mean, per_view


def paired_summary(records, bootstrap_count=2000, seed=20261122):
    summary = {}
    for split in ("train", "validation"):
        paired = [r for r in records if r["split"] == split and
                  r.get("methods", {}).get("decoder_refine") is not None and
                  r.get("methods", {}).get("meshoptimizer_budget") is not None]
        deltas = {}
        for key_index, key in enumerate(METRIC_KEYS):
            values = np.asarray([
                r["methods"]["decoder_refine"][key] - r["methods"]["meshoptimizer_budget"][key]
                for r in paired if r["methods"]["decoder_refine"][key] is not None and
                r["methods"]["meshoptimizer_budget"][key] is not None
            ], dtype=np.float64)
            if not len(values):
                deltas[key] = None
                continue
            rng = np.random.default_rng(seed + key_index + (100 if split == "validation" else 0))
            boot = np.empty(bootstrap_count)
            for index in range(bootstrap_count):
                boot[index] = rng.choice(values, len(values), replace=True).mean()
            deltas[key] = {
                "decoder_refine_minus_meshoptimizer": float(values.mean()),
                "bootstrap_95_percentile_ci": [float(x) for x in np.quantile(boot, (.025, .975))],
                "assets_positive": int(np.count_nonzero(values > 0)),
                "positive_delta_is_better": key in ("psnr_db", "ssim", "normal_consistency_absdot"),
            }
        summary[split] = {"paired_assets": len(paired), "deltas": deltas}
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, action="append", required=True)
    parser.add_argument("--budget-meshopt", type=Path, required=True,
                        help="meshoptimizer baseline folder at decoder-refinement face budgets")
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--quality", type=Path, required=True,
                        help="quality folder containing validation refinement sidecars")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--views", type=int, default=12)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--surface-samples", type=int, default=20000)
    args = parser.parse_args()
    if args.views < 2 or not 32 <= args.size <= 1024 or args.samples not in (1, 2, 4):
        parser.error("Invalid image evaluation budget")
    args.out.mkdir(parents=True, exist_ok=True)
    budget_manifest_path = args.budget_meshopt / "manifest.json"
    budget_manifest = json.loads(budget_manifest_path.read_text(encoding="utf-8"))
    budget_rows = {(r["split"], r["file_id"]): r for r in budget_manifest["records"]}
    quality_report_path = args.quality / "report.json"
    quality_report = json.loads(quality_report_path.read_text(encoding="utf-8"))
    quality_rows = {(r["split"], r["file_id"]): r for r in quality_report["records"]}
    fit_report_path = args.fit / "report.json"
    fit_report = json.loads(fit_report_path.read_text(encoding="utf-8"))
    fit_rows = {r["file_id"]: r for r in fit_report["modes"]["refine"]["records"]}
    metric = ImageMetrics()
    report = {
        "scope": "Frozen development comparison: source-aware decoder refinement vs meshoptimizer at equal face count",
        "image_protocol": {"views": args.views, "size": args.size,
                           "box_samples_per_pixel": args.samples ** 2,
                           "metrics": metric.settings},
        "surface_protocol": {"samples_per_direction": args.surface_samples,
                             "method": "Area-uniform samples; nearest sampled-point-cloud distances"},
        "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                    "scipy": scipy.__version__, "torch": torch.__version__},
        "inputs": {
            "budget_meshopt_manifest_sha256": hashlib.sha256(budget_manifest_path.read_bytes()).hexdigest(),
            "fit_report_sha256": hashlib.sha256(fit_report_path.read_bytes()).hexdigest(),
            "quality_report_sha256": hashlib.sha256(quality_report_path.read_bytes()).hexdigest(),
        },
        "records": [],
    }
    panels = []
    for manifest_path in args.pairs:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if any(r["source"]["split"] not in ("train", "validation") for r in manifest["records"]):
            raise ValueError("Final test geometry is refused by this comparison")
        report["inputs"].setdefault("pair_manifest_sha256", {})[str(manifest_path)] = hashlib.sha256(
            manifest_path.read_bytes()).hexdigest()
        for row in manifest["records"]:
            source = row["source"]
            key = (source["split"], source["file_id"])
            result = {"split": key[0], "file_id": key[1], "source_sha256": source["sha256"],
                      "preparation_status": row["status"], "decoder_refine_status": None,
                      "meshoptimizer_budget_status": None, "triangle_counts": {}, "methods": {}}
            if row["status"] != "prepared":
                result["reason"] = row["reason"]
                report["records"].append(result)
                continue
            pair = load_pair(manifest_path.parent, row)
            quality_row = quality_rows.get(key, {})
            result["decoder_refine_status"] = quality_row.get("decode_status", {}).get("refine", "missing")
            fit_row = fit_rows.get(key[1], {}) if key[0] == "train" else None
            if key[0] == "train":
                result["decoder_refine_status"] = fit_row.get("status", "missing")
            base_geometry = (pair["positions"], pair["triangles"])
            variants = {"meshoptimizer_base": base_geometry}
            if result["decoder_refine_status"] == "decoded":
                if key[0] == "train":
                    path = args.fit / "refine" / f"{key[1]}-decoded.npz"
                    with np.load(path, allow_pickle=False) as archive:
                        variants["decoder_refine"] = (archive["positions"], archive["triangles"])
                else:
                    variants["decoder_refine"] = validation_refinement(pair, args.fit, args.quality, key[1])
            budget_row = budget_rows.get(key, {})
            result["meshoptimizer_budget_status"] = budget_row.get("status", "missing")
            if budget_row.get("status") == "usable":
                path = args.budget_meshopt / f"{key[0]}-{key[1]}.npz"
                if hashlib.sha256(path.read_bytes()).hexdigest() != budget_row["output_sha256"]:
                    raise ValueError(f"Meshoptimizer budget hash mismatch for {key}")
                with np.load(path, allow_pickle=False) as archive:
                    variants["meshoptimizer_budget"] = (archive["positions"], archive["triangles"])
            if "decoder_refine" in variants and "meshoptimizer_budget" in variants:
                decoder_count = len(variants["decoder_refine"][1])
                meshopt_count = len(variants["meshoptimizer_budget"][1])
                if decoder_count != meshopt_count or decoder_count != budget_row["target_triangles"]:
                    raise ValueError(f"Equal-face invariant failed for {key}")
            for name, geometry in variants.items():
                result["triangle_counts"][name] = len(geometry[1])
            reference = (pair["source_positions"], pair["source_triangles"])
            for name, geometry in variants.items():
                image, per_view = measure(reference, geometry, metric, args.views, args.size,
                                          args.samples, args.surface_samples, key[1])
                result["methods"][name] = image
                result.setdefault("per_view", {})[name] = per_view
            report["records"].append(result)
            if key[0] == "validation":
                order = ("reference", "meshoptimizer_base", "decoder_refine", "meshoptimizer_budget")
                visuals = [render(*reference, view_basis(0, args.views), args.size, args.samples)[0]]
                visuals.extend(render(*variants[name], view_basis(0, args.views), args.size, args.samples)[0]
                               for name in order[1:] if name in variants)
                panel = Image.new("RGB", (args.size * len(visuals), args.size + 32), "#20252b")
                draw = ImageDraw.Draw(panel)
                for col, (name, img) in enumerate(zip(order, visuals)):
                    draw.text((col * args.size + 4, 5), f"{key[1]} | {name}", fill="white")
                    panel.paste(Image.fromarray(img), (col * args.size, 32))
                panels.append(panel)
            (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(f"{key[0]} {key[1]}: {list(variants)}", flush=True)
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
