"""Diagnose existing cuts against exact-face QEM and meshoptimizer controls."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/mmgeo"))
sys.path.insert(0, str(ROOT / "tools/mmtrain"))

from audit_target_budget_visibility import load_binary_ply, load_obj
from bench_upstream_clusterlod import assess, boundary, compact
from compare_qem_meshopt_validation_70pct import meshopt_simplify_raw, qem_simplify
from cluster_decoder_meshopt_baseline import HELPER as MESHOPT_HELPER
from audit_cut_boundary_geometry import measure as measure_boundary_curve


RATIOS = (0.3, 0.5, 0.7)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_safe(value):
    """Convert NumPy values in diagnostic records to JSON-native values."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def source_frame(positions):
    center = (positions.min(axis=0) + positions.max(axis=0)) * 0.5
    radius = np.linalg.norm(positions - center, axis=1).max()
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError("Source mesh has invalid scale")
    return center, radius


def normalize(positions, center, radius):
    return ((positions - center) / radius).astype(np.float32).astype(np.float64)


def score_control(reference, reference_boundary, geometry, views, size, seed):
    return assess(reference, geometry, reference_boundary, views, size, seed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-obj", type=Path, required=True)
    parser.add_argument("--cut-dir", type=Path, required=True)
    parser.add_argument("--mmgeo", type=Path,
                        help="Optional generator binary hash; the scorer reads frozen PLY cuts and does not invoke it")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--views", type=int, default=8)
    parser.add_argument("--size", type=int, default=192)
    parser.add_argument("--seed", type=int, default=20261123)
    parser.add_argument("--score-ineligible-controls", action="store_true",
                        help="Score image metrics even when the ManyMesh cut fails boundary checks")
    parser.add_argument("--geometric-boundary-tolerance-ulp", type=float, default=None,
                        help="Accept a one-to-one oriented boundary-vertex match within this many float32 epsilons")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    original_positions, faces = load_obj(args.source_obj)
    center, radius = source_frame(original_positions)
    reference = (normalize(original_positions, center, radius), faces)
    reference_boundary = boundary(*reference)
    boundary_step = (np.linalg.norm(original_positions.max(axis=0)
                                    - original_positions.min(axis=0))
                     / radius * 1e-4)
    boundary_tolerance = (None if args.geometric_boundary_tolerance_ulp is None else
                          args.geometric_boundary_tolerance_ulp
                          * np.finfo(np.float32).eps)

    def curve_equivalent(geometry):
        try:
            audit = measure_boundary_curve(
                reference_boundary, boundary(*geometry), boundary_step)
        except ValueError as error:
            return False, {"error": str(error)}
        equivalent = (
            audit["nearest_vertex_map_is_one_to_one"]
            and audit["approximate_directed_edge_matches"] == len(reference_boundary)
            and audit["approximate_reversed_edge_matches"] == 0
            and audit["max_nearest_boundary_vertex_distance"] <= boundary_tolerance)
        return equivalent, audit
    report = {
        "source_path": str(args.source_obj),
        "source_sha256": digest(args.source_obj),
        "scoring_repository_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip(),
        "candidate_generation_provenance": {
            "generator_binary_sha256": digest(args.mmgeo) if args.mmgeo else None,
            "generator_source_sha256": digest(ROOT / "tools/mmgeo/src/main.cpp"),
            "note": ("The scorer reads the supplied PLY cuts and does not invoke mmgeo; "
                     "without --mmgeo, their generator binary is not pinned."),
        },
        "script_sha256": digest(__file__),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "fast_simplification_version": importlib.metadata.version("fast-simplification"),
        "scikit_image_version": importlib.metadata.version("scikit-image"),
        "node_version": subprocess.check_output(["node", "--version"], text=True).strip(),
        "meshoptimizer_helper_sha256": digest(MESHOPT_HELPER),
        "meshoptimizer_module_sha256": digest(
            ROOT / "third_party/meshoptimizer/js/meshopt_simplifier.js"),
        "protocol": {
            "reference": "original full-resolution OBJ geometry",
            "views": args.views,
            "resolution": args.size,
            "samples_per_pixel": 4,
            "flip_ppd": 67,
            "surface_samples_per_direction": 10000,
            "candidate_face_ratios_requested": list(RATIOS),
            "controls": ["fast-simplification QEM", "meshoptimizer whole-mesh LockBorder"],
            "metrics": ["LDR-FLIP", "PSNR", "SSIM", "silhouette XOR", "coverage MAE",
                        "sampled Chamfer", "sampled 95th-percentile distance",
                        "sampled normal consistency"],
            "boundary_rule": ("exact directed edge set" if boundary_tolerance is None else {
                "type": "one-to-one oriented boundary-vertex mapping",
                "tolerance_float32_ulp": args.geometric_boundary_tolerance_ulp,
                "normalized_tolerance": boundary_tolerance,
                "curve_sample_spacing": boundary_step,
            }),
        },
        "source_vertices": len(reference[0]),
        "source_faces": len(faces),
        "source_boundary_edges": len(reference_boundary),
        "cuts": [],
    }

    for ratio in RATIOS:
        ply = args.cut_dir / f"selected_ratio_{ratio:g}.ply"
        entry = {"requested_ratio": ratio, "candidate_ply": str(ply),
                 "candidate_ply_sha256": digest(ply)}
        positions, triangles = load_binary_ply(ply)
        candidate = compact(normalize(positions, center, radius), triangles)
        entry["actual_faces"] = len(candidate[1])
        entry["actual_ratio"] = len(candidate[1]) / len(faces)
        candidate_metrics = score_control(reference, reference_boundary, candidate,
                                           args.views, args.size, args.seed)
        entry["candidate"] = candidate_metrics
        exact_boundary = candidate_metrics["source_directed_boundary_preserved"]
        entry["candidate_exact_directed_boundary_set"] = exact_boundary
        if boundary_tolerance is None:
            curve_match = False
        else:
            curve_match, curve_audit = curve_equivalent(candidate)
            entry["candidate_boundary_curve_audit"] = curve_audit
        candidate_metrics["source_boundary_geometrically_equivalent"] = (
            exact_boundary or curve_match)
        eligible = (candidate_metrics["topology_error"] is None
                    and (exact_boundary or curve_match))
        entry["candidate_eligible"] = eligible
        entry["controls"] = {}

        if eligible or args.score_ineligible_controls:
            entry["control_scope"] = (
                "eligible matched-face comparison under the recorded boundary rule" if eligible else
                "diagnostic only: ManyMesh cut failed a topology or directed-boundary gate")
            controls = {}
            for name, simplify in (
                    ("qem", lambda: qem_simplify(*reference, len(candidate[1]))),
                    ("meshoptimizer", lambda: meshopt_simplify_raw(
                        *reference, len(candidate[1]), args.out))):
                started = time.perf_counter()
                try:
                    result = simplify()
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    if name == "qem":
                        geometry = (result.positions, result.triangles)
                        metadata = {}
                    else:
                        control_positions, control_triangles, metadata = result
                        geometry = (control_positions, control_triangles)
                    metrics = score_control(reference, reference_boundary, geometry,
                                            args.views, args.size, args.seed)
                    exact = len(geometry[1]) == len(candidate[1])
                    exact_control_boundary = metrics["source_directed_boundary_preserved"]
                    if boundary_tolerance is None:
                        control_curve_match = False
                    else:
                        control_curve_match, control_curve_audit = curve_equivalent(geometry)
                        metrics["boundary_curve_audit"] = control_curve_audit
                    metrics["source_boundary_geometrically_equivalent"] = (
                        exact_control_boundary or control_curve_match)
                    legal = (metrics["topology_error"] is None
                             and (exact_control_boundary or control_curve_match))
                    controls[name] = {
                        "elapsed_ms": elapsed_ms,
                        "faces": len(geometry[1]),
                        "exact_face_count": exact,
                        "eligible": exact and legal,
                        "metrics": metrics,
                        "metadata": metadata,
                    }
                    if exact and legal:
                        controls[name]["candidate_minus_control"] = {
                            "flip": candidate_metrics["image"]["flip"] - metrics["image"]["flip"],
                            "psnr_db": candidate_metrics["image"]["psnr_db"] - metrics["image"]["psnr_db"],
                            "ssim": candidate_metrics["image"]["ssim"] - metrics["image"]["ssim"],
                            "silhouette_xor_fraction": (
                                candidate_metrics["image"]["silhouette_xor_fraction"]
                                - metrics["image"]["silhouette_xor_fraction"]),
                            "coverage_mae": candidate_metrics["image"]["coverage_mae"]
                            - metrics["image"]["coverage_mae"],
                        }
                except (ValueError, subprocess.CalledProcessError) as error:
                    controls[name] = {"eligible": False, "error": str(error)}
            entry["controls"] = controls
        report["cuts"].append(entry)
        print(ratio, entry["actual_faces"], entry["candidate_eligible"],
              {name: control.get("candidate_minus_control")
               for name, control in entry["controls"].items()}, flush=True)

    out_path = args.out / "receipt.json"
    out_path.write_text(json.dumps(json_safe(report), indent=2, allow_nan=False) + "\n",
                        encoding="utf-8")
    print(f"receipt: {out_path}", flush=True)


if __name__ == "__main__":
    main()
