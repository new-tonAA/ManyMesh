"""Compare QEM and meshoptimizer on a frozen asset split at a 70% face target."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

import fast_simplification
import flip_evaluator
import numpy as np
import scipy
from PIL import Image, ImageDraw
from skimage.metrics import structural_similarity

from cluster_decoder import Mesh, topology
from cluster_decoder_meshopt_baseline import HELPER
from cluster_decoder_pilot import read_stl
from cluster_decoder_quality import render
from cluster_decoder_surface_quality import surface_metrics
from make_refinement_pairs import view_basis


IMAGE_KEYS = ("mse", "psnr_db", "ssim", "flip", "silhouette_xor_fraction", "coverage_mae")
SURFACE_KEYS = ("chamfer_l1_mean", "chamfer_l2_squared_mean",
                "bidirectional_distance_p95", "bidirectional_distance_max_sampled",
                "normal_consistency_absdot")
PREFER_HIGHER = {"psnr_db", "ssim", "normal_consistency_absdot"}


def image_metrics(reference, candidate, ref_coverage, candidate_coverage, ppd):
    ref = reference.astype(np.float64) / 255.
    image = candidate.astype(np.float64) / 255.
    difference = ref - image
    mse = float(np.mean(difference ** 2))
    xor = (ref_coverage > 0) != (candidate_coverage > 0)
    per_pixel_squared_error = np.mean(difference ** 2, axis=2)
    total_squared_error = float(np.sum(per_pixel_squared_error))
    _, flip_mean, _ = flip_evaluator.evaluate(
        ref.astype(np.float32), image.astype(np.float32), "LDR", inputsRGB=True,
        applyMagma=False, parameters={"ppd": ppd})
    return {
        "mse": mse,
        "psnr_db": None if mse == 0 else float(-10 * np.log10(mse)),
        "ssim": float(structural_similarity(
            ref, image, data_range=1., channel_axis=2, gaussian_weights=True,
            sigma=1.5, use_sample_covariance=False)),
        "flip": float(flip_mean),
        "silhouette_xor_fraction": float(np.mean((ref_coverage > 0) != (candidate_coverage > 0))),
        "silhouette_xor_mse_share": (None if total_squared_error == 0 else
                                      float(np.sum(per_pixel_squared_error[xor]) /
                                            total_squared_error)),
        "coverage_mae": float(np.mean(np.abs(ref_coverage - candidate_coverage))),
    }


def render_metrics(reference, candidate, views, size, samples, ppd):
    rows = []
    for view in range(views):
        basis = view_basis(view, views)
        ref_image, ref_coverage = render(*reference, basis, size, samples)
        image, coverage = render(*candidate, basis, size, samples)
        rows.append(image_metrics(ref_image, image, ref_coverage, coverage, ppd))
    means = {key: float(np.mean([row[key] for row in rows]))
             for key in IMAGE_KEYS if key != "psnr_db"}
    means["psnr_db"] = (None if means["mse"] == 0
                        else float(-10 * np.log10(means["mse"])))
    finite_shares = [row["silhouette_xor_mse_share"] for row in rows
                     if row["silhouette_xor_mse_share"] is not None]
    means["silhouette_xor_mse_share"] = (
        float(np.mean(finite_shares)) if finite_shares else None)
    return means, rows


def qem_simplify(positions, triangles, target_triangles):
    vertices, faces = fast_simplification.simplify(
        positions, triangles.astype(np.int32), target_count=target_triangles,
        preserve_border=True)
    used, inverse = np.unique(faces, return_inverse=True)
    vertices = vertices[used]
    faces = inverse.reshape(-1, 3)
    mesh = Mesh(vertices, faces, np.zeros(len(faces), dtype=np.int64)).checked()
    return mesh


def meshopt_simplify_raw(positions, triangles, target_triangles, temporary_root):
    input_positions = np.asarray(positions, dtype=np.float32)
    with tempfile.TemporaryDirectory(prefix="qem-meshopt-", dir=temporary_root) as folder:
        source = Path(folder) / "input.json"
        destination = Path(folder) / "output.json"
        source.write_text(json.dumps({
            "positions": input_positions.tolist(),
            "triangles": np.asarray(triangles, dtype=np.int64).tolist(),
            "targetTriangles": int(target_triangles),
            "targetError": 1e6,
        }), encoding="utf-8")
        completed = subprocess.run(
            ["node", str(HELPER), str(source), str(destination)],
            check=False, capture_output=True, text=True, timeout=180)
        if completed.returncode != 0:
            raise ValueError("meshoptimizer failed: " + completed.stderr.strip()[-1200:])
        output = json.loads(destination.read_text(encoding="utf-8"))
    indices = np.asarray(output["indices"], dtype=np.int64)
    if (indices.ndim != 1 or not len(indices) or len(indices) % 3
            or indices.min() < 0 or indices.max() >= len(input_positions)):
        raise ValueError("meshoptimizer returned invalid indices")
    used, inverse = np.unique(indices, return_inverse=True)
    return input_positions[used].astype(np.float64), inverse.reshape(-1, 3), output


def surface_geometry_for_sampling(positions, triangles):
    points = positions[triangles]
    areas = np.linalg.norm(np.cross(points[:, 1] - points[:, 0],
                                    points[:, 2] - points[:, 0]), axis=1)
    nondegenerate = areas > 1e-18
    faces = triangles[nondegenerate]
    keys = np.sort(faces, axis=1)
    _, first = np.unique(keys, axis=0, return_index=True)
    unique = np.zeros(len(faces), dtype=bool)
    unique[first] = True
    cleaned = faces[unique]
    used, inverse = np.unique(cleaned, return_inverse=True)
    cleaned_positions = positions[used]
    cleaned = inverse.reshape(-1, 3)
    try:
        Mesh(cleaned_positions, cleaned, np.zeros(len(cleaned), dtype=np.int64)).checked()
        cleanup_topology = "valid"
    except ValueError as error:
        cleanup_topology = f"still_invalid: {error}"
    return (cleaned_positions, cleaned), {
        "degenerate_faces_omitted_for_sampling": int(np.count_nonzero(~nondegenerate)),
        "duplicate_faces_omitted_for_sampling": int(len(faces) - len(cleaned)),
        "topology_after_surface_sampling_cleanup": cleanup_topology,
    }


def bootstrap_deltas(records, count=10000, seed=20261122):
    result = {}
    metrics = (*IMAGE_KEYS, *SURFACE_KEYS)
    for index, key in enumerate(metrics):
        pairs = [
            (row["file_id"], row["methods"]["meshoptimizer"][key],
             row["methods"]["qem"][key])
            for row in records
        ]
        finite_pairs = [(asset, new - old) for asset, new, old in pairs
                        if new is not None and old is not None
                        and np.isfinite(new) and np.isfinite(old)]
        deltas = np.asarray([delta for _, delta in finite_pairs], dtype=np.float64)
        if len(deltas):
            rng = np.random.default_rng(seed + index)
            samples = rng.choice(deltas, size=(count, len(deltas)), replace=True).mean(axis=1)
            mean = float(deltas.mean())
            interval = [float(value) for value in np.quantile(samples, (.025, .975))]
            better = int(np.count_nonzero(
                deltas > 0 if key in PREFER_HIGHER else deltas < 0))
        else:
            mean, interval, better = None, None, None
        result[key] = {
            "meshoptimizer_minus_qem_mean": mean,
            "asset_bootstrap_95_percentile_ci": interval,
            "assets_better_for_meshoptimizer": better,
            "assets_included": len(deltas),
            "assets_omitted_nonfinite": [asset for asset, _, _ in pairs
                                         if asset not in {item[0] for item in finite_pairs}],
            "preferred_direction": "higher" if key in PREFER_HIGHER else "lower",
        }
    return result


def bootstrap_method_metric(records, method, key, count=10000, seed=20261122):
    values = np.asarray([
        row["methods"][method][key] for row in records
        if row["methods"][method][key] is not None
        and np.isfinite(row["methods"][method][key])
    ], dtype=np.float64)
    if not len(values):
        return {"mean": None, "asset_bootstrap_95_percentile_ci": None, "assets": 0}
    rng = np.random.default_rng(seed)
    samples = rng.choice(values, size=(count, len(values)), replace=True).mean(axis=1)
    return {
        "mean": float(values.mean()),
        "asset_bootstrap_95_percentile_ci": [
            float(value) for value in np.quantile(samples, (.025, .975))],
        "assets": int(len(values)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Hash-pinned Thingi10K mesh manifest")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "validation"), default="validation")
    parser.add_argument("--retention", type=float, default=.70)
    parser.add_argument("--views", type=int, default=12)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--samples", type=int, default=2,
                        help="Box samples per axis; two means 4x pixel sampling")
    parser.add_argument("--surface-samples", type=int, default=20000)
    parser.add_argument("--flip-ppd", type=float, default=67.)
    args = parser.parse_args()
    if (not 0 < args.retention < 1 or args.views < 2 or not 32 <= args.size <= 1024
            or args.samples not in (1, 2, 4) or args.surface_samples < 100
            or not np.isfinite(args.flip_ppd) or args.flip_ppd <= 0):
        parser.error("Invalid experiment settings")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assets = [row for row in manifest["files"] if row["split"] == args.split]
    if not assets:
        raise ValueError(f"No {args.split} assets in the supplied manifest")
    args.out.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).resolve().parents[2]
    meshopt_package = json.loads((repo_root / "third_party/meshoptimizer/js/package.json")
                                 .read_text(encoding="utf-8"))
    report = {
        "schema": "manymesh-qem-meshopt-screen-v1",
        "scope": f"{args.split}-only baseline comparison; no decoder result or final-test geometry",
        "split": args.split,
        "target_retention": args.retention,
        "comparison": "QEM and meshoptimizer are matched to the QEM output's actual face count per asset",
        "meshoptimizer": {"version": meshopt_package["version"],
                          "flags": ["LockBorder"], "target_error": 1e6},
        "image_protocol": {"views": args.views, "resolution": [args.size, args.size],
                           "box_samples_per_pixel": args.samples ** 2,
                           "flat_shading": True, "input_color": "8-bit sRGB",
                           "ssim": "Gaussian sigma=1.5, population covariance",
                           "flip": "NVIDIA LDR-FLIP", "flip_ppd": args.flip_ppd},
        "surface_protocol": {"samples_per_direction": args.surface_samples,
                             "method": "Area-uniform samples; nearest sampled-point-cloud distances; estimates, not Hausdorff bounds",
                             "meshoptimizer_sampling_cleanup": "Only zero-area/sub-threshold and duplicate faces omitted for surface sampling; rendered image metrics use the raw simplifier output and topology is reported separately"},
        "lpips": "Not measured in this supplemental screen",
        "uncertainty": "10,000 paired bootstrap resamples over assets; camera views are averaged within each asset and are not independent samples",
        "runtime": {"python": platform.python_version(), "numpy": np.__version__,
                    "scipy": scipy.__version__,
                    "node": subprocess.run(["node", "--version"], check=True,
                                            capture_output=True, text=True).stdout.strip(),
                    "fast_simplification": importlib.metadata.version("fast-simplification"),
                    "flip_evaluator": importlib.metadata.version("flip-evaluator"),
                    "scikit_image": importlib.metadata.version("scikit-image")},
        "inputs": {"download_manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest()},
        "code_sha256": {
            path.resolve().relative_to(repo_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), HELPER,
                         Path(__file__).with_name("cluster_decoder_meshopt_baseline.py"),
                         Path(__file__).with_name("cluster_decoder_quality.py"),
                         Path(__file__).with_name("cluster_decoder_surface_quality.py"),
                         Path(__file__).with_name("cluster_decoder.py"),
                         Path(__file__).with_name("cluster_decoder_pilot.py"),
                         Path(__file__).with_name("make_refinement_pairs.py"))
        },
        "assets_expected": len(assets), "records": [], "simplifier_failures": [],
    }
    gallery = []
    for row in assets:
        path = args.manifest.parent / row["path"]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError(f"Input hash mismatch for asset {row['file_id']}")
        positions, triangles = read_stl(path)
        if len(triangles) != row["faces"]:
            raise ValueError(f"Face-count mismatch for asset {row['file_id']}")
        origin = (positions.min(axis=0) + positions.max(axis=0)) * .5
        scale = np.linalg.norm(positions - origin, axis=1).max()
        if not np.isfinite(scale) or scale <= 0:
            raise ValueError(f"Invalid scale for asset {row['file_id']}")
        positions = (positions - origin) / scale
        source = Mesh(positions, triangles,
                      np.zeros(len(triangles), dtype=np.int64)).checked()
        target = int(len(triangles) * args.retention)
        try:
            qem = qem_simplify(positions, triangles, target)
        except ValueError as error:
            report["simplifier_failures"].append({
                "split": row["split"], "file_id": row["file_id"],
                "thing_id": row.get("thing_id"), "source_sha256": row["sha256"],
                "source_faces": len(triangles), "requested_target_faces": target,
                "method": "qem", "error": str(error),
            })
            print(f"{args.split} {row['file_id']}: QEM rejected ({error})", flush=True)
            continue
        if topology(qem)[1] != topology(source)[1]:
            raise ValueError(f"QEM changed the directed boundary for asset {row['file_id']}")
        pair = {"source_positions": positions, "source_triangles": triangles}
        meshopt_positions, meshopt_triangles, meshopt_info = meshopt_simplify_raw(
            positions, triangles, len(qem.triangles), args.out)
        reference = (positions, triangles)
        qem_geometry = (qem.positions, qem.triangles)
        meshopt_geometry = (meshopt_positions, meshopt_triangles)
        try:
            meshopt_mesh = Mesh(meshopt_positions, meshopt_triangles,
                                np.zeros(len(meshopt_triangles), dtype=np.int64)).checked()
            meshopt_topology_status = "valid"
            meshopt_boundary_preserved = topology(meshopt_mesh)[1] == topology(source)[1]
            if not meshopt_boundary_preserved:
                meshopt_topology_status = "boundary_mismatch"
        except ValueError as error:
            meshopt_topology_status = f"rejected: {error}"
            meshopt_boundary_preserved = False
        qem_image, qem_views = render_metrics(reference, qem_geometry, args.views,
                                              args.size, args.samples, args.flip_ppd)
        meshopt_image, meshopt_views = render_metrics(reference, meshopt_geometry, args.views,
                                                     args.size, args.samples, args.flip_ppd)
        qem_surface = surface_metrics(reference, qem_geometry, args.surface_samples, row["file_id"])
        meshopt_sampling_geometry, meshopt_surface_cleanup = surface_geometry_for_sampling(
            meshopt_positions, meshopt_triangles)
        meshopt_surface = surface_metrics(reference, meshopt_sampling_geometry,
                                          args.surface_samples, row["file_id"])
        meshopt_surface.update(meshopt_surface_cleanup)
        record = {
            "split": row["split"], "file_id": row["file_id"], "thing_id": row.get("thing_id"),
            "source_sha256": row["sha256"], "source_faces": len(triangles),
            "requested_target_faces": target, "actual_qem_faces": len(qem.triangles),
            "actual_meshoptimizer_faces": len(meshopt_triangles),
            "actual_retention": len(qem.triangles) / len(triangles),
            "meshoptimizer_error": meshopt_info.get("error"),
            "meshoptimizer_topology_status": meshopt_topology_status,
            "meshoptimizer_boundary_preserved": meshopt_boundary_preserved,
            "methods": {"qem": qem_image | qem_surface,
                        "meshoptimizer": meshopt_image | meshopt_surface},
            "per_view": {"qem": qem_views, "meshoptimizer": meshopt_views},
        }
        if record["actual_qem_faces"] != record["actual_meshoptimizer_faces"]:
            raise ValueError(f"Face-count mismatch for asset {row['file_id']}")
        report["records"].append(record)
        print(f"{args.split} {row['file_id']}: {len(qem.triangles)}/{len(triangles)} faces", flush=True)

        basis = view_basis(0, args.views)
        images = [render(*geometry, basis, args.size, args.samples)[0]
                  for geometry in (reference, qem_geometry, meshopt_geometry)]
        panel = Image.new("RGB", (args.size * 3, args.size + 26), "#20252b")
        draw = ImageDraw.Draw(panel)
        meshopt_label = ("meshopt" if meshopt_topology_status == "valid"
                         and meshopt_boundary_preserved else "meshopt INVALID")
        labels = ("reference", "QEM", meshopt_label)
        for column, (label, image) in enumerate(zip(labels, images)):
            draw.text((column * args.size + 4, 5), f"{row['file_id']} | {label}", fill="white")
            panel.paste(Image.fromarray(image), (column * args.size, 26))
        gallery.append(panel)

    report["assets_evaluated"] = len(report["records"])
    report["meshoptimizer_topology_valid_assets"] = sum(
        row["meshoptimizer_topology_status"] == "valid" and
        row["meshoptimizer_boundary_preserved"] for row in report["records"])
    valid_records = [row for row in report["records"]
                     if row["meshoptimizer_topology_status"] == "valid"
                     and row["meshoptimizer_boundary_preserved"]]
    report["paired_summary"] = {
        "all_raw_outputs": bootstrap_deltas(report["records"]),
        "topology_and_boundary_valid_outputs": bootstrap_deltas(valid_records),
    }
    report["meshoptimizer_topology_failures"] = [
        {"file_id": row["file_id"], "status": row["meshoptimizer_topology_status"],
         "boundary_preserved": row["meshoptimizer_boundary_preserved"]}
        for row in report["records"] if row not in valid_records
    ]
    report["silhouette_error_attribution"] = {
        "definition": (
            "A pixel is a silhouette-XOR pixel when reference and candidate have "
            "different nonzero-coverage status. The share is RGB squared error "
            "inside those pixels divided by total RGB squared error. This is a "
            "raster-space attribution, not a perceptual metric."),
        "all_raw_outputs": {
            method: {
                "xor_pixel_fraction": bootstrap_method_metric(
                    report["records"], method, "silhouette_xor_fraction"),
                "xor_pixel_squared_error_share": bootstrap_method_metric(
                    report["records"], method, "silhouette_xor_mse_share"),
            }
            for method in ("qem", "meshoptimizer")
        },
        "topology_and_boundary_valid_outputs": {
            method: {
                "xor_pixel_fraction": bootstrap_method_metric(
                    valid_records, method, "silhouette_xor_fraction"),
                "xor_pixel_squared_error_share": bootstrap_method_metric(
                    valid_records, method, "silhouette_xor_mse_share"),
            }
            for method in ("qem", "meshoptimizer")
        },
    }
    report_path = args.out / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if gallery:
        sheet = Image.new("RGB", (gallery[0].width, sum(panel.height for panel in gallery)), "black")
        y = 0
        for panel in gallery:
            sheet.paste(panel, (0, y))
            y += panel.height
        sheet.save(args.out / f"{args.split}-gallery.png")
    print(f"Evaluated {len(report['records'])}/{report['assets_expected']} {args.split} assets")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
