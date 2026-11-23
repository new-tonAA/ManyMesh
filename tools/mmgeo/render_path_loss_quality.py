#!/usr/bin/env python3
"""Render existing path-loss and QEM mesh captures for a matched image-quality screen."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from collections import Counter

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_dynamic_path_simplification import replay_geometry


ASSETS = {
    "Pirate": ("filter", "pirate.json", "global-qem4-20pct-pirate.json"),
    "RoundedCube": ("reports", "rounded_cube.json", "global-qem4-20pct-rounded.json"),
    "Sphere": ("reports", "material_sphere.json", "global-qem4-20pct-sphere.json"),
    "Torus": ("filter", "torus.json", "global-qem4-20pct-torus.json"),
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_obj(path, positions, triangles):
    with path.open("w", encoding="ascii", newline="\n") as stream:
        for vertex in positions:
            stream.write("v %.9g %.9g %.9g\n" % tuple(vertex))
        stream.write("s off\n")
        for face in triangles:
            stream.write("f %d %d %d\n" % tuple(int(v) + 1 for v in face))


def topology_summary(positions, triangles, source_boundary=None):
    faces = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    canonical = [tuple(sorted(map(int, face))) for face in faces]
    duplicate_faces = len(canonical) - len(set(canonical))
    points = np.asarray(positions, dtype=np.float64)[faces]
    area2 = np.linalg.norm(np.cross(points[:, 1] - points[:, 0],
                                    points[:, 2] - points[:, 0]), axis=1)
    incidence = Counter()
    directed = Counter()
    for face in faces:
        for i in range(3):
            a, b = int(face[i]), int(face[(i + 1) % 3])
            incidence[tuple(sorted((a, b)))] += 1
            directed[(a, b)] += 1
    boundaries = {edge for edge, count in incidence.items() if count == 1}
    two_sided = [edge for edge, count in incidence.items() if count == 2]
    inconsistent = sum(directed[edge] != 1 or directed[(edge[1], edge[0])] != 1
                       for edge in two_sided)
    summary = {"duplicate_faces": duplicate_faces,
               "degenerate_faces_area2_le_1e-12": int(np.count_nonzero(area2 <= 1e-12)),
               "nonmanifold_edges": sum(count > 2 for count in incidence.values()),
               "inconsistent_winding_edges": int(inconsistent),
               "boundary_edges": len(boundaries)}
    if source_boundary is not None:
        summary["boundary_edge_symmetric_difference_from_source"] = len(
            boundaries.symmetric_difference(source_boundary))
    return summary, boundaries


def render_set(args, name, capture_path, report_path, out, previous_record=None,
               reusable_configuration=False):
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report["captureSha256"] != sha256(capture_path):
        raise ValueError(f"capture hash mismatch for {name}")
    unit_index = report["unitIndex"]
    unit = capture["units"][unit_index]
    source_positions = np.asarray(unit["positions"], dtype=np.float64)
    center = (source_positions.min(axis=0) + source_positions.max(axis=0)) * 0.5
    radius = max(float(np.linalg.norm(source_positions - center, axis=1).max()), 1e-8)
    eye = center + np.array([0.0, 0.0, 3.0 * radius])
    records = {"asset": name, "unit_index": unit_index, "source_faces": len(unit["triangles"]),
               "face_budget": report["path"]["finalFaces"], "center": center.tolist(),
               "radius": radius, "capture_sha256": sha256(capture_path),
               "optimization_report_sha256": sha256(report_path), "renders": {}}
    source_topology, source_boundary = topology_summary(
        source_positions, unit["triangles"])
    records["source_topology"] = source_topology
    if report["qem"]["finalFaces"] != records["face_budget"]:
        raise ValueError(f"face counts are not matched for {name}")
    if previous_record is not None and (
            previous_record.get("capture_sha256") != records["capture_sha256"] or
            previous_record.get("optimization_report_sha256") !=
            records["optimization_report_sha256"]):
        previous_record = None

    for mode in ("source", "path", "qem"):
        steps = [] if mode == "source" else report[mode]["steps"]
        positions, triangles = replay_geometry(unit, steps)
        if mode != "source" and len(triangles) != records["face_budget"]:
            raise ValueError(f"unexpected final face count for {name}/{mode}")
        mesh = out / f"{name}-{mode}.obj"
        write_obj(mesh, positions, triangles)
        mesh_sha = sha256(mesh)
        topology, _ = topology_summary(positions, triangles, source_boundary)
        prefix = out / f"{name}-{mode}.png"
        command = [str(args.mm_bench), "--headless", "--api", "opengl", "--no-shadows",
                   "--window-size", f"{args.size}x{args.size}", "--fixed-timestep", "0.0166667",
                   "--out", str(prefix), "--eye", ",".join(f"{x:.9g}" for x in eye),
                   "--target", ",".join(f"{x:.9g}" for x in center), "--views", str(args.views),
                   "--warmup", str(args.warmup), "--measure", str(args.measure), str(mesh)]
        images = [prefix.with_name(f"{prefix.stem}_v{i:02d}{prefix.suffix}")
                  for i in range(args.views)]
        old_mode = (previous_record or {}).get("renders", {}).get(mode, {})
        old_images = old_mode.get("images", [])
        reusable = (reusable_configuration and old_mode.get("mesh_sha256") == mesh_sha and
                    len(old_images) == len(images) and all(
                        image.is_file() and entry.get("path") == image.name and
                        entry.get("sha256") == sha256(image) and
                        entry.get("size") == [args.size, args.size]
                        for image, entry in zip(images, old_images, strict=True)))
        log_path = out / f"{name}-{mode}.log"
        if reusable:
            reusable = (log_path.is_file() and old_mode.get("log_sha256") == sha256(log_path))
        if not reusable:
            completed = subprocess.run(command, cwd=args.repo, text=True, capture_output=True)
            log_path.write_text(
                completed.stdout + "\n--- stderr ---\n" + completed.stderr, encoding="utf-8")
            if completed.returncode:
                raise RuntimeError(f"mm_bench failed for {name}/{mode}: {completed.returncode}")
            if not all(image.is_file() for image in images):
                raise RuntimeError(f"missing camera renders for {name}/{mode}")
        portable_command = list(command)
        portable_command[0] = str(args.mm_bench.relative_to(args.repo))
        portable_command[portable_command.index("--out") + 1] = str(prefix.relative_to(args.repo))
        portable_command[-1] = str(mesh.relative_to(args.repo))
        log_path = out / f"{name}-{mode}.log"
        log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        adapter = next((line.strip() for line in log_lines
                        if line.strip().startswith("[") and "Graphics" in line), None)
        records["renders"][mode] = {
            "faces": len(triangles), "mesh_sha256": mesh_sha, "topology": topology,
            "adapter_line": adapter, "log_sha256": sha256(log_path),
            "image_provenance": "verified reuse" if reusable else "fresh render",
            "images": [{"path": image.name, "sha256": sha256(image),
                        "size": list(Image.open(image).size)} for image in images],
            "command_cwd": ".", "command": portable_command,
        }
        action = "reused verified" if reusable else "rendered"
        print(f"{action} {name}/{mode}: {len(triangles)} faces, {len(images)} views", flush=True)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--captures", type=Path, default=Path("out/filter-real-candidates"))
    parser.add_argument("--reports", type=Path, default=Path("out/pathloss-captures"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mm-bench", type=Path, default=Path("out/cmake-release/samples/mm_bench.exe"))
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--views", type=int, default=8)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--measure", type=int, default=2)
    parser.add_argument("--assets", nargs="+", choices=ASSETS, default=list(ASSETS))
    args = parser.parse_args()
    args.repo = args.repo.resolve()
    args.captures = (args.repo / args.captures).resolve() if not args.captures.is_absolute() else args.captures
    args.reports = (args.repo / args.reports).resolve() if not args.reports.is_absolute() else args.reports
    args.mm_bench = (args.repo / args.mm_bench).resolve() if not args.mm_bench.is_absolute() else args.mm_bench
    args.out = (args.repo / args.out).resolve() if not args.out.is_absolute() else args.out
    args.out.mkdir(parents=True, exist_ok=True)
    previous_receipt_path = args.out / "receipt.json"
    previous_receipt = (json.loads(previous_receipt_path.read_text(encoding="utf-8"))
                        if previous_receipt_path.is_file() else None)
    reusable_configuration = bool(previous_receipt and
                                  previous_receipt.get("image_size") == [args.size, args.size] and
                                  previous_receipt.get("views_per_asset") == args.views and
                                  previous_receipt.get("warmup_frames") == args.warmup and
                                  previous_receipt.get("measured_frames") == args.measure and
                                  previous_receipt.get("mm_bench_sha256") == sha256(args.mm_bench))
    previous_records = ({row["asset"]: row for row in previous_receipt["records"]}
                        if previous_receipt else {})
    records = []
    for name in args.assets:
        capture_location, capture_name, report_name = ASSETS[name]
        capture_dir = args.captures if capture_location == "filter" else args.reports
        records.append(render_set(args, name,
                                  capture_dir / capture_name,
                                  args.reports / report_name, args.out,
                                  previous_records.get(name), reusable_configuration))
    script = Path(__file__).resolve()
    receipt = {"scope": "matched shared-default-material desktop image-quality screen",
               "backend": "Filament mm_bench, OpenGL on host default adapter",
               "image_size": [args.size, args.size], "views_per_asset": args.views,
               "warmup_frames": args.warmup, "measured_frames": args.measure,
               "method": "same source capture and camera per asset; path-loss vs QEM at equal faces",
               "reused_from_receipt_sha256": (sha256(previous_receipt_path)
                                               if reusable_configuration else None),
               "mm_bench_sha256": sha256(args.mm_bench), "script_sha256": sha256(script),
               "records": records}
    (args.out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out / 'receipt.json'}", flush=True)


if __name__ == "__main__":
    main()
