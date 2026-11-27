"""Compute the frozen LDR-FLIP metric from captured grayscale render arrays."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path

import numpy as np


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(reference, image, flip_evaluator):
    ref = reference.astype(np.float32) / 255.
    rgb = image.astype(np.float32) / 255.
    _, flip, _ = flip_evaluator.evaluate(
        np.repeat(ref[..., None], 3, axis=-1),
        np.repeat(rgb[..., None], 3, axis=-1), "LDR",
        inputsRGB=True, applyMagma=False, parameters={"ppd": 67.})
    return float(flip)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--image-dir", required=True, type=Path)
    args = parser.parse_args()

    import flip_evaluator

    report = json.loads(args.report.read_text(encoding="utf-8"))
    image_hashes = {}
    rows = {arm: {mode: [] for mode in ("native", "msaa4")}
            for arm in report["summary"]}
    for view in report["views"]:
        stem = f"view-{view['view']:02d}-distance-{view['distance']:.1f}"
        reference_path = args.image_dir / f"{stem}-reference.npy"
        reference = np.load(reference_path, allow_pickle=False)
        image_hashes[reference_path.name] = digest(reference_path)
        for arm, modes in view["quality"].items():
            for mode in modes:
                image_path = args.image_dir / f"{stem}-{arm}-{mode}.npy"
                image = np.load(image_path, allow_pickle=False)
                image_hashes[image_path.name] = digest(image_path)
                flip = evaluate(reference, image, flip_evaluator)
                modes[mode]["flip"] = flip
                rows[arm][mode].append(flip)

    for arm, modes in rows.items():
        for mode, values in modes.items():
            report["summary"][arm][mode]["mean"]["flip"] = float(np.mean(values))
            report["summary"][arm][mode]["worst"]["flip"] = float(np.max(values))

    report["flip_status"] = "computed from lossless frame arrays in the D-drive WSL environment"
    report["flip_execution"] = {
        "package": "flip-evaluator",
        "version": importlib.metadata.version("flip-evaluator"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "inputs_rgb": True,
        "apply_magma": False,
        "parameters": {"ppd": 67.},
        "image_sha256": image_hashes,
        "script_sha256": digest(Path(__file__)),
    }
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                            encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
