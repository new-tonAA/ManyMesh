"""Check that a placement experiment has legal meshes at a common face count."""

import argparse
import importlib.metadata
import json
from pathlib import Path
import subprocess

import numpy as np
from scipy.spatial import cKDTree

from score_mmgeo_obj_diagnostic_controls import (
    MESHOPT_HELPER, ROOT, boundary, compact, digest, load_binary_ply, load_obj,
    meshopt_simplify_raw, normalize, qem_simplify, source_frame,
)


TARGET = 0.30
RATIO_TOLERANCE = 0.01
BOUNDARY_TOLERANCE = float(np.finfo(np.float32).eps)


def same_boundary(reference, candidate):
    """Match oriented edges after a bijection of their endpoint positions."""
    if reference == candidate:
        return True
    if not reference or len(reference) != len(candidate):
        return False
    source_points = sorted({p for _, u, v in reference for p in (u, v)})
    output_points = sorted({p for _, u, v in candidate for p in (u, v)})
    if len(source_points) != len(output_points):
        return False
    distance, indices = cKDTree(output_points).query(source_points)
    if distance.max() > BOUNDARY_TOLERANCE or len(set(indices)) != len(source_points):
        return False
    match = dict(zip(source_points, (output_points[i] for i in indices)))
    return {(group, match[u], match[v]) for group, u, v in reference} == set(candidate)


def audit(reference_edges, positions, triangles):
    result = {"faces": len(triangles)}
    try:
        edges = boundary(positions, triangles)
    except ValueError as error:
        return {**result, "topology_error": str(error), "boundary_preserved": False}
    return {
        **result, "topology_error": None, "boundary_edges": len(edges),
        "boundary_preserved": same_boundary(reference_edges, edges),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--candidate", type=Path, required=True,
                        help="PLY prepared by adapt_position_ply.py")
    parser.add_argument("--mmgeo", type=Path, required=True)
    parser.add_argument("--weld-controls", action="store_true",
                        help="Give both controls exact-position welded source indices")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if digest(args.source) != args.source_sha256:
        parser.error("Source OBJ does not match the expected SHA-256")

    positions, faces = load_obj(args.source)
    center, radius = source_frame(positions)
    points = normalize(positions, center, radius)
    reference_edges = boundary(*compact(points, faces))
    candidate_points, candidate_faces = load_binary_ply(args.candidate)
    candidate = audit(reference_edges, normalize(candidate_points, center, radius),
                      candidate_faces)
    actual_ratio = len(candidate_faces) / len(faces)
    in_band = abs(actual_ratio - TARGET) <= RATIO_TOLERANCE
    target_faces = len(candidate_faces) if in_band else round(TARGET * len(faces))

    control_points, control_faces = points, faces
    if args.weld_controls:
        control_points, indices = np.unique(points, axis=0, return_inverse=True)
        control_faces = indices[faces]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    controls = {}
    for name in ("qem_preserve_border", "meshoptimizer_lock_border"):
        try:
            if name == "qem_preserve_border":
                mesh = qem_simplify(control_points, control_faces, target_faces)
                control = audit(reference_edges, mesh.positions, mesh.triangles)
            else:
                vertices, triangles, _ = meshopt_simplify_raw(
                    control_points, control_faces, target_faces, args.output.parent)
                control = audit(reference_edges, vertices, triangles)
        except (ValueError, subprocess.TimeoutExpired) as error:
            control = {"error": str(error)}
        control["eligible"] = (control.get("faces") == target_faces
                               and control["boundary_preserved"])
        controls[name] = control

    report = {
        "source_sha256": args.source_sha256,
        "source_faces": len(faces),
        "source_boundary_edges": len(reference_edges),
        "candidate_sha256": digest(args.candidate),
        "mmgeo_sha256": digest(args.mmgeo),
        "script_sha256": digest(Path(__file__)),
        "source_revision": subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "meshoptimizer_helper_sha256": digest(MESHOPT_HELPER),
        "meshoptimizer_module_sha256": digest(
            ROOT / "third_party/meshoptimizer/js/meshopt_simplifier.js"),
        "numpy_version": np.__version__,
        "scipy_version": importlib.metadata.version("scipy"),
        "fast_simplification_version": importlib.metadata.version("fast-simplification"),
        "target_ratio": TARGET, "ratio_tolerance": RATIO_TOLERANCE,
        "normalized_boundary_tolerance": BOUNDARY_TOLERANCE,
        "candidate_ratio": actual_ratio, "candidate_in_band": in_band,
        "manymesh": candidate, "control_target_faces": target_faces,
        "control_indexing": "welded" if args.weld_controls else "original",
        "control_input_vertices": len(control_points),
        "controls": controls,
        "matched_inputs_ready": in_band and candidate["boundary_preserved"]
        and all(row["eligible"] for row in controls.values()),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n",
                           encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
