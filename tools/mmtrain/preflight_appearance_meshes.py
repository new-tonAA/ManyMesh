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


def export_appearance_objs(directory, geometries):
    """Write neutral-material OBJ inputs in the shared source frame."""
    directory.mkdir(parents=True, exist_ok=True)
    material = directory / "neutral.mtl"
    material.write_text("newmtl neutral\nKd 0.5 0.5 0.5\nKs 0 0.5 0\n",
                        encoding="ascii", newline="\n")
    receipts = {material.name: digest(material)}
    for name, (positions, triangles) in geometries.items():
        path = directory / f"{name}.obj"
        a, b, c = positions[triangles].astype(np.float64).transpose(1, 0, 2)
        normals = np.cross(b - a, c - a)
        normals /= np.linalg.norm(normals, axis=1, keepdims=True)
        with path.open("w", encoding="ascii", newline="\n") as obj:
            obj.write("mtllib neutral.mtl\nvt 0 0\nvt 1 0\nvt 0 1\n")
            np.savetxt(obj, positions, fmt="v %.17g %.17g %.17g")
            np.savetxt(obj, normals, fmt="vn %.9g %.9g %.9g")
            obj.write("usemtl neutral\n")
            for index, (a, b, c) in enumerate(triangles + 1, 1):
                obj.write(f"f {a}/1/{index} {b}/2/{index} {c}/3/{index}\n")
        receipts[path.name] = digest(path)
    return receipts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--candidate", type=Path, required=True,
                        help="PLY prepared by adapt_position_ply.py")
    parser.add_argument("--mmgeo", type=Path, required=True)
    parser.add_argument("--target-ratio", type=float, default=TARGET,
                        help="Center of the one-percentage-point retention band")
    parser.add_argument("--weld-controls", action="store_true",
                        help="Give both controls exact-position welded source indices")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--export-obj-dir", type=Path,
                        help="Export all four audited meshes when the exact-face gate passes")
    args = parser.parse_args()
    if not RATIO_TOLERANCE < args.target_ratio <= 1:
        parser.error("Target ratio must be greater than the band tolerance and at most 1")
    if digest(args.source) != args.source_sha256:
        parser.error("Source OBJ does not match the expected SHA-256")

    positions, faces = load_obj(args.source)
    center, radius = source_frame(positions)
    points = normalize(positions, center, radius)
    source = compact(points, faces)
    reference_edges = boundary(*source)
    candidate_points, candidate_faces = load_binary_ply(args.candidate)
    manymesh = (normalize(candidate_points, center, radius), candidate_faces)
    candidate = audit(reference_edges, *manymesh)
    actual_ratio = len(candidate_faces) / len(faces)
    in_band = (args.target_ratio - RATIO_TOLERANCE <= actual_ratio
               <= args.target_ratio + RATIO_TOLERANCE)
    target_faces = len(candidate_faces) if in_band else round(args.target_ratio * len(faces))

    control_points, control_faces = points, faces
    if args.weld_controls:
        control_points, indices = np.unique(points, axis=0, return_inverse=True)
        control_faces = indices[faces]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    controls = {}
    geometries = {"reference": source, "manymesh": manymesh}
    for name in ("qem_preserve_border", "meshoptimizer_lock_border"):
        try:
            if name == "qem_preserve_border":
                mesh = qem_simplify(control_points, control_faces, target_faces)
                geometry = mesh.positions, mesh.triangles
            else:
                vertices, triangles, _ = meshopt_simplify_raw(
                    control_points, control_faces, target_faces, args.output.parent)
                geometry = vertices, triangles
            control = audit(reference_edges, *geometry)
            geometries[name] = geometry
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
        "target_ratio": args.target_ratio, "ratio_tolerance": RATIO_TOLERANCE,
        "normalized_boundary_tolerance": BOUNDARY_TOLERANCE,
        "candidate_ratio": actual_ratio, "candidate_in_band": in_band,
        "manymesh": candidate, "control_target_faces": target_faces,
        "control_indexing": "welded" if args.weld_controls else "original",
        "control_input_vertices": len(control_points),
        "controls": controls,
        "matched_inputs_ready": in_band and candidate["boundary_preserved"]
        and all(row["eligible"] for row in controls.values()),
    }
    if args.export_obj_dir is not None and report["matched_inputs_ready"]:
        report["source_frame"] = {"center": center.tolist(), "radius": float(radius)}
        report["obj_exports_sha256"] = export_appearance_objs(args.export_obj_dir, geometries)
    args.output.write_text(json.dumps(report, indent=2) + "\n",
                           encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
