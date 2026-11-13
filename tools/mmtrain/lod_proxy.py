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


def resolve_cuts(cuts, triangles, face, pixel, depth, count):
    """Resolve shared fragments once, preserving exact per-cut nearest depth.

    The intersection includes the finer references and optional interaction cuts:
    geometry common only to the candidates must not occlude either reference.
    Duplicate cuts share a read-only result (notably identical refinement levels).
    """
    common = set.intersection(*cuts)
    common_ids = np.array([tri in common for tri in triangles], dtype=bool)
    shared = common_ids[face]
    base = z_buffer(pixel[shared], depth[shared], count)
    variable_face = face[~shared]
    variable_pixel, variable_depth = pixel[~shared], depth[~shared]
    ids = {tri: i for i, tri in enumerate(triangles)}
    cache, resolved = {}, []
    for cut in cuts:
        key = frozenset(cut - common)
        if key not in cache:
            included = np.zeros(len(triangles), dtype=bool)
            included[[ids[tri] for tri in key]] = True
            keep = included[variable_face]
            image = np.maximum(base, z_buffer(variable_pixel[keep], variable_depth[keep], count))
            image.flags.writeable = False
            cache[key] = image
        resolved.append(cache[key])
    return resolved, {
        "common_raster_triangles": len(common),
        "shared_fragments": int(shared.sum()),
        "variable_fragments": len(variable_face),
        "unique_depth_resolves": len(cache),
    }


def frame_scores(path, view, width, height, graph, measure_interactions=False, shared_depth=False):
    with (path / "oracle.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))[1:]
    positions, faces, vertices = read_cut(path / "oracle_baseline.obj", True)
    baseline = graph.faces(faces)
    if len(positions) != graph.vertices or len(baseline) != int(rows[0]["triangles"]):
        raise ValueError(f"Unexpected baseline geometry: {path}")
    graph_json = path / "lod_graph.json"
    selected = None
    parents = None
    if graph_json.exists():
        metadata = json.loads(graph_json.read_text(encoding="utf-8"))
        selected = metadata["selectedNodes"]
        parents = [node["parent"] for node in metadata["dag"]]
        if graph.cut(selected) != baseline:
            raise ValueError(f"Selected nodes disagree with exported baseline: {path}")

    def below(node, ancestor):
        while node != 0xffffffff:
            if node == ancestor:
                return True
            node = parents[node]
        return False

    candidates, touched = [baseline], set()
    components, component_ranges = [], []
    for row in rows[1:]:
        splits = [int(value) for value in row["split"].split("+")]
        merges = [int(value) for value in row["merge"].split("+")]
        old_nodes = set(splits)
        for merge in merges:
            if selected is None:
                old_nodes.update(graph.node(merge)[0])
            else:
                old_nodes.update(node for node in selected if below(node, merge))
        old_faces = graph.cut(old_nodes)
        if (any(not graph.node(split)[0] for split in splits)
                or any(not graph.node(merge)[0] for merge in merges)
                or not old_faces <= baseline):
            raise ValueError(f"Unexpected swap nodes: {path / row['stem']}")
        new_nodes = set(merges)
        for split in splits:
            new_nodes.update(graph.node(split)[0])
        candidate = (baseline - old_faces) | graph.cut(new_nodes)
        _, exported, candidate_vertices = read_cut(path / f"{row['stem']}.obj", False)
        if (candidate_vertices != vertices or len(candidate) != len(baseline)
                or candidate != graph.faces(exported)):
            raise ValueError(f"Graph swap disagrees with exported cut: {path / row['stem']}")
        candidates.append(candidate)
        touched.update(old_nodes)
        if measure_interactions and len(splits) + len(merges) > 2:
            first = len(components)
            for split in splits:
                components.append((baseline - graph.cut({split})) |
                                  graph.cut(graph.node(split)[0]))
            for merge in merges:
                descendants = {node for node in selected if below(node, merge)}
                components.append((baseline - graph.cut(descendants)) |
                                  graph.cut({merge}))
            component_ranges.append((len(candidates) - 1, first, len(components)))

    start = perf_counter()
    if len(candidates) == 1:
        # With no reallocations, no nodes are touched: both finer references
        # equal the baseline. Every gain is exactly zero without rasterization.
        scores = {f"proxy{level}_{loss}": np.zeros(1)
                  for level in (1, 2) for loss in ("outline", "surface")}
        work = {
            "candidates": 0, "baseline_triangles": len(baseline),
            "candidate_triangles_outside_baseline": 0,
            "proxy1_triangles_outside_candidates": 0,
            "proxy2_triangles_outside_candidates": 0,
            "shared_raster_triangles": 0, "independent_raster_triangles": 0,
            "prototype_ms": 1000 * (perf_counter() - start),
        }
        if measure_interactions:
            work.update(interaction_count=0, interaction_mean_abs=0,
                        interaction_max_abs=0, interaction_values=[])
        return scores, work
    # Every candidate is evaluated against the same reference. Refine only regions
    # touched by at least one candidate, so unrelated regions keep their baseline LOD.
    unchanged = baseline - graph.cut(touched)
    fine_nodes = graph.refine(touched)
    one_level = unchanged | graph.cut(fine_nodes)
    two_levels = unchanged | graph.cut(graph.refine(fine_nodes))
    cuts = [*candidates, *components, one_level, two_levels]
    triangles = sorted(set.union(*cuts))
    projected = project(positions, view["eye"], view["target"], width, height)
    face, pixel, depth = fragments(projected, triangles, width, height)
    if shared_depth:
        depths, resolve_work = resolve_cuts(cuts, triangles, face, pixel, depth, width * height)
    else:
        ids = {tri: i for i, tri in enumerate(triangles)}
        depths, resolve_work = [], {}
        for cut in cuts:
            included = np.zeros(len(triangles), dtype=bool)
            included[[ids[tri] for tri in cut]] = True
            keep = included[face]
            depths.append(z_buffer(pixel[keep], depth[keep], width * height))

    scores = {}
    for level, reference in enumerate(depths[-2:], 1):
        errors = np.array([surface_loss(z, reference) for z in depths[:-2]])
        gains = errors[0] - errors
        scores[f"proxy{level}_outline"] = gains[:len(candidates), 0]
        scores[f"proxy{level}_surface"] = gains[:len(candidates), 1]
        if level == 1 and measure_interactions:
            def fixed_surface(image):
                difference = np.abs(image - reference)
                denominator = np.maximum(image, reference)
                return float(np.sum(np.divide(difference, denominator,
                                              out=np.zeros_like(difference),
                                              where=denominator > 0))) / len(image)

            fixed = np.array([fixed_surface(image) for image in depths[:-2]])
            fixed_gain = fixed[0] - fixed
            interactions = [fixed_gain[index] - fixed_gain[
                    len(candidates) + first:len(candidates) + last].sum()
                    for index, first, last in component_ranges]
    work = {
        "candidates": len(rows) - 1,
        "baseline_triangles": len(baseline),
        "candidate_triangles_outside_baseline": len(set.union(*candidates) - baseline),
        "proxy1_triangles_outside_candidates": len(one_level - set.union(*candidates)),
        "proxy2_triangles_outside_candidates": len(two_levels - set.union(*candidates)),
        "shared_raster_triangles": len(triangles),
        "independent_raster_triangles": sum(map(len, cuts)),
        "prototype_ms": 1000 * (perf_counter() - start),
        **resolve_work,
    }
    if measure_interactions:
        work["interaction_count"] = len(component_ranges)
        work["interaction_mean_abs"] = float(np.mean(np.abs(interactions))) if interactions else 0
        work["interaction_max_abs"] = float(np.max(np.abs(interactions))) if interactions else 0
        work["interaction_values"] = [float(value) for value in interactions]
    return scores, work


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
    parser.add_argument("--interactions", action="store_true",
                        help="Measure deviation from summed single-operation proxy gains")
    parser.add_argument("--proxy-height", type=int,
                        help="Score geometry on a smaller grid; evaluate images at capture size")
    parser.add_argument("--shared-depth", action="store_true",
                        help="Resolve common fragments once (experimental CPU cost tradeoff)")
    args = parser.parse_args()
    if args.proxy_height is not None and args.proxy_height <= 0:
        parser.error("--proxy-height must be positive")
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
        if args.proxy_height is not None:
            if args.proxy_height > height:
                raise ValueError("Proxy height must not exceed capture height")
            width, height = max(1, round(width * args.proxy_height / height)), args.proxy_height
        views = {view["directory"]: view for view in geometry["views"]}
        scores, cost = [], []
        for meta, view in zip(trajectory.metadata, trajectory.views, strict=True):
            if any(meta[key] != views[meta["directory"]][key]
                   for key in ("eye", "target", "graph_sha256", "asset_sha256")):
                raise ValueError(f"Capture metadata disagree: {root}")
            path = root / meta["directory"]
            graph = graph_for(meta["graph_sha256"], (path / "lod_graph.mmb").read_bytes())
            frame, work = frame_scores(path, meta, width, height, graph, args.interactions,
                                       args.shared_depth)
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
                      start_degrees=geometry["start_degrees"], work_by_frame=cost,
                      proxy_width=width, proxy_height=height, shared_depth=args.shared_depth)
        reports.append(report)
        print(f"{root.name} {report['asset']}: {sum(w['candidates'] for w in cost)} swaps",
              flush=True)
    args.out.write_text(json.dumps(reports, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
