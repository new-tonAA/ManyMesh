"""Train and time a small predictor for where finer geometry improves reconstruction."""

import argparse
import json
import math
from pathlib import Path
import time

import numpy as np


TILE_SIZE = 8
BUDGETS = (0.10, 0.25)
HIDDEN = 12
FEATURES = ("coverage", "silhouette", "contrast", "depthSlope", "depthStep",
            "intensity", "variance", "collapseOffset")


def tile_mean(values, side=TILE_SIZE):
    height, width = values.shape
    return values.reshape(height // side, side, width // side, side).mean(axis=(1, 3)).ravel()


def tile_features(color, depth):
    covered = np.isfinite(depth)
    z = np.where(covered, depth, 0)
    silhouette = np.zeros_like(color)
    contrast = np.zeros_like(color)
    depth_slope = np.zeros_like(color)
    depth_step = np.zeros_like(color)
    for here, adjacent in ((np.s_[1:, :], np.s_[:-1, :]), (np.s_[:, 1:], np.s_[:, :-1])):
        silhouette[here] += covered[here] != covered[adjacent]
        contrast[here] += np.abs(color[here] - color[adjacent])
        delta = np.abs(z[here] - z[adjacent]) * (covered[here] & covered[adjacent])
        depth_slope[here] += np.minimum(delta, 0.04)
        depth_step[here] += delta > 0.04
    mean = tile_mean(color)
    variance = np.maximum(0, tile_mean(color * color) - mean * mean)
    measures = (covered, silhouette, contrast, depth_slope, depth_step)
    return np.column_stack([*(tile_mean(x) for x in measures), mean, variance]).astype(np.float32)


def witness_tiles(witnesses, basis, depth):
    height, width = depth.shape
    position = witnesses[:, :3] @ basis
    offset = witnesses[:, 3]
    x = np.floor((position[:, 0] * 0.45 + 0.5) * width).astype(np.int32)
    y = np.floor((position[:, 1] * 0.45 + 0.5) * height).astype(np.int32)
    x = np.clip(x, 0, width - 1)
    y = np.clip(y, 0, height - 1)
    visible = position[:, 2] <= depth[y, x] + 0.04 + offset
    tiles = np.zeros((height // TILE_SIZE, width // TILE_SIZE), dtype=np.float32)
    np.maximum.at(tiles, (y[visible] // TILE_SIZE, x[visible] // TILE_SIZE), offset[visible])
    return tiles.ravel()


def forward(features, weights):
    input_weights, bias, output_weights, intercept = weights
    return np.maximum(features @ input_weights + bias, 0) @ output_weights + intercept


def fit(features, gains):
    mean = features.mean(axis=0)
    scale = np.maximum(features.std(axis=0), 1e-5)
    x = (features - mean) / scale
    magnitude = max(gains.std(), 1e-8)
    y = gains / magnitude
    ridge = np.linalg.solve(x.T @ x + len(x) * 0.02 * np.eye(x.shape[1]), x.T @ (y - y.mean()))

    rng = np.random.default_rng(2027)
    weights = [rng.normal(0, 0.2, (x.shape[1], HIDDEN)).astype(np.float32),
               np.zeros(HIDDEN, dtype=np.float32),
               rng.normal(0, 0.2, HIDDEN).astype(np.float32), np.zeros(1, dtype=np.float32)]
    first = [np.zeros_like(w) for w in weights]
    second = [np.zeros_like(w) for w in weights]
    for step in range(1, 601):
        choice = rng.integers(len(x), size=512)
        batch = x[choice]
        w0, b0, w1, b1 = weights
        hidden = np.maximum(batch @ w0 + b0, 0)
        error = (hidden @ w1 + b1 - y[choice]) / len(choice)
        slope = (error[:, None] * w1) * (hidden > 0)
        grads = (batch.T @ slope, slope.sum(axis=0), hidden.T @ error,
                 np.array([error.sum()]))
        for i, gradient in enumerate(grads):
            first[i] = 0.9 * first[i] + 0.1 * gradient
            second[i] = 0.999 * second[i] + 0.001 * gradient ** 2
            corrected_mean = first[i] / (1 - 0.9 ** step)
            corrected_square = second[i] / (1 - 0.999 ** step)
            weights[i] -= 0.003 * corrected_mean / (np.sqrt(corrected_square) + 1e-8)

    w0, b0, w1, b1 = weights
    w0 = w0 / scale[:, None]
    return mean, scale, ridge, (w0, b0 - mean @ w0, w1 * magnitude, b1 * magnitude)


def selected_gains(gains, scores, budget):
    keep = max(1, math.floor(scores.shape[-1] * budget))
    chosen = np.argsort(-scores, axis=-1, kind="stable")[..., :keep]
    return np.take_along_axis(gains, chosen, axis=-1).sum(axis=-1) / scores.shape[-1]


def evaluate(assets, out):
    scores_by_asset = {}
    held_weights = {}
    for held, data in assets.items():
        train = [candidate for name, candidate in assets.items() if name != held]
        training_pixels = np.concatenate([d["features"] for d in train], axis=0)
        training_gains = np.concatenate([d["coarse"] - d["fine"] for d in train], axis=0)
        features = data["features"]
        gains = data["coarse"] - data["fine"]
        scores = {name: features[..., FEATURES.index(name)]
                  for name in ("silhouette", "contrast", "depthStep", "collapseOffset")}
        for size, suffix in ((len(FEATURES) - 1, ""), (len(FEATURES), "WithWitness")):
            inputs = training_pixels[..., :size].reshape(-1, size)
            mean, scale, ridge, weights = fit(inputs, training_gains.ravel())
            frame_features = features[..., :size]
            scores[f"ridge{suffix}"] = ((frame_features - mean) / scale) @ ridge
            scores[f"mlp{suffix}"] = forward(frame_features, weights)
            np.savez(out / f"weights{suffix}_without_{held}.npz", *weights)
        held_weights[held] = weights
        scores["oracle"] = gains
        base = float(data["coarse"].mean())
        rows = {}
        for budget in BUDGETS:
            rows[str(budget)] = {
                name: float(selected_gains(gains, rank, budget).mean())
                for name, rank in scores.items()
            }
            chosen_heuristic = max(("silhouette", "contrast", "depthStep", "collapseOffset"),
                key=lambda name:
                selected_gains(training_gains, training_pixels[..., FEATURES.index(name)],
                               budget).mean())
            rows[str(budget)]["trainChosenHeuristic"] = chosen_heuristic
        result = {"baseMse": base, "errorReduction": rows,
                  "triangles": data["triangles"].tolist(), "views": len(features)}
        scores_by_asset[held] = result
        print(held, {b: {k: round(v / base * 100, 1) for k, v in scores.items()
                         if k != "trainChosenHeuristic"} for b, scores in rows.items()},
              flush=True)
    return scores_by_asset, held_weights


def timing(color, depth, witnesses, basis, weights, extract):
    rows = []
    for width, height in ((96, 96), (320, 184), (960, 544)):
        y = np.arange(height) * color.shape[0] // height
        x = np.arange(width) * color.shape[1] // width
        image = color[y[:, None], x]
        geometry = depth[y[:, None], x]
        elapsed = []
        network = []
        for trial in range(32):
            start = time.perf_counter()
            features = np.column_stack((extract(image, geometry),
                                        witness_tiles(witnesses, basis, geometry)))
            predicted_at = time.perf_counter()
            prediction = forward(features, weights)
            ranked_at = time.perf_counter()
            np.argsort(-prediction, kind="stable")[:math.floor(len(prediction) * 0.10)]
            finish = time.perf_counter()
            if trial >= 2:
                elapsed.append(1000 * (finish - start))
                network.append(1000 * (ranked_at - predicted_at))
        rows.append({"width": width, "height": height, "tiles": len(prediction),
                     "featureInferenceRankingMs": elapsed, "inferenceMs": network})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fused-features", action="store_true", help="time Numba tile extraction")
    args = parser.parse_args()
    manifest = json.loads((args.data / "dataset.json").read_text(encoding="utf-8"))
    assets = {}
    for source in manifest["sources"]:
        name = source["name"]
        with np.load(args.data / f"{name}.npz") as file:
            assets[name] = dict(file)
    if len(assets) < 3:
        parser.error("at least three independent assets are required")
    args.out.mkdir(parents=True, exist_ok=True)
    quality, weights = evaluate(assets, args.out)
    extract = tile_features
    if args.fused_features:
        from fused_tile_features import fused_tile_features
        extract = fused_tile_features
        for name, sample in assets.items():
            expected = sample["features"][0, :, :-1]
            actual = extract(sample["color"], sample["depth"])
            if not np.allclose(actual, expected, atol=1e-6, rtol=0):
                raise ValueError(f"Fused extraction changed tile features for {name}")
    example = next(iter(assets))
    data = assets[example]
    rows = timing(data["color"], data["depth"], data["witnesses"], data["basis"],
                  weights[example], extract)
    result = {"architecture": [len(FEATURES), HIDDEN, 1], "features": FEATURES,
              "budgets": BUDGETS, "tiles": TILE_SIZE, "quality": quality,
              "timingAsset": example, "featureImplementation": extract.__name__, "timing": rows}
    (args.out / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
