"""Score every exact legal pair found by the fixed cluster-parameter sweep."""

import argparse
import hashlib
import json
import platform
from pathlib import Path
import subprocess

import numpy as np

from bench_upstream_clusterlod import OBJ_SCALE, assess, boundary, compact, digest
from cluster_decoder_pilot import read_stl
from compare_manymesh_clusterlod import load_position_ply
from audit_target_budget_visibility import load_obj


IMAGE_DELTA_KEYS = (
    "flip", "psnr_db", "ssim", "silhouette_xor_fraction", "coverage_mae",
)


def image_delta(candidate, baseline):
    return {key: candidate["image"][key] - baseline["image"][key]
            for key in IMAGE_DELTA_KEYS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--upstream-receipt", type=Path, required=True)
    parser.add_argument("--upstream-cut-dir", type=Path, required=True)
    parser.add_argument("--eligibility-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    upstream = json.loads(args.upstream_receipt.read_text(encoding="utf-8"))
    eligibility = json.loads(args.eligibility_receipt.read_text(encoding="utf-8"))
    upstream_by_id = {row["asset"]: row for row in upstream["assets"]}
    manifest_by_id = {row["file_id"]: row for row in manifest["files"]
                      if row["split"] == "validation"}
    protocol = upstream["protocol"]
    args.out.mkdir(parents=True, exist_ok=True)

    result = {
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip(),
        "score_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "manifest_sha256": digest(args.manifest),
        "upstream_receipt_sha256": digest(args.upstream_receipt),
        "eligibility_receipt_sha256": digest(args.eligibility_receipt),
        "mmgeo_sha256": eligibility["mmgeo_sha256"],
        "mmgeo_source_sha256": eligibility["mmgeo_source_sha256"],
        "protocol": protocol,
        "reference": "original full-resolution source mesh",
        "comparison": "ManyMesh DAG cut minus stock meshoptimizer cluster LOD cut",
        "delta_convention": "lower FLIP, silhouette XOR, coverage MAE are better; higher PSNR and SSIM are better",
        "pairs": [],
    }

    for asset in eligibility["assets"]:
        asset_id = asset["asset"]
        source_record = manifest_by_id[asset_id]
        source_path = args.manifest.parent / source_record["path"]
        if digest(source_path) != asset["source_sha256"]:
            raise ValueError(f"Source hash mismatch for asset {asset_id}")
        positions, faces = read_stl(source_path)
        center = (positions.min(axis=0) + positions.max(axis=0)) * 0.5
        radius = np.linalg.norm(positions - center, axis=1).max()
        positions = ((positions - center) / radius).astype(np.float32).astype(np.float64)
        reference = (positions, faces)
        reference_boundary = boundary(*reference)
        upstream_asset = upstream_by_id[asset_id]

        for setting in asset["settings"]:
            for eligibility_cut in setting.get("cuts", []):
                if not eligibility_cut.get("eligible_exact_face"):
                    continue
                depth = eligibility_cut["stock_depth"]
                candidate_ply = (
                    args.eligibility_receipt.parent / str(asset_id)
                    / f"ct{setting['cluster_triangles']}_dg{setting['dag_group']}"
                    / f"selected_ratio_{format(eligibility_cut['target_faces'] / len(faces), '.6g')}.ply"
                )
                if digest(candidate_ply) != eligibility_cut["ply_sha256"]:
                    raise ValueError(f"Candidate PLY hash mismatch: {candidate_ply}")
                candidate_positions, candidate_faces = load_position_ply(candidate_ply)
                candidate = compact(candidate_positions / OBJ_SCALE, candidate_faces)

                stock_entry = next(row for row in upstream_asset["cuts"]
                                   if row["cut"] == depth and row["status"] == "measured")
                if stock_entry["clusterlod"]["faces"] != eligibility_cut["target_faces"]:
                    raise ValueError(f"Stock face count mismatch for {asset_id}, depth {depth}")
                stock_obj = args.upstream_cut_dir / str(asset_id) / f"cut-{depth}.obj"
                stock_positions, stock_faces = load_obj(stock_obj)
                stock = compact(stock_positions / OBJ_SCALE, stock_faces)
                if len(stock[1]) != eligibility_cut["target_faces"]:
                    raise ValueError(f"Stock cut OBJ count mismatch: {stock_obj}")

                seed = int(asset_id)
                candidate_metrics = assess(
                    reference, candidate, reference_boundary,
                    protocol["views"], protocol["size"], seed,
                )
                stock_metrics = assess(
                    reference, stock, reference_boundary,
                    protocol["views"], protocol["size"], seed,
                )
                if (candidate_metrics["topology_error"] is not None
                        or not candidate_metrics["source_directed_boundary_preserved"]
                        or stock_metrics["topology_error"] is not None
                        or not stock_metrics["source_directed_boundary_preserved"]):
                    raise ValueError(f"Eligibility changed before scoring: asset {asset_id}")

                pair = {
                    "asset": asset_id,
                    "stock_depth": depth,
                    "cluster_triangles": setting["cluster_triangles"],
                    "dag_group": setting["dag_group"],
                    "faces": len(candidate[1]),
                    "candidate_ply_sha256": digest(candidate_ply),
                    "stock_obj_sha256": digest(stock_obj),
                    "candidate_minus_stock": image_delta(candidate_metrics, stock_metrics),
                    "candidate_image": candidate_metrics["image"],
                    "stock_image": stock_metrics["image"],
                    "candidate_per_view": candidate_metrics["per_view"],
                    "stock_per_view": stock_metrics["per_view"],
                    "candidate_surface": candidate_metrics["surface"],
                    "stock_surface": stock_metrics["surface"],
                }
                result["pairs"].append(pair)
                print(asset_id, depth, setting["cluster_triangles"], setting["dag_group"],
                      pair["candidate_minus_stock"], flush=True)

    out_path = args.out / "receipt.json"
    out_path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8")
    print(f"receipt: {out_path}", flush=True)


if __name__ == "__main__":
    main()
