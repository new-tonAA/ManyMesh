#!/usr/bin/env python3
"""Recompute whole-cut projected-error proxies for mmgeo equal-face candidates."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def source_bounds(path):
    positions = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.startswith("v "):
                parts = line.split()
                if len(parts) >= 4:
                    positions.append(tuple(float(value) for value in parts[1:4]))
    if not positions:
        raise ValueError(f"no OBJ vertex positions in {path}")
    low = tuple(min(p[axis] for p in positions) for axis in range(3))
    high = tuple(max(p[axis] for p in positions) for axis in range(3))
    center = tuple((low[axis] + high[axis]) * 0.5 for axis in range(3))
    extent = tuple(high[axis] - low[axis] for axis in range(3))
    return low, high, center, extent


def auto_camera(extent, center, height=1080, fov_degrees=45.0):
    width = height * 16 // 9
    tan_half_fov = math.tan(math.radians(fov_degrees * 0.5))
    aspect = width / max(height, 1)
    distance_height = (extent[1] * 0.5) / tan_half_fov
    distance_width = (extent[0] * 0.5) / (tan_half_fov * aspect)
    distance = max(distance_height, distance_width) * 1.05 + extent[2] * 0.5
    eye = (center[0], center[1], center[2] + max(distance, 1e-3))
    near = max(distance * 0.01, 1e-4)
    pixels_per_radian = height / (2.0 * tan_half_fov)
    return eye, near, pixels_per_radian, distance


def reconstruct_cut(row, base, nodes):
    selected = set(base)
    split_ids = [int(value) for value in row["split"].split("+") if value]
    merge_ids = [int(value) for value in row["merge"].split("+") if value]
    for split_id in split_ids:
        selected.discard(split_id)
        selected.update(nodes[split_id]["children"])
    for merge_id in merge_ids:
        descendants = set()
        for node_id in selected:
            parent_id = nodes[node_id]["parent"]
            while parent_id != 4294967295:
                if parent_id == merge_id:
                    descendants.add(node_id)
                    break
                parent_id = nodes[parent_id]["parent"]
        selected.difference_update(descendants)
        selected.add(merge_id)
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--mesh", type=Path,
            default=Path("third_party/meshoptimizer/demo/pirate.obj"))
    args = parser.parse_args()
    graph_path = args.output_dir / "lod_graph.json"
    manifest_path = args.output_dir / "oracle.csv"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in graph["dag"]}
    base = set(graph["selectedNodes"])
    low, high, center, extent = source_bounds(args.mesh)
    eye, near, pixels_per_radian, distance = auto_camera(extent, center)

    def node_error(node_id):
        node = nodes[node_id]
        sphere = node["bounds"]
        center_z = sphere["center"][2]
        depth = eye[2] - center_z - sphere["radius"]
        return node["accumulatedError"] / max(depth, near) * pixels_per_radian

    def cut_error(cut):
        return max((node_error(node_id) for node_id in cut), default=0.0)

    baseline_error = cut_error(base)
    results = []
    with manifest_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if not row["stem"].startswith("oracle_") or row["stem"] in (
                    "oracle_reference", "oracle_baseline"):
                continue
            cut = reconstruct_cut(row, base, nodes)
            triangles = sum(nodes[node_id]["tri"] for node_id in cut)
            expected_triangles = int(row["triangles"])
            if triangles != expected_triangles:
                raise ValueError(f"{row['stem']} reconstructs to {triangles} faces, "
                        f"manifest says {expected_triangles}")
            results.append({"stem": row["stem"], "triangles": triangles,
                    "worstProjectedErrorPx": cut_error(cut),
                    "split": row["split"], "merge": row["merge"]})
    if not results:
        raise ValueError("candidate manifest contains no oracle alternatives")

    summaries = {}
    for label, values in (
            ("singleSwap", [r["worstProjectedErrorPx"] for r in results
                    if r["stem"].startswith("oracle_swap_")]),
            ("composite", [r["worstProjectedErrorPx"] for r in results
                    if r["stem"].startswith("oracle_composite_")]),
            ("all", [r["worstProjectedErrorPx"] for r in results])):
        ordered = sorted(values)
        if ordered:
            summaries[label] = {"count": len(ordered), "min": ordered[0],
                    "median": ordered[len(ordered) // 2], "max": ordered[-1],
                    "improvesBaseline": any(value < baseline_error for value in ordered)}

    result = {
        "scope": "bounded equal-face cut candidates; projected geometric-error proxy, not rendered image quality",
        "camera": {"eye": eye, "center": center, "distance": distance,
                "screen": [1920, 1080], "fovYDegrees": 45.0, "near": near},
        "baseline": {"triangles": graph["selectedTriangles"],
                "reportedWorstProjectedErrorPx": graph["maxScreenErrorPx"],
                "recomputedWorstProjectedErrorPx": baseline_error},
        "candidateSummaries": summaries,
        "bestCandidates": sorted(results,
                key=lambda item: item["worstProjectedErrorPx"])[:10],
        "candidates": results,
        "inputs": {"meshSha256": sha256(args.mesh),
                "graphSha256": sha256(graph_path), "manifestSha256": sha256(manifest_path),
                "analysisScriptSha256": sha256(Path(__file__))}}
    output_path = args.output_dir / "oracle_screen_analysis.json"
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"baseline": result["baseline"],
            "candidateSummaries": summaries, "output": str(output_path)}, indent=2))


if __name__ == "__main__":
    main()
