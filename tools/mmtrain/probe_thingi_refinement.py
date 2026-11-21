"""Train tiny tile rankers on Thingi10K train assets and select on held-out validation Things."""

import argparse
import json
from pathlib import Path
import time

import numpy as np

from tile_refinement import FEATURES, fit, forward


RANKERS = ("silhouette", "contrast", "depthStep", "collapseOffset",
           "ridge", "ridgeWithWitness", "mlp", "mlpWithWitness")
BUDGETS = (0.10, 0.25)


def load_assets(data: Path):
    manifest = json.loads((data / "dataset.json").read_text(encoding="utf-8"))
    assets = {}
    for source in manifest["sources"]:
        name = source["name"]
        with np.load(data / f"{name}.npz", allow_pickle=False) as capture:
            row = {key: capture[key] for key in capture.files}
        row["source"] = source
        if row["features"].ndim != 3 or row["features"].shape[-1] != len(FEATURES):
            raise ValueError(f"Unexpected feature shape for {name}: {row['features'].shape}")
        if row["coarse"].shape != row["fine"].shape or row["coarse"].shape != row["features"].shape[:2]:
            raise ValueError(f"Mismatched target arrays for {name}")
        if not np.isfinite(row["features"]).all() or not np.isfinite(row["coarse"]).all():
            raise ValueError(f"Non-finite training data for {name}")
        assets[name] = row
    if len(assets) != len(manifest["sources"]):
        raise ValueError("Duplicate asset names in dataset manifest")
    splits = {name: [key for key, row in assets.items() if row["source"].get("split") == name]
              for name in ("train", "validation", "test")}
    if any(len(splits[name]) == 0 for name in splits):
        raise ValueError(f"All three splits must be nonempty: { {k: len(v) for k, v in splits.items()} }")
    return manifest, assets, splits


def train_rankers(assets, train_names):
    x = np.concatenate([assets[name]["features"].reshape(-1, len(FEATURES))
                        for name in train_names], axis=0)
    gain = np.concatenate([(assets[name]["coarse"] - assets[name]["fine"]).reshape(-1)
                           for name in train_names], axis=0)
    models = {}
    for feature_count, suffix in ((len(FEATURES) - 1, ""), (len(FEATURES), "WithWitness")):
        mean, scale, ridge, weights = fit(x[:, :feature_count], gain)
        models[f"ridge{suffix}"] = (mean, scale, ridge)
        models[f"mlp{suffix}"] = weights
    return models


def predict(data, models):
    feature = data["features"]
    score = {
        "silhouette": feature[..., FEATURES.index("silhouette")],
        "contrast": feature[..., FEATURES.index("contrast")],
        "depthStep": feature[..., FEATURES.index("depthStep")],
        "collapseOffset": feature[..., FEATURES.index("collapseOffset")],
    }
    flat = feature.reshape(-1, feature.shape[-1])
    for name in ("ridge", "ridgeWithWitness"):
        mean, scale, coefficient = models[name]
        count = len(FEATURES) if name.endswith("WithWitness") else len(FEATURES) - 1
        score[name] = (((flat[:, :count] - mean) / scale) @ coefficient).reshape(feature.shape[:2])
    for name in ("mlp", "mlpWithWitness"):
        count = len(FEATURES) if name.endswith("WithWitness") else len(FEATURES) - 1
        score[name] = forward(flat[:, :count], models[name]).reshape(feature.shape[:2])
    gain = data["coarse"] - data["fine"]
    score["oracle"] = gain
    return score


def selected_gain(gain, priority, budget):
    count = max(1, int(np.floor(priority.shape[-1] * budget)))
    order = np.argsort(-priority, axis=-1, kind="stable")[..., :count]
    selected = np.take_along_axis(gain, order, axis=-1)
    return selected.sum(axis=-1).sum() / gain.size


def evaluate(assets, names, models):
    rows = {}
    for name in names:
        data = assets[name]
        priority = predict(data, models)
        gain = data["coarse"] - data["fine"]
        base = float(data["coarse"].mean())
        rows[name] = {"baseMse": base, "triangles": data["triangles"].tolist(),
                      "views": int(data["features"].shape[0]), "budgets": {}}
        for budget in BUDGETS:
            rows[name]["budgets"][str(budget)] = {
                method: float(100 * selected_gain(gain, priority[method], budget) / base)
                for method in (*RANKERS, "oracle")
            }
    return rows


def aggregate(rows, names):
    return {str(budget): {
        method: float(np.mean([rows[name]["budgets"][str(budget)][method] for name in names]))
        for method in (*RANKERS, "oracle")
    } for budget in BUDGETS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest, assets, splits = load_assets(args.data)
    start = time.perf_counter()
    models = train_rankers(assets, splits["train"])
    train_seconds = time.perf_counter() - start
    validation = evaluate(assets, splits["validation"], models)
    test = evaluate(assets, splits["test"], models)
    validation_mean = aggregate(validation, splits["validation"])
    test_mean = aggregate(test, splits["test"])

    selected = {}
    for budget in BUDGETS:
        key = str(budget)
        winner = max(RANKERS, key=lambda method: validation_mean[key][method])
        selected[key] = {"ranker": winner,
                         "validationGainPercent": validation_mean[key][winner],
                         "testGainPercent": test_mean[key][winner]}

    args.out.mkdir(parents=True, exist_ok=True)
    for name, weights in models.items():
        if name.startswith("mlp"):
            np.savez(args.out / f"{name}.npz", *weights)
    result = {
        "source": manifest,
        "features": FEATURES,
        "rankers": RANKERS,
        "budgets": BUDGETS,
        "trainingAssets": splits["train"],
        "validationAssets": splits["validation"],
        "testAssets": splits["test"],
        "trainingSeconds": train_seconds,
        "selectionByValidation": selected,
        "validationMeanGainPercent": validation_mean,
        "heldOutTestMeanGainPercent": test_mean,
        "validationPerAsset": validation,
        "testPerAsset": test,
        "metric": "per-asset percent reduction in filtered tile MSE by rendering finer LOD in the top-budget tiles",
        "limitations": [
            "orthographic views and grayscale directional lighting",
            "two QEM LODs per input; tile replacement is a proxy for a legal runtime mixed cut",
            "clean licensed Thingi10K subset; not representative of wild non-manifold meshes",
            "no end-to-end GPU frame time or full renderer evaluation in this probe",
        ],
    }
    (args.out / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"train": len(splits["train"]), "validation": len(splits["validation"]),
                      "test": len(splits["test"]), "trainingSeconds": train_seconds,
                      "selected": selected, "validation": validation_mean, "test": test_mean},
                     indent=2))


if __name__ == "__main__":
    main()
