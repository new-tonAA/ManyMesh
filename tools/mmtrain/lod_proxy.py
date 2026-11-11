#!/usr/bin/env python3
#
# Copyright (C) 2026 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test a local finer cut as a reference for equal-budget LOD reallocation."""

import argparse
import csv
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import struct
from time import perf_counter

import numpy as np

from lod_oracle import digest
from lod_predictor import causal_path, load_trajectories
from lod_sequence import evaluate_trajectory
from lod_visibility import SILHOUETTE_METRIC, fragments, project, read_cut, z_buffer


class Graph:
    """Read just the hierarchy and triangle indices from an experimental MMLG v7 capture."""

    def __init__(self, data):
        # Serialized by serializeLodGraph in libs/manymesh/src/Streaming.cpp.
        magic, version, nodes, roots, leaves, _, _, self.vertices = struct.unpack_from(
            "<4s5IQI", data)
        if magic != b"MMLG" or version != 7:
            raise ValueError("Expected an MMLG v7 graph")
        cursor = 36 + 4 * (roots + leaves)
        generated, = struct.unpack_from("<I", data, cursor)
        cursor += 4 + 40 * generated
        positions, = struct.unpack_from("<I", data, cursor)
        cursor += 4
        if positions != self.vertices:
            raise ValueError("Expected one canonical position ID per vertex")
        self.positions = np.frombuffer(data, "<u4", positions, cursor)
        if np.any(self.positions >= self.vertices):
            raise ValueError("Invalid canonical position ID")
        cursor += 4 * positions
        self.offsets = np.frombuffer(data, "<u8", nodes + 1, cursor)
        if (self.offsets[0] != cursor + 8 * (nodes + 1) or self.offsets[-1] != len(data)
                or np.any(self.offsets[1:] <= self.offsets[:-1])):
            raise ValueError("Invalid graph offsets")
        self.data = data
        self.cache = {}

    def node(self, index):
        if index in self.cache:
            return self.cache[index]
        if not 0 <= index < len(self.offsets) - 1:
            raise ValueError(f"Invalid node {index}")
        start, end = map(int, self.offsets[index:index + 2])
        child_count, index_count = struct.unpack_from("<II", self.data, start + 16)
        payload = start + 184
        if index_count % 3 or payload + 4 * (child_count + index_count) != end:
            raise ValueError(f"Invalid node record {index}")
        children = struct.unpack_from(f"<{child_count}I", self.data, payload)
        indices = np.frombuffer(self.data, "<u4", index_count, payload + 4 * child_count)
        self.cache[index] = children, self.faces(indices.reshape(-1, 3))
        return self.cache[index]

    def faces(self, faces):
        indices = np.asarray(faces, dtype=np.intp).reshape(-1, 3)
        if np.any(indices < 0) or np.any(indices >= self.vertices):
            raise ValueError("Invalid triangle index")
        return {tuple(face) for face in np.sort(self.positions[indices], axis=1).tolist()}

    def cut(self, nodes):
        return set().union(*(self.node(node)[1] for node in nodes))

    def refine(self, nodes):
        return {child for node in nodes for child in (self.node(node)[0] or (node,))}


def surface_loss(depth, reference):
    occupied = (depth > 0) | (reference > 0)
    a, b = depth[occupied], reference[occupied]
    denominator = max(len(a), 1)
    outline = np.count_nonzero((a == 0) ^ (b == 0)) / denominator
    # Background mismatches contribute one; covered pixels contribute relative depth error.
    surface = float(np.sum(np.abs(a - b) / np.maximum(a, b))) / denominator
    return np.array([outline, surface])


def frame_scores(path, view, width, height, graph):
    with (path / "oracle.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))[1:]
    positions, faces, vertices = read_cut(path / "oracle_baseline.obj", True)
    baseline = graph.faces(faces)
    if len(positions) != graph.vertices or len(baseline) != int(rows[0]["triangles"]):
        raise ValueError(f"Unexpected baseline geometry: {path}")
    candidates, touched = [baseline], set()
    for row in rows[1:]:
        split, merge = int(row["split"]), int(row["merge"])
        split_children, _ = graph.node(split)
        merge_children, _ = graph.node(merge)
        old_nodes = {split, *merge_children}
        old_faces = graph.cut(old_nodes)
        if not split_children or not merge_children or not old_faces <= baseline:
            raise ValueError(f"Unexpected swap nodes: {path / row['stem']}")
        candidate = (baseline - old_faces) | graph.cut({merge, *split_children})
        _, exported, candidate_vertices = read_cut(path / f"{row['stem']}.obj", False)
        if (candidate_vertices != vertices or len(candidate) != len(baseline)
                or candidate != graph.faces(exported)):
            raise ValueError(f"Graph swap disagrees with exported cut: {path / row['stem']}")
        candidates.append(candidate)
        touched.update(old_nodes)

    start = perf_counter()
    # Every candidate is evaluated against the same reference. Refine only regions
    # touched by at least one candidate, so unrelated regions keep their baseline LOD.
    unchanged = baseline - graph.cut(touched)
    fine_nodes = graph.refine(touched)
    one_level = unchanged | graph.cut(fine_nodes)
    two_levels = unchanged | graph.cut(graph.refine(fine_nodes))
    cuts = [*candidates, one_level, two_levels]
    triangles = sorted(set.union(*cuts))
    ids = {tri: i for i, tri in enumerate(triangles)}
    projected = project(positions, view["eye"], view["target"], width, height)
    face, pixel, depth = fragments(projected, triangles, width, height)
    depths = []
    for cut in cuts:
        included = np.zeros(len(triangles), dtype=bool)
        included[[ids[tri] for tri in cut]] = True
        keep = included[face]
        depths.append(z_buffer(pixel[keep], depth[keep], width * height))

    scores = {}
    for level, reference in enumerate(depths[-2:], 1):
        errors = np.array([surface_loss(z, reference) for z in depths[:-2]])
        gains = errors[0] - errors
        scores[f"proxy{level}_outline"] = gains[:, 0]
        scores[f"proxy{level}_surface"] = gains[:, 1]
    return scores, {
        "candidates": len(rows) - 1,
        "baseline_triangles": len(baseline),
        "candidate_triangles_outside_baseline": len(set.union(*candidates) - baseline),
        "proxy1_triangles_outside_candidates": len(one_level - set.union(*candidates)),
        "proxy2_triangles_outside_candidates": len(two_levels - set.union(*candidates)),
        "shared_raster_triangles": len(triangles),
        "independent_raster_triangles": sum(map(len, cuts)),
        "prototype_ms": 1000 * (perf_counter() - start),
    }


@lru_cache(maxsize=4)
def graph_for(graph_hash, data):
    if hashlib.sha256(data).hexdigest() != graph_hash:
        raise ValueError("Graph differs from capture metadata")
    return Graph(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", nargs="+", type=Path, required=True)
    parser.add_argument("--silhouette", nargs="+", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    outlines = {}
    for path in args.silhouette:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["metric"] != SILHOUETTE_METRIC or outlines.keys() & data["captures"].keys():
            raise ValueError(f"Unexpected silhouette data: {path}")
        outlines.update(data["captures"])
    reports = []
    for trajectory in load_trajectories(args.scores, None, outlines):
        root = trajectory.source.parent
        manifest = root / "geometry.json"
        geometry = json.loads(manifest.read_text(encoding="utf-8"))
        width, height = geometry["width"], geometry["height"]
        if (width, height) != (trajectory.capture["width"], trajectory.capture["height"]):
            raise ValueError(f"Capture dimensions disagree: {root}")
        views = {view["directory"]: view for view in geometry["views"]}
        scores, cost = [], []
        for meta, view in zip(trajectory.metadata, trajectory.views, strict=True):
            if any(meta[key] != views[meta["directory"]][key]
                   for key in ("eye", "target", "graph_sha256", "asset_sha256")):
                raise ValueError(f"Capture metadata disagree: {root}")
            path = root / meta["directory"]
            graph = graph_for(meta["graph_sha256"], (path / "lod_graph.mmb").read_bytes())
            frame, work = frame_scores(path, meta, width, height, graph)
            rows = view["candidates"]
            with (path / "oracle.csv").open(newline="") as stream:
                keys = ("stem", "triangles", "split", "merge", "geometric_score")
                if [tuple(row[k] for k in keys) for row in list(csv.DictReader(stream))[1:]] != [
                        tuple(row[k] for k in keys) for row in rows]:
                    raise ValueError(f"Score rows do not match the graph swaps: {path}")
            frame["geometry"] = np.array([0.0] + [float(r["geometric_score"]) for r in rows[1:]])
            scores.append(frame)
            cost.append(work)

        def select_paths(churn):
            paths = {}
            for name in scores[0]:
                series = [frame[name] for frame in scores]
                paths[f"{name}_frame"] = [int(np.argmax(frame)) for frame in series]
                paths[f"{name}_causal"] = causal_path(series, churn, 0, 0)
            return paths

        report = evaluate_trajectory(root, trajectory.metadata, trajectory.views, [], select_paths)
        report.update(capture_sha256=digest(manifest), target_ratio=geometry["target_ratio"],
                      start_degrees=geometry["start_degrees"], work_by_frame=cost)
        reports.append(report)
        print(f"{root.name} {report['asset']}: {sum(w['candidates'] for w in cost)} swaps",
              flush=True)
    args.out.write_text(json.dumps(reports, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
