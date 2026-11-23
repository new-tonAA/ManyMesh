"""Compare fixed and searched quantization grid origins in actual Draco streams."""

import argparse
from itertools import product
import json
import platform
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import time

import numpy as np

from bench_geometry_codecs import ROOT, checked_mesh, oriented_lattice_faces, sha256
from cluster_decoder_pilot import read_stl
from cluster_decoder_quality import render
from compare_qem_meshopt_validation_70pct import image_metrics
from make_refinement_pairs import view_basis


BITS = (10, 12, 14, 16, 18, 20)
COORDINATE_SCALE = 1 << 20
PHASES = list(product(range(4), repeat=3))
ENCODER = Path(__file__).with_name("encode_quantization_phases.cjs")


def normals(vertices, faces):
    points = vertices[faces].astype(np.float64)
    return np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])


def prepare_grid(positions, bits):
    levels = (1 << bits) - 1
    lower = np.floor(positions.min(axis=0) * 8) / 8
    extent = float(np.max(positions.max(axis=0).astype(np.float64) - lower))
    # Reserve one grid cell for the shifted origin and use binary-exact eighths.
    step = np.ceil(2 * extent / (levels - 1)) / 2
    return lower, np.float32(levels * step), step


def snap(positions, origin, extent, bits):
    levels = np.float32((1 << bits) - 1)
    lattice = np.floor((positions - origin) * (levels / extent) + np.float32(.5))
    return lattice * (extent / levels) + origin


def check_geometry(candidate, triangles, source_normals):
    # A positive dot product excludes collapses and reversals of local normals.
    face_dot = np.einsum("ij,ij->i", normals(candidate, triangles), source_normals)
    if np.any(face_dot <= 0):
        return False
    return len(np.unique(candidate, axis=0)) == len(candidate)


def search(positions, triangles, source_normals, bits):
    lower, extent, step = prepare_grid(positions, bits)
    start = time.perf_counter()
    fixed = snap(positions, lower, extent, bits)
    passes = check_geometry(fixed, triangles, source_normals)
    fixed_time = time.perf_counter() - start
    preferred = None
    valid_phases = 0
    for phase in PHASES:
        origin = (lower - (np.asarray(phase) * step / 4)).astype(np.float32)
        quantized = fixed if phase == (0, 0, 0) else snap(positions, origin, extent, bits)
        legal = passes if phase == (0, 0, 0) else check_geometry(
            quantized, triangles, source_normals)
        if not legal:
            continue
        valid_phases += 1
        squared_error = float(np.mean((quantized.astype(np.float64) - positions) ** 2))
        if preferred is None or squared_error < preferred["position_mse_scaled"]:
            preferred = {"phase": phase, "origin": origin.tolist(),
                         "range": float(extent), "bits": bits,
                         "position_mse_scaled": squared_error}
    fixed_config = None
    if passes:
        fixed_config = {"phase": (0, 0, 0), "origin": lower.tolist(), "range": float(extent),
                        "bits": bits,
                        "position_mse_scaled": float(np.mean(
                            (fixed.astype(np.float64) - positions) ** 2))}
    return {"bits": bits, "valid_phases": valid_phases,
            "fixed": fixed_config, "searched": preferred,
            "fixed_ms": 1000 * fixed_time, "search_ms": 1000 * (time.perf_counter() - start)}


def encode(configurations, positions, triangles, directory):
    if not configurations:
        return []
    with TemporaryDirectory(prefix="phase-codec-", dir=directory) as temporary:
        job = Path(temporary) / "input.json"
        output = Path(temporary) / "output.json"
        job.write_text(json.dumps({
            "positions": positions.tolist(), "triangles": triangles.tolist(),
            "configurations": configurations,
        }), encoding="utf-8")
        subprocess.run(["node", str(ENCODER), str(job), str(output)], check=True, timeout=240)
        return json.loads(output.read_text(encoding="utf-8"))


def position_bits(vertices):
    positions = np.asarray(vertices, dtype=np.float32).copy(order="C")
    positions[positions == 0] = 0
    return positions.view(np.int32)


def score(payload, configuration, positions, triangles, source_normals, views, size):
    output_positions = np.asarray(payload.pop("positions"), dtype=np.float32).reshape(-1, 3)
    output_triangles = np.asarray(payload.pop("indices"), dtype=np.int64).reshape(-1, 3)
    origin = np.asarray(configuration["origin"], dtype=np.float32)
    expected = snap(positions, origin, np.float32(configuration["range"]), configuration["bits"])
    if (len(output_positions) != len(positions)
            or oriented_lattice_faces(position_bits(output_positions), output_triangles)
            != oriented_lattice_faces(position_bits(expected), triangles)):
        raise ValueError("Decoded oriented triangles differ from the checked rounding result")
    if not check_geometry(expected, triangles, source_normals):
        raise ValueError("Decoded geometry does not meet the certified local constraints")
    payload["median_decode_ms"] = float(np.median(payload["decodeMs"]))
    if views:
        rows = []
        for basis, reference, coverage in views:
            image, output_coverage = render(output_positions / COORDINATE_SCALE, output_triangles,
                                            basis, size, 2)
            rows.append(image_metrics(reference, image, coverage, output_coverage, 67.))
        payload["per_view"] = rows
        payload["mean"] = {key: float(np.mean([view[key] for view in rows]))
                           for key in ("mse", "ssim", "flip", "coverage_mae",
                                       "silhouette_xor_fraction")}
        mse = payload["mean"]["mse"]
        payload["mean"]["psnr_db"] = -10 * float(np.log10(mse)) if mse > 0 else None
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--split", choices=("train", "validation"), required=True)
    parser.add_argument("--asset", type=int)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--views", type=int, default=8)
    parser.add_argument("--size", type=int, default=192)
    args = parser.parse_args()
    if args.views < 2 or args.size < 32:
        parser.error("Use two or more views at a resolution of at least 32 pixels")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    assets = [a for a in manifest["files"] if a["split"] == args.split
              and (args.asset is None or args.asset == a["file_id"])]
    if not assets:
        parser.error("No matching assets")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "split": args.split, "preflight": args.preflight_only,
        "manifest_sha256": sha256(args.manifest), "bits": BITS, "phases": PHASES,
        "views": args.views, "size": args.size, "coordinate_scale": COORDINATE_SCALE,
        "cpu": platform.processor(),
        "hashes": {path.relative_to(ROOT).as_posix(): sha256(path) for path in (
            Path(__file__), ENCODER, ENCODER.with_name("geometry_codec_baseline.cjs"),
            ENCODER.with_name("bench_geometry_codecs.py"),
            ENCODER.with_name("cluster_decoder_quality.py"),
            ROOT / "third_party/draco/javascript/npm/draco3d/draco_encoder.wasm",
            ROOT / "third_party/draco/javascript/npm/draco3d/draco_decoder.wasm",
        )},
        "assets": [],
    }
    for asset in assets:
        source = args.manifest.parent / asset["path"]
        if sha256(source) != asset["sha256"]:
            raise ValueError(f"Source hash mismatch for asset {asset['file_id']}")
        positions, triangles = read_stl(source)
        center = (positions.min(axis=0) + positions.max(axis=0)) * .5
        scale = np.linalg.norm(positions - center, axis=1).max()
        positions = ((positions - center) / scale).astype(np.float32)
        checked_mesh(positions, triangles)
        scaled = positions * COORDINATE_SCALE
        source_normals = normals(scaled, triangles)
        rows = [search(scaled, triangles, source_normals, bits) for bits in BITS]
        if not args.preflight_only:
            bases = [view_basis(i, args.views) for i in range(args.views)]
            views = [(basis, *render(positions, triangles, basis, args.size, 2)) for basis in bases]
            configs = [config for row in rows for config in (row["fixed"], row["searched"])
                       if config is not None]
            unique = {(config["bits"], tuple(config["origin"])): config for config in configs}
            encoded = encode(list(unique.values()), scaled, triangles, args.out.parent)
            for config, payload in zip(unique.values(), encoded, strict=True):
                config.update(score(payload, config, scaled, triangles, source_normals,
                                    views, args.size))
            for row in rows:
                for kind in ("fixed", "searched"):
                    if row[kind] is not None:
                        config = row[kind]
                        row[kind] = unique[(config["bits"], tuple(config["origin"]))]
        report["assets"].append({"asset": asset["file_id"], "sha256": asset["sha256"],
                                 "vertices": len(positions), "faces": len(triangles),
                                 "quantization": rows})
        thresholds = {kind: next((row["bits"] for row in rows if row[kind]), None)
                      for kind in ("fixed", "searched")}
        print(asset["file_id"], thresholds, flush=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
