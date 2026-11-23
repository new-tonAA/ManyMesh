#!/usr/bin/env python3
"""Join exact path-loss screens to inexpensive, mesh-local collapse features."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

import depth_candidate_pilot as raster


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dirs", type=Path, nargs="+",
                        default=[Path("out/filter-real-candidates"),
                                 Path("out/pathloss-captures")])
    parser.add_argument("--result-dirs", type=Path, nargs="+",
                        default=[Path("out"), Path("out/pathloss-captures")])
    parser.add_argument("--out", type=Path,
                        default=Path("out/pathloss-captures/path-loss-features.json"))
    args = parser.parse_args()

    capture_by_hash = {}
    for directory in args.capture_dirs:
        for path in sorted(directory.glob("*.json")):
            if path.name.startswith("shared-envelope-raster") or path.name.endswith("audit.json"):
                continue
            capture_by_hash[sha256(path)] = path

    feature_cache = {}
    rows = []
    seen_groups = set()
    unmatched = []
    for directory in args.result_dirs:
        for result_path in sorted(directory.glob("shared-envelope-raster*.json")):
            result = json.loads(result_path.read_text(encoding="utf-8"))
            digest = result.get("captureSha256")
            capture_path = capture_by_hash.get(digest)
            if capture_path is None:
                unmatched.append(result_path.name)
                continue
            group_key = (digest, tuple(result.get("candidateIds", ())),
                         tuple(result.get("path", ())), tuple(result.get("tileRect", ())),
                         result.get("cameraAngle"), result.get("panAngle", 0.0),
                         result.get("unitIndex", 0))
            if group_key in seen_groups:
                continue
            seen_groups.add(group_key)

            if digest not in feature_cache:
                capture = json.loads(capture_path.read_text(encoding="utf-8"))
                feature_cache[digest] = capture
            capture = feature_cache[digest]
            unit_index = result.get("unitIndex", 0)
            unit = capture["units"][unit_index]
            positions = np.asarray(unit["positions"], dtype=float)
            triangles = np.asarray(unit["triangles"], dtype=np.int64)
            candidates = unit["candidates"]
            face_normals = np.zeros((len(triangles), 3), dtype=float)
            face_areas = np.zeros(len(triangles), dtype=float)
            if len(triangles):
                v0, v1, v2 = (positions[triangles[:, i]] for i in range(3))
                cross = np.cross(v1 - v0, v2 - v0)
                lengths = np.linalg.norm(cross, axis=1)
                face_areas = 0.5 * lengths
                nonzero = lengths > 1e-15
                face_normals[nonzero] = cross[nonzero] / lengths[nonzero, None]
            vertex_valence = np.bincount(triangles.reshape(-1), minlength=len(positions))
            bounds_diagonal = max(float(np.linalg.norm(positions.max(axis=0) -
                                                         positions.min(axis=0))), 1e-12)
            angle = float(result.get("cameraAngle", 0.0))
            pan_angle = math.radians(float(result.get("panAngle", 0.0)))
            image_size = int(result.get("imageSize", 64))
            transform = raster.camera(positions, angle, image_size)
            projected = raster.project(positions, transform)
            tile = result.get("tileRect", [0, 0, image_size, image_size])
            tile_center = np.asarray([(tile[0] + tile[2]) * 0.5,
                                      (tile[1] + tile[3]) * 0.5])
            label_rows = result.get("candidateRasterRows", [])
            max_steps = max((int(row["steps"]) for row in label_rows), default=-1)
            min_steps = min((int(row["steps"]) for row in label_rows), default=-1)
            exact_by_id = {int(row["candidateId"]): float(row["exactEnergy"])
                           for row in label_rows if int(row["steps"]) == max_steps}
            coarse_by_id = {int(row["candidateId"]): float(row["rasterEnergy"])
                            for row in label_rows if int(row["steps"]) == min_steps}
            for candidate_id in result.get("candidateIds", ()):
                candidate_id = int(candidate_id)
                if candidate_id >= len(candidates) or candidate_id not in exact_by_id:
                    continue
                candidate = candidates[candidate_id]
                remove, keep = int(candidate["remove"]), int(candidate["keep"])
                target = np.asarray(candidate["target"], dtype=float)
                affected = np.asarray(candidate.get("affected", []), dtype=np.int64)
                affected = affected[(affected >= 0) & (affected < len(triangles))]
                if len(affected):
                    local_normals = face_normals[affected]
                    mean_normal = local_normals.mean(axis=0)
                    normal_dispersion = 1.0 - float(np.linalg.norm(mean_normal))
                    local_area = float(face_areas[affected].sum())
                    mean_area = float(face_areas[affected].mean())
                else:
                    normal_dispersion = 0.0
                    local_area = mean_area = 0.0
                midpoint = 0.5 * (projected[remove, :2] + projected[keep, :2])
                projected_target = raster.project(target.reshape(1, 3), transform)[0]
                features = {
                    "qem_priority": float(candidate["priority"]),
                    "edge_length_normalized": float(np.linalg.norm(
                        positions[remove] - positions[keep]) / bounds_diagonal),
                    "target_shift_normalized": float(np.linalg.norm(
                        target - positions[keep]) / bounds_diagonal),
                    "affected_face_count": int(len(affected)),
                    "remove_valence": int(vertex_valence[remove]),
                    "keep_valence": int(vertex_valence[keep]),
                    "affected_area_normalized": local_area / (bounds_diagonal ** 2),
                    "mean_affected_area_normalized": mean_area / (bounds_diagonal ** 2),
                    "normal_dispersion": normal_dispersion,
                    "projected_edge_length": float(np.linalg.norm(
                        projected[remove, :2] - projected[keep, :2]) / image_size),
                    "projected_target_shift": float(np.linalg.norm(
                        projected_target[:2] - projected[keep, :2]) / image_size),
                    "projected_midpoint_offset_x": float((midpoint[0] - tile_center[0]) /
                                                          image_size),
                    "projected_midpoint_offset_y": float((midpoint[1] - tile_center[1]) /
                                                          image_size),
                    "path_length_normalized": float((result["path"][1] -
                                                       result["path"][0]) / image_size),
                    "coarse_raster_energy": coarse_by_id[candidate_id],
                    "view_sin": math.sin(angle),
                    "view_cos": math.cos(angle),
                    "pan_sin": math.sin(pan_angle),
                    "pan_cos": math.cos(pan_angle),
                }
                rows.append({"group": len(seen_groups) - 1,
                             "capture": capture_path.name,
                             "result": result_path.name,
                             "candidateId": candidate_id,
                             "exactEnergy": exact_by_id[candidate_id],
                             "rasterSteps": min_steps,
                             "features": features})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"scope": "existing CPU path-loss screens; inexpensive local features",
                                   "warning": "small, correlated pilot set; not a train/test split",
                                   "groupCount": len(seen_groups), "rowCount": len(rows),
                                   "unmatchedResults": unmatched, "rows": rows},
                                  indent=2) + "\n", encoding="utf-8")
    nonnull = sum(any(row["exactEnergy"] > 1e-12 for row in rows
                      if row["group"] == group) for group in range(len(seen_groups)))
    print(json.dumps({"groupCount": len(seen_groups), "rowCount": len(rows),
                      "groupsWithNontrivialLoss": nonnull,
                      "unmatchedResultCount": len(unmatched), "output": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
