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

"""Train and replay causal LOD swap predictors with whole assets held out."""

import argparse
from collections import Counter
from dataclasses import dataclass
from itertools import groupby
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

from lod_oracle import digest
from lod_sequence import evaluate_trajectory, psnr_gain
from lod_visibility import SILHOUETTE_METRIC, VISIBILITY_FIELDS


PROJECTION_FIELDS = ("split_px", "split_child_px", "split_radius_px",
                     "merge_px", "merge_child_px", "merge_radius_px")
FEATURES = PROJECTION_FIELDS + ("exchange_fraction", "target_ratio", "geometric_score")
SILHOUETTE_COST = 1000.0
GAIN_LIMIT_DB = 1.0
ACCEPT_MARGIN_DB = 0.02
CHURN_COST = 1.0
RIDGE_PENALTY = 0.05
MLP_WIDTH = 16
MLP_STEPS = 180
MLP_SEED = 17


@dataclass
class Trajectory:
    source: Path
    capture: dict
    metadata: list
    views: list
    visibility: dict

    @property
    def asset(self):
        return self.metadata[0]["asset_sha256"]


def load_trajectories(paths, visibility, silhouettes):
    trajectories = []
    seen = set()
    graph_by_asset = {}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        capture = data["capture"]
        if visibility is not None or silhouettes is not None:
            capture_id = digest(path.parent / "geometry.json")
        visibility_frames = {}
        if visibility is not None:
            visibility_frames = visibility[capture_id]
            for view in data["views"]:
                frame = visibility_frames[view["directory"]]
                expected = {r["stem"] for r in view["candidates"][1:]}
                if set(frame) != expected or any(
                        len(values) != len(VISIBILITY_FIELDS)
                        or not np.all(np.isfinite(values)) or np.any(np.asarray(values) < 0)
                        for values in frame.values()):
                    raise ValueError(f"Visibility data does not match candidates: {path}")
        if silhouettes is not None:
            for view in data["views"]:
                outline = silhouettes[capture_id][view["directory"]]
                if (set(outline) != {row["stem"] for row in view["candidates"]}
                        or any(not 0 <= error <= 1 for error in outline.values())):
                    raise ValueError(f"Silhouette labels do not match candidates: {path}")
                for row in view["candidates"]:
                    row["silhouette_xor_over_union"] = outline[row["stem"]]
        if not 0 < capture.get("arc_degrees", 360) < 360:
            raise ValueError(f"Expected an ordered camera arc: {path}")
        pairs = zip(capture["views"], data["views"], strict=True)
        for asset, group in groupby(pairs, key=lambda pair: pair[0]["asset_sha256"]):
            metadata, views = map(list, zip(*group))
            graph = metadata[0]["graph_sha256"]
            if (len(views) < 2 or graph_by_asset.setdefault(asset, graph) != graph
                    or any(m["graph_sha256"] != graph or m["directory"] != v["directory"]
                           for m, v in zip(metadata, views))):
                raise ValueError(f"Unmatched trajectory or graph: {path}")
            identity = (asset, capture["target_ratio"],
                        tuple((m["eye"], m["target"]) for m in metadata))
            if identity in seen:
                raise ValueError(f"Duplicate trajectory: {path} ({metadata[0]['asset']})")
            seen.add(identity)
            trajectories.append(Trajectory(path, capture, metadata, views, visibility_frames))
    return trajectories


def features(row, capture, visibility):
    scale = 216 / capture["height"]
    projection = [np.log1p(float(row[field]) * scale) for field in PROJECTION_FIELDS]
    exchange = np.log1p(100 * int(row["exchanged_triangles"]) / int(row["triangles"]))
    score = float(row["geometric_score"]) * scale ** 3
    geometry = projection + [exchange, capture["target_ratio"],
                             np.sign(score) * np.log1p(abs(score))]
    visible = np.log1p(100 * np.asarray(visibility.get(row["stem"], [])))
    return geometry + visible.tolist()


def measured_utility(baseline, row):
    gain = psnr_gain(baseline["raw_mse"], row["raw_mse"])
    outline_loss = max(0.0, row["silhouette_xor_over_union"]
                       - baseline["silhouette_xor_over_union"])
    return np.clip(gain - SILHOUETTE_COST * outline_loss, -GAIN_LIMIT_DB, GAIN_LIMIT_DB)


def training_data(trajectories):
    active_frames = Counter(t.asset for t in trajectories for v in t.views
                            if len(v["candidates"]) > 1)
    x, y, weights = [], [], []
    for t in trajectories:
        for view in t.views:
            baseline, *candidates = view["candidates"]
            visible = t.visibility.get(view["directory"], {})
            for row in candidates:
                x.append(features(row, t.capture, visible))
                y.append(measured_utility(baseline, row))
                weights.append(1 / (active_frames[t.asset] * len(candidates)))
    if not x:
        raise ValueError("Training fold has no swap candidates")
    weights = np.asarray(weights)
    return np.asarray(x), np.asarray(y), weights / weights.sum()


def standardize(x, center, scale):
    return np.clip((x - center) / scale, -5, 5)


def train(trajectories):
    x, y, weights = training_data(trajectories)
    center = np.average(x, axis=0, weights=weights)
    scale = np.sqrt(np.average(np.square(x - center), axis=0, weights=weights))
    scale = np.where(scale > 1e-6, scale, 1)
    x = standardize(x, center, scale)
    design = np.column_stack((np.ones(len(x)), x))
    regularization = np.diag([0.0] + [RIDGE_PENALTY] * x.shape[1])
    ridge = np.linalg.solve(design.T @ (weights[:, None] * design) + regularization,
                           design.T @ (weights * y))

    torch.manual_seed(MLP_SEED)
    mlp = nn.Sequential(nn.Linear(x.shape[1], MLP_WIDTH), nn.Tanh(), nn.Linear(MLP_WIDTH, 1))
    optimizer = torch.optim.Adam(mlp.parameters(), lr=0.015, weight_decay=0.002)
    inputs, targets, w = (torch.as_tensor(a, dtype=torch.float32) for a in (x, y, weights))
    for _ in range(MLP_STEPS):
        optimizer.zero_grad(set_to_none=True)
        loss = torch.sum(w * (mlp(inputs).squeeze(1) - targets).square())
        loss.backward()
        optimizer.step()
    layers = [{"weight": layer.weight.detach().numpy().tolist(),
               "bias": layer.bias.detach().numpy().tolist()} for layer in (mlp[0], mlp[2])]
    return {"center": center.tolist(), "scale": scale.tolist(), "ridge": ridge.tolist(),
            "mlp": layers, "training_candidates": len(y)}


def scores_for_frame(rows, capture, model, visibility):
    geometric = np.array([float(row["geometric_score"] or 0) for row in rows])
    if len(rows) == 1:
        return geometric, np.zeros(1), np.zeros(1)
    x = np.asarray([features(row, capture, visibility) for row in rows[1:]])
    x = standardize(x, np.asarray(model["center"]), np.asarray(model["scale"]))
    ridge = np.asarray(model["ridge"])
    hidden, output = model["mlp"]
    h = np.tanh(x @ np.asarray(hidden["weight"]).T + hidden["bias"])
    mlp = h @ np.asarray(output["weight"])[0] + output["bias"][0]
    return geometric, np.r_[0.0, ridge[0] + x @ ridge[1:]], np.r_[0.0, mlp]


def causal_path(scores, churn, margin, switch_cost):
    path = []
    for t, frame in enumerate(scores):
        adjusted = frame.copy()
        adjusted[1:] -= margin
        if t:
            edge = churn[t - 1][path[-1]]
            # Falling back to the current baseline is always feasible. If we are already
            # off the baseline, its transition cost is measured from the actual last cut.
            adjusted -= switch_cost * edge
            adjusted[edge > edge[0]] = -np.inf
        path.append(int(np.argmax(adjusted)))
    return path


def evaluate(t, model):
    predictions = [scores_for_frame(v["candidates"], t.capture, model,
                                    t.visibility.get(v["directory"], {})) for v in t.views]
    geometric, ridge, mlp = map(list, zip(*predictions))
    # Diagnostic only: the measured utility uses reference renders. This path isolates
    # the limitations of the greedy transition rule from errors in the utility predictor.
    measured = []
    for view in t.views:
        baseline, *candidates = view["candidates"]
        measured.append(np.array([0.0] + [measured_utility(baseline, row) for row in candidates]))

    def select_paths(churn):
        return {
            "geometry_causal": causal_path(geometric, churn, 0, 0),
            "ridge_causal": causal_path(ridge, churn, ACCEPT_MARGIN_DB, CHURN_COST),
            "mlp_frame": [int(np.argmax(np.r_[f[0], f[1:] - ACCEPT_MARGIN_DB])) for f in mlp],
            "mlp_causal": causal_path(mlp, churn, ACCEPT_MARGIN_DB, CHURN_COST),
            "utility_causal_oracle": causal_path(measured, churn, ACCEPT_MARGIN_DB, CHURN_COST),
        }

    report = evaluate_trajectory(t.source.parent, t.metadata, t.views, [], select_paths)
    report.update(target_ratio=t.capture["target_ratio"],
                  start_degrees=t.capture["start_degrees"], score_path=str(t.source))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score", type=Path, nargs="+", required=True)
    parser.add_argument("--visibility", type=Path, help="Geometry-only features from lod_visibility")
    parser.add_argument("--silhouette", type=Path,
                        help="Use independent geometry silhouette labels for training and evaluation")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(1)
    visibility = None
    if args.visibility:
        data = json.loads(args.visibility.read_text(encoding="utf-8"))
        if tuple(data["features"]) != VISIBILITY_FIELDS:
            parser.error("unexpected visibility feature schema")
        visibility = data["captures"]
    silhouettes = None
    if args.silhouette:
        data = json.loads(args.silhouette.read_text(encoding="utf-8"))
        if data["metric"] != SILHOUETTE_METRIC:
            parser.error("unexpected silhouette label metric")
        silhouettes = data["captures"]
    trajectories = load_trajectories(args.score, visibility, silhouettes)
    assets = sorted({t.asset for t in trajectories})
    if len(assets) < 3:
        parser.error("whole-asset validation requires at least three assets")
    folds = []
    for held in assets:
        training = [t for t in trajectories if t.asset != held]
        test = [t for t in trajectories if t.asset == held]
        model = train(training)
        reports = [evaluate(t, model) for t in test]
        folds.append({"test_asset": test[0].metadata[0]["asset"], "test_sha256": held,
                      "train_sha256": sorted({t.asset for t in training}),
                      "model": model, "trajectories": reports})
        print(f"{folds[-1]['test_asset']}: {len(test)} held-out trajectories, "
              f"{model['training_candidates']} training swaps", flush=True)
    field_names = FEATURES + VISIBILITY_FIELDS if visibility is not None else FEATURES
    result = {"features": field_names, "seed": MLP_SEED, "mlp_width": MLP_WIDTH,
              "mlp_steps": MLP_STEPS, "ridge_penalty": RIDGE_PENALTY,
              "silhouette_cost": SILHOUETTE_COST, "gain_limit_db": GAIN_LIMIT_DB,
              "accept_margin_db": ACCEPT_MARGIN_DB, "churn_cost": CHURN_COST, "folds": folds}
    if silhouettes is not None:
        result["silhouette_metric"] = SILHOUETTE_METRIC
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
