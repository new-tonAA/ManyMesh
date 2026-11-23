"""Measure face-matched and edge-screened cuts with shared optimized layouts."""

import argparse
import importlib.metadata
import json
from pathlib import Path
import subprocess
import time

import fast_simplification
import numpy as np
import wgpu

from bench_bevy_smaa import PINNED
from bench_component_gpu import select_adapter
from bench_mixed_scene_layout import COMMIT, pack_geometry, read_geometry
from bench_mixed_scenes import SETTINGS, SceneRaster, SceneReference, gpu_mesh, run_view, sha
from cluster_decoder_surface_quality import surface_metrics
from make_refinement_pairs import vertex_normals
from prepare_scene_clusterlod import topology_counts


OFFSETS = (0, 1, -1, 2, -2)
COHORTS = ("exact", "near", "edge")
COHORT_ARMS = tuple((c, k) for c in COHORTS for k in ("match-qem", "cluster2")) + (("near", "smooth-cluster"),)
PAIRED_SETTINGS = tuple((f"{c}-{k}-msaa4", f"{c}-{k}", "msaa4") for c, k in COHORT_ARMS)
ALL_SETTINGS = SETTINGS + PAIRED_SETTINGS


def qem_target(source, inds, target):
    positions = np.ascontiguousarray(source.reshape(-1, 6)[:, :3], dtype=np.float64)
    faces = np.ascontiguousarray(inds.reshape(-1, 3), dtype=np.int32)
    best_size = np.inf
    chosen = None
    tries = []
    for offset in OFFSETS:
        request = target + offset
        start = time.perf_counter()
        v, f = fast_simplification.simplify(positions, faces, target_count=request)
        elapsed = (time.perf_counter() - start) * 1000
        actual = len(f)
        tries.append({"request": request, "faces": actual, "simplify_wall_ms": elapsed})
        if abs(actual - target) < best_size:
            best_size = abs(actual - target)
            chosen = (request, v, f)
        if actual == target:
            break
    request, v, f = chosen
    return request, v, f, tries


def shaded(positions, faces):
    normals = vertex_normals(positions, faces)
    return np.column_stack((positions, normals)).astype(np.float32).ravel()


def edge_clean(counts):
    return not any(counts[k] for k in ("repeated_vertex_faces", "duplicate_faces", "nonmanifold_edges"))


def sampled_surface(source, reference_indices, candidate, sample_count=12000):
    def geometry(v, i):
        return v.reshape(-1, 6)[:, :3].astype(np.float64), i.reshape(-1, 3)

    try:
        return {"scores": surface_metrics(geometry(source, reference_indices), geometry(*candidate),
                                           sample_count, 20261122)}
    except ValueError as error:
        if str(error) != "Surface contains degenerate triangles":
            raise
        return {"rejected": str(error)}


def build_matched(originals, asset_metadata):
    report = {}
    for asset, meta in asset_metadata.items():
        source, inds = originals[(asset, "source")]
        cluster_v, cluster_i = originals[(asset, "cluster2")]
        target = cluster_i.size // 3
        request, v, f, tries = qem_target(source, inds, target)
        mesh = shaded(v, f), f.astype(np.uint32).ravel()
        originals[(asset, "match-qem")] = mesh
        cluster_pos = cluster_v.reshape(-1, 6)[:, :3].astype(np.float64)
        cluster_f = cluster_i.reshape(-1, 3)
        originals[(asset, "smooth-cluster")] = shaded(cluster_pos, cluster_f), cluster_i
        topology = topology_counts(mesh[0].reshape(-1, 6), f)
        classified = meta["stock"]
        clean = all(edge_clean(counts) for counts in (classified["source_topology"],
                                                     classified["cuts"]["cluster2"]["topology"], topology))
        gap = len(f) - target
        report[asset] = {"cluster_faces": target, "qem_faces": len(f), "face_delta": gap,
                         "selected_request": request, "requests": tries, "qem_topology": topology,
                         "source_topology": classified["source_topology"],
                         "cluster_topology": classified["cuts"]["cluster2"]["topology"],
                         "eligible": {"exact": gap == 0, "near": abs(gap) <= 1,
                                      "edge": abs(gap) <= 1 and clean}}
        if abs(gap) <= 1:
            report[asset]["sampled_surface"] = {
                "qem": sampled_surface(source, inds, mesh),
                "cluster2": sampled_surface(source, inds, (cluster_v, cluster_i)),
            }
    return report


def verify_normals_only(packed, assets):
    for asset in assets:
        stock, i = packed[(asset, "cluster2", "cache-fetch")]
        smooth, j = packed[(asset, "smooth-cluster", "cache-fetch")]
        if (not np.array_equal(i, j) or stock.reshape(-1, 6)[:, :3].tobytes()
                != smooth.reshape(-1, 6)[:, :3].tobytes()):
            raise ValueError(f"Normal control changes positions or indices for {asset}")


def plans_for_scene(device, buffers, scene, matched):
    transforms = {a: device.create_buffer_with_data(
        data=np.asarray(scene["instance_transforms"][a], dtype=np.float32),
        usage=wgpu.BufferUsage.VERTEX) for a in scene["asset_order"]}

    def draw(asset, vertex_index):
        return (*vertex_index, transforms[asset], len(scene["instance_transforms"][asset]))

    def by_group(name, cohort):
        return [draw(a, buffers[(a, name if cohort is None or matched[a]["eligible"][cohort] else "source")])
                for a in transforms]

    plans = {name: by_group(name, None) for name in ("source", "qem", "parts", "cluster1", "cluster2")}
    plans.update({f"{c}-{k}": by_group(k, c) for c, k in COHORT_ARMS})
    return plans, transforms


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", required=True, type=Path)
    p.add_argument("--layout", required=True, type=Path)
    p.add_argument("--meshes", required=True, type=Path)
    p.add_argument("--stock", required=True, type=Path)
    p.add_argument("--upstream", required=True, type=Path)
    p.add_argument("--shader-root", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--scene")
    p.add_argument("--first-view", action="store_true")
    p.add_argument("--frames", type=int, default=24)
    p.add_argument("--batches", type=int, default=3)
    args = p.parse_args()
    version = importlib.metadata.version("fast-simplification")
    if args.frames < 1 or args.batches < 1:
        p.error("Frames and batches must be positive")
    if version != "0.2.0":
        p.error("Expected fast-simplification 0.2.0")
    git = ["git", "-C", str(args.upstream)]
    if (subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip() != COMMIT
            or subprocess.check_output(git + ["diff", "HEAD", "--", "js"], text=True)):
        p.error(f"Expected stock meshoptimizer checkout at {COMMIT}")
    for name, expected in PINNED.items():
        if sha((args.shader_root / name).read_bytes()) != expected:
            p.error(f"Bevy shader input changed: {name}")
    encoder = (args.upstream / "js/meshopt_encoder.js").resolve()
    baseline_data = args.baseline.read_bytes()
    layout_data = args.layout.read_bytes()
    baseline, layout = json.loads(baseline_data), json.loads(layout_data)
    if layout["baseline_sha256"] != sha(baseline_data) or layout["encoder_sha256"] != sha(encoder.read_bytes()):
        p.error("Layout receipt does not match benchmark or encoder")
    if args.scene is not None and args.scene not in baseline["scenes"]:
        p.error(f"No scene named {args.scene}")
    originals = read_geometry(baseline, args.meshes, args.stock)
    matched = build_matched(originals, baseline["assets"])
    tagged, audit = pack_geometry(originals, encoder)
    verify_normals_only(tagged, matched)
    for asset, metadata in layout["packing"].items():
        for geom, row in metadata.items():
            if audit[asset][geom]["cache-fetch"] != row["cache-fetch"]:
                raise ValueError(f"Reordering differs from the previous experiment for {asset}/{geom}")
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    if dict(adapter.info) != baseline["adapter"] or wgpu.__version__ != baseline["wgpu"]:
        raise ValueError("Adapter or wgpu differs from the mixed-scene benchmark")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = SceneRaster(device, *baseline["size"], args.shader_root)
    high = SceneReference(device, *baseline["reference_size"], 1, False)
    buffers = {(a, g): gpu_mesh(device, v, i) for (a, g, l), (v, i) in tagged.items() if l == "cache-fetch"}
    ref_buffers = {a: gpu_mesh(device, *originals[(a, "source")]) for a in matched}
    for a, row in matched.items():
        row["cache_fetch"] = {g: audit[a][g]["cache-fetch"] for g in ("match-qem", "smooth-cluster")}
        print(a, row["cluster_faces"], row["qem_faces"], row["eligible"], flush=True)
    scripts = (Path(__file__).name, "bench_mixed_scenes.py", "bench_mixed_scene_layout.py",
               "bench_component_gpu.py", "prepare_scene_clusterlod.py", "make_refinement_pairs.py",
               "reorder_scene_indices.mjs", "bench_bevy_smaa.py", "bench_sparse_silhouette_guide.py",
               "gray_flip.py", "bench_silhouette_guide_fusion.py", "cluster_decoder_surface_quality.py")
    report = {"baseline_sha256": sha(baseline_data), "layout_sha256": sha(layout_data),
              "encoder_sha256": sha(encoder.read_bytes()), "meshoptimizer_commit": COMMIT,
              "bevy_sha256": PINNED, "fast_simplification": version, "adapter": dict(adapter.info),
              "wgpu": wgpu.__version__, "scripts": {k: sha(Path(__file__).with_name(k).read_bytes()) for k in scripts},
              "frames_per_batch": args.frames, "batches": args.batches, "matched_assets": matched,
              "timestamp_retries": [], "scenes": {}}
    for name, scene in baseline["scenes"].items():
        if args.scene is not None and name != args.scene:
            continue
        plans, transforms = plans_for_scene(device, buffers, scene, matched)
        reference_draws = [(*ref_buffers[a], b, len(scene["instance_transforms"][a]))
                           for a, b in transforms.items()]
        counts = {k: sum(draw[2] // 3 * draw[4] for draw in plan) for k, plan in plans.items()}
        row = {"triangle_counts": counts, "views": [], "cohort_assets": {}}
        for cohort in COHORTS:
            eligible = [a for a in scene["asset_order"] if matched[a]["eligible"][cohort]]
            row["cohort_assets"][cohort] = eligible
            gap = sum(matched[a]["face_delta"] * len(scene["instance_transforms"][a]) for a in eligible)
            if not eligible or counts[f"{cohort}-match-qem"] - counts[f"{cohort}-cluster2"] != gap:
                raise ValueError(f"Unexpected face counts in {name}/{cohort}")
        if counts["near-smooth-cluster"] != counts["near-cluster2"]:
            raise ValueError(f"Normal comparison changed triangle count in {name}")
        for i, view in enumerate(scene["views"][:1] if args.first_view else scene["views"]):
            label = f"{name}/{i}"
            result = run_view(raster, high, plans, view["eye"], args.frames, args.batches, label,
                              report["timestamp_retries"], None, settings=ALL_SETTINGS,
                              reference_draws=reference_draws)
            if result["reference_srgb_sha256"] != view["reference_srgb_sha256"]:
                raise ValueError(f"Reference image differs for {label}")
            for geometry in ("source", "qem", "parts", "cluster1", "cluster2"):
                expected = layout["scenes"][name]["views"][i]["modes"][geometry]["cache-fetch"]
                measured = result["modes"][f"{geometry}-msaa4"]
                if measured["image_sha256"] != expected["image_sha256"] or measured["quality"] != expected["quality"]:
                    raise ValueError(f"Reordered MSAA control differs for {label}/{geometry}")
            row["views"].append(result)
            print(label, {c: [round(result["modes"][f"{c}-{k}-msaa4"]["quality"]["flip"], 6)
                              for k in ("match-qem", "cluster2")] for c in COHORTS}, flush=True)
        report["scenes"][name] = row
        for b in transforms.values():
            b.destroy()
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
