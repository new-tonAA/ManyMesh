"""Measure bytes and decoded render quality for geometry codec baselines."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import tempfile

import numpy as np

from cluster_decoder import Mesh, topology
from cluster_decoder_pilot import read_stl
from cluster_decoder_quality import render
from compare_qem_meshopt_validation_70pct import image_metrics, meshopt_simplify_raw
from make_refinement_pairs import view_basis


ROOT = Path(__file__).resolve().parents[2]
HELPER = Path(__file__).with_name("geometry_codec_baseline.cjs")
DRACO = ROOT / "third_party/draco/javascript/npm/draco3d"
MESHOPT = ROOT / "third_party/meshoptimizer/js"
BITS = (8, 11, 14, 20)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_codecs(positions, triangles, directory):
    with tempfile.TemporaryDirectory(prefix="codec-", dir=directory) as temporary:
        source = Path(temporary) / "input.json"
        target = Path(temporary) / "output.json"
        source.write_text(json.dumps({"positions": positions.tolist(),
                                     "triangles": triangles.tolist(), "bits": BITS}),
                          encoding="utf-8")
        subprocess.run(["node", str(HELPER), str(source), str(target)], cwd=ROOT,
                       check=True, timeout=180)
        return json.loads(target.read_text(encoding="utf-8"))


def oriented_lattice_faces(lattice, triangles):
    points = lattice[triangles]
    rotations = [np.roll(points, -shift, axis=1).reshape(-1, 9) for shift in range(3)]
    return sorted(min(tuple(a), tuple(b), tuple(c)) for a, b, c in zip(*rotations))


def checked_mesh(positions, triangles):
    mesh = Mesh(positions, triangles, np.zeros(len(triangles), dtype=np.int64)).checked()
    return mesh, topology(mesh)[1]


def score_codec(row, geometry, captured, bases, size, origin, extent):
    if "error" in row:
        return row
    positions = np.asarray(row.pop("positions"), dtype=np.float64).reshape(-1, 3)
    triangles = np.asarray(row.pop("indices"), dtype=np.int64).reshape(-1, 3)
    row.update(decoded_vertices=len(positions), decoded_faces=len(triangles),
               median_decode_ms=float(np.median(row["decodeMs"])))
    if (not len(positions) or not len(triangles) or not np.isfinite(positions).all()
            or triangles.min() < 0 or triangles.max() >= len(positions)):
        row["topology_error"] = "Invalid decoded buffers"
        return row
    levels = (1 << row["bits"]) - 1
    origin_f32 = origin.astype(np.float32)
    inv_step = np.float32(levels) / np.float32(extent)
    expected_grid = np.floor((geometry[0].astype(np.float32) - origin_f32) * inv_step + .5)
    step = np.float32(extent) / np.float32(levels)
    grid = (positions - origin) / float(step)
    nearest = np.rint(grid).astype(np.float32)
    if np.array_equal(positions.astype(np.float32), nearest * step + origin_f32):
        expected = oriented_lattice_faces(expected_grid.astype(np.int32), geometry[1])
        actual = oriented_lattice_faces(nearest.astype(np.int32), triangles)
        row["oriented_grid_faces_match"] = actual == expected
    else:
        row["oriented_grid_faces_match"] = False
        row["grid_error"] = "Decoded coordinates do not equal the reconstructed float32 grid"
    try:
        # The lattice check detects exact collinearity hidden by float32 rounding.
        for coordinates in (nearest, positions):
            Mesh(coordinates, triangles, np.zeros(len(triangles), dtype=np.int64)).checked()
    except ValueError as error:
        row["topology_error"] = str(error)

    metrics = []
    for basis, (reference, reference_coverage) in zip(bases, captured):
        image, coverage = render(positions, triangles, basis, size, 2)
        metrics.append(image_metrics(reference, image, reference_coverage, coverage, 67.))
    row["per_view"] = metrics
    row["mean"] = {key: float(np.mean([view[key] for view in metrics]))
                   for key in ("mse", "ssim", "flip", "coverage_mae", "silhouette_xor_fraction")}
    mse = row["mean"]["mse"]
    row["mean"]["psnr_db"] = -10 * float(np.log10(mse)) if mse > 0 else None
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--asset", type=int, help="Optional single validation asset for a smoke run")
    parser.add_argument("--size", type=int, default=192)
    parser.add_argument("--views", type=int, default=8)
    args = parser.parse_args()
    if args.size < 32 or args.views < 2:
        parser.error("Use at least two views at a resolution of at least 32 pixels")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assets = [asset for asset in manifest["files"] if asset["split"] == "validation"
              and (args.asset is None or args.asset == asset["file_id"])]
    if not assets:
        parser.error("No matching validation assets in the manifest")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "scope": "Thingi10K validation geometry codec baseline",
        "manifest_sha256": sha256(args.manifest),
        "runtime": {
            "platform": platform.platform(), "cpu": platform.processor(),
            "node": subprocess.check_output(["node", "--version"], text=True).strip(),
            "python": platform.python_version(), "numpy": np.__version__,
            "flip_evaluator": importlib.metadata.version("flip-evaluator"),
            "scikit_image": importlib.metadata.version("scikit-image"),
        },
        "versions": {name: json.loads((path / "package.json").read_text())["version"]
                     for name, path in (("draco", DRACO), ("meshopt", MESHOPT))},
        "protocol": {"bits": BITS, "views": args.views, "size": args.size, "samples_per_pixel": 4,
                     "thinned_target": 0.70, "draco_speed": [5, 5], "flip_ppd": 67,
                     "decode_repetitions": 11, "meshopt_header_bytes": 32},
        "hashes": {path.relative_to(ROOT).as_posix(): sha256(path) for path in
                   (Path(__file__).resolve(), HELPER,
                    Path(__file__).with_name("meshopt_simplify.cjs"),
                    Path(__file__).with_name("cluster_decoder_quality.py"),
                    Path(__file__).with_name("compare_qem_meshopt_validation_70pct.py"),
                    DRACO / "draco_encoder.wasm", DRACO / "draco_decoder.wasm",
                    MESHOPT / "meshopt_encoder.js", MESHOPT / "meshopt_decoder.js",
                    MESHOPT / "meshopt_simplifier.js")},
        "assets": [],
    }
    bases = [view_basis(view, args.views) for view in range(args.views)]
    for asset in assets:
        path = args.manifest.parent / asset["path"]
        if sha256(path) != asset["sha256"]:
            raise ValueError(f"Source hash mismatch for {asset['file_id']}")
        positions, triangles = read_stl(path)
        if len(triangles) != asset["faces"]:
            raise ValueError(f"Unexpected source face count for {asset['file_id']}")
        origin = (positions.min(axis=0) + positions.max(axis=0)) * .5
        scale = np.linalg.norm(positions - origin, axis=1).max()
        if not np.isfinite(scale) or scale <= 0:
            raise ValueError(f"Invalid normalization scale for {asset['file_id']}")
        positions = ((positions - origin) / scale).astype(np.float32).astype(np.float64)
        _, source_boundary = checked_mesh(positions, triangles)
        captured = [render(positions, triangles, basis, args.size, 2) for basis in bases]
        entry = {"asset": asset["file_id"], "source_sha256": asset["sha256"],
                 "source_faces": len(triangles), "rows": []}
        reduced = meshopt_simplify_raw(positions, triangles, int(.70 * len(triangles)),
                                       args.out.parent)[:2]
        for label, geometry in (("full", (positions, triangles)), ("meshopt70", reduced)):
            try:
                _, boundary = checked_mesh(*geometry)
                if boundary != source_boundary:
                    raise ValueError("Simplification changed the directed boundary")
                failure = None
            except ValueError as error:
                failure = str(error)
            receipt = run_codecs(*geometry, args.out.parent)
            for result in receipt["results"]:
                result.update(input=label, input_faces=len(geometry[1]), input_topology_error=failure)
                entry["rows"].append(score_codec(result, geometry, captured, bases, args.size,
                                                 np.asarray(receipt["origin"]), receipt["range"]))
        report["assets"].append(entry)
        print(f"{asset['file_id']}: {len(entry['rows'])} configurations", flush=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
