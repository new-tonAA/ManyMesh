"""Score exact-face existing DAG and meshoptimizer cuts on the contour test views."""

import argparse
import json
from pathlib import Path

from bench_contour_importance_qem import compare_images
from preflight_appearance_meshes import (
    audit, boundary, compact, digest, load_binary_ply, load_obj,
    meshopt_simplify_raw, normalize, source_frame,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--preflight-receipt", type=Path, required=True)
    parser.add_argument("--cut", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    preflight = json.loads(args.preflight_receipt.read_text(encoding="utf-8"))
    source_sha = digest(args.source)
    if source_sha != preflight["source_sha256"]:
        parser.error("Source OBJ does not match the earlier cut receipt")
    cut_sha = digest(args.cut)
    prior_cut = next((row for row in preflight["cuts"]
                      if row["candidate_ply_sha256"] == cut_sha), None)
    if prior_cut is None:
        parser.error("DAG cut does not match the earlier cut receipt")

    raw, faces = load_obj(args.source)
    center, radius = source_frame(raw)
    points = normalize(raw, center, radius)
    source = compact(points, faces)
    edges = boundary(*source)
    target = len(faces) - 2 * round(len(faces) / 4)
    cut_points, cut_faces = load_binary_ply(args.cut)
    dag = compact(normalize(cut_points, center, radius), cut_faces)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    control_points, control_faces, _ = meshopt_simplify_raw(
        points, faces, target, args.output.parent)
    variants = {"manymesh": dag, "meshoptimizer": (control_points, control_faces)}
    audits = {name: audit(edges, *geometry) for name, geometry in variants.items()}
    eligible = {name: geometry for name, geometry in variants.items()
                if audits[name]["faces"] == target and audits[name]["boundary_preserved"]}
    result = {
        "source_sha256": source_sha, "cut_sha256": cut_sha,
        "mmgeo_sha256": preflight["mmgeo_sha256"],
        "script_sha256": digest(Path(__file__)), "target_faces": target,
        "arms": audits, "views": compare_images(source, eligible) if eligible else [],
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
