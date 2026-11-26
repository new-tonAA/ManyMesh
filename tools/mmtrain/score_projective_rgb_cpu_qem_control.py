#!/usr/bin/env python3
"""Score an exact-face QEM control against a saved CPU RGB fit."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/mmgeo"))
sys.path.insert(0, str(ROOT / "tools/mmtrain"))


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True,
                        help="Result JSON from fit_projective_rgb_cpu.py")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    from fit_projective_rgb_cpu import camera_sets, score
    from compare_qem_meshopt_validation_70pct import qem_simplify
    from cluster_decoder_surface_quality import surface_metrics
    from preflight_appearance_meshes import audit, boundary, digest

    result = json.loads(args.result.read_text(encoding="utf-8"))
    if digest(args.source) != result["source_sha256"]:
        raise ValueError("The source OBJ hash differs from the fit receipt")
    geometry_path = args.result.with_suffix(".geometry.npz")
    geometry_sha256 = file_sha256(geometry_path)
    if geometry_sha256 != result["geometry_sha256"]:
        raise ValueError("The fitted geometry archive hash differs from the fit receipt")

    with np.load(geometry_path, allow_pickle=False) as archive:
        source = (archive["source_positions"], archive["source_faces"])
        meshoptimizer = (archive["meshoptimizer_positions"],
                         archive["meshoptimizer_faces"])
        fitted = (archive["fitted_positions"], archive["fitted_faces"])
    target_faces = len(meshoptimizer[1])
    if (len(fitted[1]) != target_faces
            or not np.array_equal(meshoptimizer[1], fitted[1])):
        raise ValueError("The fit does not preserve the initializer's exact topology")

    qem = qem_simplify(source[0], source[1], target_faces)
    qem_mesh = (qem.positions, qem.triangles)
    source_boundary = boundary(*source)
    qem_audit = audit(source_boundary, *qem_mesh)
    if qem_audit["faces"] != target_faces or not qem_audit["boundary_preserved"]:
        raise ValueError(f"The exact-face QEM control is ineligible: {qem_audit}")

    import drjit as dr
    import mitsuba as mi

    mi.set_variant("llvm_ad_rgb")
    dr.set_thread_count(2)
    _, heldout_views = camera_sets()
    variants = {"source": source, "qem": qem_mesh,
                "meshoptimizer": meshoptimizer, "fitted": fitted}
    scored = score(mi, variants, heldout_views, args.out.parent / "qem-score")
    surface = {name: surface_metrics(source, mesh, 20000, 20261125)
               for name, mesh in variants.items()}

    args.out.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "status": "complete",
        "source_path": args.source.as_posix(),
        "source_sha256": result["source_sha256"],
        "fit_result_sha256": file_sha256(args.result),
        "fit_geometry_sha256": geometry_sha256,
        "fit_script_sha256": result["script_sha256"],
        "qem_scoring_script_sha256": file_sha256(Path(__file__)),
        "source_faces": result["source_faces"],
        "target_faces": target_faces,
        "qem_audit": qem_audit,
        "meshoptimizer_audit": result["initial_audit"],
        "fitted_audit": result["fitted_audit"],
        "boundary_vertices_locked_for_fit": result["boundary_vertices_locked"],
        "heldout": {"camera_count": len(heldout_views),
                    "resolution": result["heldout"]["resolution"],
                    "spp": result["heldout"]["spp"],
                    "metrics": scored},
        "surface": surface,
        "limitations": [
            "This scores sampled held-out views only; the camera set is not region-blocked.",
            "The QEM control shares the exact face budget but not meshoptimizer topology.",
            "This CPU renderer screen does not measure MSAA, GPU cost, mobile behavior, or user preference."
        ]
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"asset": args.source.stem,
                      "target_faces": target_faces,
                      "qem_eligible": qem_audit["boundary_preserved"],
                      "means": scored["means"],
                      "scoring_script_sha256": receipt["qem_scoring_script_sha256"]},
                     separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
