"""Export filtered grayscale render pairs for asset-held-out CNN super-resolution."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pairs", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    dataset = json.loads((args.pairs / "dataset.json").read_text(encoding="utf-8"))
    records = {split: [] for split in ("train", "validation", "test")}
    for source in dataset["sources"]:
        split = source.get("split")
        if split not in records:
            raise ValueError(f"Source {source['name']} has no valid split")
        name = source["name"]
        with np.load(args.pairs / f"{name}.npz", allow_pickle=False) as archive:
            if "lowImages" not in archive or "highImages" not in archive:
                raise ValueError(f"Missing RGB reconstruction pairs for {name}; regenerate pairs")
            low, high = archive["lowImages"], archive["highImages"]
        if low.ndim != 3 or high.ndim != 3 or low.shape[0] != high.shape[0]:
            raise ValueError(f"Unexpected image arrays for {name}: {low.shape}, {high.shape}")
        if high.shape[1] != 2 * low.shape[1] or high.shape[2] != 2 * low.shape[2]:
            raise ValueError(f"Expected a 2x scale pair for {name}")
        folder = args.out / split
        folder.mkdir(parents=True, exist_ok=True)
        for view in range(low.shape[0]):
            index = len(records[split])
            low_name, high_name = f"lr_v{index:04}.png", f"hr_v{index:04}.png"
            Image.fromarray(low[view], mode="L").save(folder / low_name)
            Image.fromarray(high[view], mode="L").save(folder / high_name)
            records[split].append({"asset": name, "view": view,
                                   "low": low_name, "high": high_name})
    manifest = {"dataset": dataset, "scale": 2, "channel": "grayscale directional shading",
                "samples": records}
    (args.out / "dataset.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(" ".join(f"{split}={len(rows)}" for split, rows in records.items()))


if __name__ == "__main__":
    main()
