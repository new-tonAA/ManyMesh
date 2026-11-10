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

"""Measure equal-budget LOD changes along an ordered camera trajectory."""

import argparse
from itertools import groupby
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


def image(path):
    with Image.open(path) as png:
        return np.asarray(png.convert("RGB"), dtype=np.float32).reshape(-1) / 255


def faces(path):
    # Every cut of a fixed graph uses the same global vertex IDs in the OBJ export.
    with path.open() as obj:
        return {tuple(sorted(int(word.split("/", 1)[0]) for word in line.split()[1:]))
                for line in obj if line.startswith("f ")}


def load_frame(path, rows):
    reference = image(path / "oracle_reference.png")
    residuals = []
    triangles = []
    for row in rows:
        stem = row["stem"]
        residuals.append(image(path / f"{stem}.png") - reference)
        cut = faces(path / f"{stem}.obj")
        if len(cut) != int(row["triangles"]):
            raise ValueError(f"OBJ face identity is not unique: {path / stem}")
        triangles.append(cut)
    return residuals, triangles


def transitions(previous, current):
    prev_images, prev_faces = previous
    images, triangles = current
    temporal = np.empty((len(prev_images), len(images)))
    churn = np.empty_like(temporal)
    for i, (prev_image, prev_cut) in enumerate(zip(prev_images, prev_faces)):
        for j, (rgb, cut) in enumerate(zip(images, triangles)):
            # Screen-space change in the error relative to the full-detail motion.
            temporal[i, j] = np.mean(np.square(rgb - prev_image), dtype=np.float64)
            shared = len(prev_cut & cut)
            total = len(prev_cut) + len(cut)
            churn[i, j] = (total - 2 * shared) / (total - shared)
    return temporal, churn


def guarded_path(errors, silhouettes, edges, guard_churn):
    # A path through the baseline is feasible by construction. We minimize summed RGB
    # error while limiting each frame and transition to its paired baseline errors.
    valid = [(e <= e[0]) & (s <= s[0]) for e, s in zip(errors, silhouettes)]
    costs = np.where(valid[0], errors[0], np.inf)
    parents = []
    for t, (temporal, churn) in enumerate(edges, 1):
        allowed = temporal <= temporal[0, 0]
        if guard_churn:
            allowed &= churn <= churn[0, 0]
        candidates = np.where(allowed, costs[:, None], np.inf)
        previous = np.argmin(candidates, axis=0)
        parents.append(previous)
        costs = candidates[previous, np.arange(len(previous))] + errors[t]
        costs = np.where(valid[t], costs, np.inf)
    path = [int(np.argmin(costs))]
    for parent in reversed(parents):
        path.append(int(parent[path[-1]]))
    return path[::-1]


def psnr_gain(baseline, candidate):
    return 10 * math.log10(max(baseline, 1e-12) / max(candidate, 1e-12))


def evaluate_trajectory(root, metadata, views, strengths, select_paths=None):
    rows = [view["candidates"] for view in views]
    errors = [np.array([row["raw_mse"] for row in frame]) for frame in rows]
    silhouettes = [np.array([row["silhouette_xor_over_union"] for row in frame])
                   for frame in rows]
    edges = []
    previous = load_frame(root / views[0]["directory"], rows[0])
    for view, frame in zip(views[1:], rows[1:]):
        current = load_frame(root / view["directory"], frame)
        edges.append(transitions(previous, current))
        previous = current

    raw = [int(np.argmin(e)) for e in errors]
    strategies = {
        "baseline": [0] * len(views),
        "geometric": [next(i for i, row in enumerate(frame)
                           if row["stem"] == view["geometric_choice"])
                      for view, frame in zip(views, rows)],
        "frame_oracle": raw,
        "image_guarded_oracle": guarded_path(errors, silhouettes, edges, False),
        "all_guarded_oracle": guarded_path(errors, silhouettes, edges, True),
    }
    if select_paths is not None:
        strategies.update(select_paths([churn for _, churn in edges]))
    reports = {}
    for name, path in strategies.items():
        gain = [psnr_gain(e[0], e[i]) for e, i in zip(errors, path)]
        outline = [float(s[i] - s[0]) for s, i in zip(silhouettes, path)]
        temporal = [float(edge[0][a, b]) for edge, a, b in zip(edges, path, path[1:])]
        churn = [float(edge[1][a, b]) for edge, a, b in zip(edges, path, path[1:])]
        reports[name] = {
            "chosen": [frame[i]["stem"] for frame, i in zip(rows, path)],
            "median_psnr_gain_db": float(np.median(gain)),
            "mean_silhouette_delta": float(np.mean(outline)),
            "mean_temporal_error_mse": float(np.mean(temporal)),
            "mean_triangle_churn": float(np.mean(churn)),
            "frames_with_worse_silhouette": sum(delta > 0 for delta in outline),
            "edges_with_worse_temporal_error": sum(
                int(value > edge[0][0, 0]) for value, edge in zip(temporal, edges)),
            "edges_with_worse_churn": sum(
                int(value > edge[1][0, 0]) for value, edge in zip(churn, edges)),
            "psnr_gain_db_by_frame": gain,
            "silhouette_delta_by_frame": outline,
            "temporal_error_mse_by_edge": temporal,
            "triangle_churn_by_edge": churn,
        }

    ranking = {}
    for strength in strengths:
        key = str(strength)
        scores = [[row["mse_by_strength"][key] for row in frame] for frame in rows]
        winners = [int(np.argmin(s)) for s in scores]
        gain = [psnr_gain(s[r], s[w]) for s, r, w in zip(scores, raw, winners)]
        ranking[key] = {
            "changed_choices": sum(r != w for r, w in zip(raw, winners)),
            "median_extra_psnr_db": float(np.median(gain)),
            "max_extra_psnr_db": max(gain),
            "extra_psnr_db_by_frame": gain,
        }
    return {
        "asset": metadata[0]["asset"],
        "asset_sha256": metadata[0]["asset_sha256"],
        "frames": len(views),
        "swaps": sum(len(frame) - 1 for frame in rows),
        "triangle_counts": [int(frame[0]["triangles"]) for frame in rows],
        "strategies": reports,
        "reconstruction_ranking": ranking,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    results = []
    paired_inputs = {}
    for score in args.score:
        data = json.loads(score.read_text(encoding="utf-8"))
        capture = data["capture"]
        if not 0 < capture.get("arc_degrees", 360) < 360:
            raise ValueError(f"Expected a partial camera arc: {score}")
        sequence = {"capture": capture, "checkpoint_sha256": data["checkpoint_sha256"],
                    "score": str(score), "trajectories": []}
        pairs = zip(capture["views"], data["views"], strict=True)
        for _, group in groupby(pairs, key=lambda pair: pair[0]["asset_sha256"]):
            meta, views = map(list, zip(*group))
            if (len(views) < 2 or len({frame["graph_sha256"] for frame in meta}) != 1
                    or any(m["directory"] != v["directory"] for m, v in zip(meta, views))):
                raise ValueError(f"Invalid trajectory in {score}")
            asset = meta[0]["asset_sha256"]
            signature = (meta[0]["graph_sha256"], capture["width"], capture["height"],
                         data["checkpoint_sha256"], data["strengths"],
                         [(m["eye"], m["target"]) for m in meta])
            if paired_inputs.setdefault(asset, signature) != signature:
                raise ValueError(f"Unmatched graph, camera, or reconstruction for {score}")
            report = evaluate_trajectory(score.parent, meta, views, data["strengths"])
            sequence["trajectories"].append(report)
            print(f"{report['asset']} @ {capture['target_ratio']:.0%}: "
                  f"{report['frames']} frames, {report['swaps']} swaps", flush=True)
        results.append(sequence)
    args.out.write_text(json.dumps(results, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
