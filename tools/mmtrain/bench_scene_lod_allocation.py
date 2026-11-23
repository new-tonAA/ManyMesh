"""Evaluate groupwise stock LOD allocation against area and a finite render oracle."""

import argparse
import json
from pathlib import Path
import subprocess
import time

import numpy as np
import wgpu

from bench_bevy_smaa import PINNED
from bench_component_gpu import linear_gray_to_srgb, select_adapter
from bench_mixed_scene_layout import COMMIT, pack_geometry, read_geometry
from bench_mixed_scenes import SETTINGS, SceneRaster, SceneReference, gpu_mesh, run_view, sha
from bench_scene_face_budgets import edge_clean
from gray_flip import gray_flip


CAPS = (("25", 1), ("50", 2), ("75", 3))


def capture_msaa(raster, plan):
    encoder = raster.device.create_command_encoder()
    raster.encode(encoder, plan, "msaa4")
    raster.queue.submit([encoder.finish()])
    raw = raster.queue.read_texture(
        {"texture": raster.output},
        {"bytes_per_row": raster.width * 4, "rows_per_image": raster.height},
        (raster.width, raster.height, 1))
    return np.frombuffer(raw, dtype=np.uint8).reshape(raster.height, raster.width, 4)[..., 0].copy()


def make_plans(device, scene, assets, buffers, supplied):
    order = scene["asset_order"]
    payload = scene["instance_transforms"]
    instance_buffers = {a: device.create_buffer_with_data(
        data=np.asarray(payload[a], dtype=np.float32), usage=wgpu.BufferUsage.VERTEX) for a in order}

    def draw(a, mesh):
        return (*mesh, instance_buffers[a], len(payload[a]))

    group_order = []
    for a in order:
        stock = assets[a]["stock"]
        if all(edge_clean(row) for row in (stock["source_topology"],
                                            stock["cuts"]["cluster1"]["topology"],
                                            stock["cuts"]["cluster2"]["topology"])):
            group_order.append(a)
    if len(group_order) < 2:
        raise ValueError("A scene needs at least two eligible asset groups")
    bit = {a: 1 << j for j, a in enumerate(group_order)}
    masks = []
    for code in range(1 << len(group_order)):
        plan = []
        for a in order:
            kind = "source" if a not in bit else "cluster1" if code & bit[a] else "cluster2"
            plan.append(draw(a, buffers[a, kind]))
        masks.append(plan)
    triangles = [sum(v[2] // 3 * v[4] for v in plan) for plan in masks]
    plans = {kind: [draw(a, buffers[a, kind]) for a in order]
             for kind in ("source", "qem", "parts", "cluster1", "cluster2")}
    render_reference = [draw(a, supplied[a]) for a in order]
    return group_order, masks, triangles, plans, render_reference, instance_buffers


def score_pool(raster, high, scene, masks, reference, groups):
    width, height = raster.width, raster.height
    scores = []
    singles = [1 << j for j in range(len(groups))]
    for old in scene["views"]:
        raster.camera_at(old["eye"])
        high.camera_at(old["eye"])
        ref_raw = capture_msaa(high, reference)
        ref = linear_gray_to_srgb(ref_raw.reshape(height, 2, width, 2).mean(axis=(1, 3)))
        if sha(ref.tobytes()) != old["reference_srgb_sha256"]:
            raise ValueError("Unchanged supersampled reference does not reproduce")
        start = time.perf_counter()
        rows = []
        for plan in masks:
            raw = capture_msaa(raster, plan)
            if not np.any(raw):
                raise ValueError("Blank allocation capture")
            rows.append({"flip": gray_flip(ref, linear_gray_to_srgb(raw)), "image_sha256": sha(raw.tobytes())})
        total_ms = (time.perf_counter() - start) * 1000
        base = rows[0]["flip"]
        if base <= 0:
            raise ValueError("Coarse allocation already equals the supersampled reference")
        scores.append({"masks": rows, "pool_capture_score_wall_ms": total_ms,
                       "relative_single_benefits": [(base - rows[m]["flip"]) / base for m in singles]})
    return scores


def select_masks(pool, i, triangles, area, count):
    start = time.perf_counter()
    costs = np.asarray(triangles, dtype=np.int64)
    mask_ids = np.arange(len(triangles))
    bits = ((mask_ids[:, None] >> np.arange(count)) & 1).astype(np.float64)
    current = pool[i]["relative_single_benefits"]
    other_views = [row["relative_single_benefits"] for j, row in enumerate(pool) if j != i]
    fitted = np.mean(other_views, axis=0)
    scored = {"area": bits @ area, "heldout-profile": bits @ fitted,
              "same-view-additive": bits @ current,
              "oracle": -np.asarray([m["flip"] for m in pool[i]["masks"]])}
    choices = {}
    for name, quarter in CAPS:
        cap = triangles[0] + quarter * (triangles[-1] - triangles[0]) // 4
        allowed = np.flatnonzero(costs <= cap)
        best = {k: int(min(allowed, key=lambda m: (-value[m], costs[m], m)))
                for k, value in scored.items()}
        choices[name] = {"cap": cap, "feasible_masks": len(allowed), "masks": best}
    return choices, 1000 * (time.perf_counter() - start)


def view_experiment(raster, high, modes, ref, scene, archived, pool, i, groups, masks, triangles,
                    label, frames, batches, retries):
    old = scene["views"][i]
    area = [old["group_coverage_pixels"][scene["asset_order"].index(a)] for a in groups]
    choices, select_ms = select_masks(pool, i, triangles, area, len(groups))
    timed = {0, len(masks) - 1}
    for setup in choices.values():
        for policy in ("area", "heldout-profile", "oracle"):
            timed.add(setup["masks"][policy])
    mixes = {f"mask-{j}": masks[j] for j in sorted(timed)}
    settings = SETTINGS + tuple((k, k, "msaa4") for k in mixes)
    result = run_view(raster, high, modes | mixes, old["eye"], frames, batches,
                      label, retries, None, settings=settings, reference_draws=ref)
    if result["reference_srgb_sha256"] != old["reference_srgb_sha256"]:
        raise ValueError("Timed reference differs from original reference")
    for k, _, _ in SETTINGS:
        r, prior = result["modes"][k], archived["views"][i]["modes"][k]
        if r["image_sha256"] != prior["image_sha256"] or r["quality"] != prior["quality"]:
            raise ValueError(f"Archived optimized baseline differs at {label}/{k}")
    for m in timed:
        actual = result["modes"][f"mask-{m}"]
        if (actual["image_sha256"] != pool[i]["masks"][m]["image_sha256"]
                or actual["quality"]["flip"] != pool[i]["masks"][m]["flip"]):
            raise ValueError("Timed allocation differs from enumerated capture")
    result.update({"choices": choices, "selection_wall_ms": select_ms, "area_benefits": area})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", required=True, type=Path)
    p.add_argument("--optimized", required=True, type=Path)
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
    if args.frames < 1 or args.batches < 1:
        p.error("Frames and batches must be positive")
    base_data = args.baseline.read_bytes()
    opt_data = args.optimized.read_bytes()
    baseline, optimized = json.loads(base_data), json.loads(opt_data)
    if optimized["baseline_sha256"] != sha(base_data):
        p.error("Mismatched benchmark receipts")
    if args.scene is not None and args.scene not in baseline["scenes"]:
        p.error(f"No scene named {args.scene}")
    git = ["git", "-C", str(args.upstream)]
    if (subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip() != COMMIT
            or subprocess.check_output(git + ["diff", "HEAD", "--", "js"], text=True)):
        p.error(f"Expected stock meshoptimizer checkout at {COMMIT}")
    encoder = (args.upstream / "js/meshopt_encoder.js").resolve()
    if sha(encoder.read_bytes()) != optimized["encoder_sha256"]:
        p.error("Meshoptimizer WebAssembly differs from optimized benchmark")
    for k, v in PINNED.items():
        if sha((args.shader_root / k).read_bytes()) != v:
            p.error(f"Bevy input hash differs: {k}")
    originals = read_geometry(baseline, args.meshes, args.stock)
    packed, _ = pack_geometry(originals, encoder)
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    if dict(adapter.info) != baseline["adapter"] or wgpu.__version__ != baseline["wgpu"]:
        raise ValueError("Adapter or wgpu differs from benchmark")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = SceneRaster(device, *baseline["size"], args.shader_root)
    high = SceneReference(device, *baseline["reference_size"], 1, False)
    buffers = {(a, g): gpu_mesh(device, v, i) for (a, g, l), (v, i) in packed.items() if l == "cache-fetch"}
    supplied = {a: gpu_mesh(device, *originals[a, "source"]) for a in baseline["assets"]}
    scripts = (Path(__file__).name, "bench_mixed_scenes.py", "bench_mixed_scene_layout.py",
               "bench_scene_face_budgets.py", "bench_component_gpu.py", "reorder_scene_indices.mjs",
               "bench_bevy_smaa.py", "bench_sparse_silhouette_guide.py", "gray_flip.py")
    report = {"baseline_sha256": sha(base_data), "optimized_sha256": sha(opt_data),
              "encoder_sha256": sha(encoder.read_bytes()), "meshoptimizer_commit": COMMIT,
              "bevy_sha256": PINNED, "adapter": dict(adapter.info), "wgpu": wgpu.__version__,
              "scripts": {k: sha(Path(__file__).with_name(k).read_bytes()) for k in scripts},
              "frames_per_batch": args.frames, "batches": args.batches, "timestamp_retries": [], "scenes": {}}
    for name, scene in baseline["scenes"].items():
        if args.scene is not None and name != args.scene:
            continue
        groups, masks, triangles, modes, ref, instance_buffers = make_plans(
            device, scene, baseline["assets"], buffers, supplied)
        pool = score_pool(raster, high, scene, masks, ref, groups)
        print(name, len(masks), "mask captures per view", flush=True)
        timed = []
        for i in range(1 if args.first_view else len(scene["views"])):
            result = view_experiment(raster, high, modes, ref, scene, optimized["scenes"][name],
                                     pool, i, groups, masks, triangles, f"{name}/{i}",
                                     args.frames, args.batches, report["timestamp_retries"])
            timed.append(result)
            print(name, i, result["choices"]["50"]["masks"], flush=True)
        report["scenes"][name] = {"groups": groups, "mask_triangle_counts": triangles,
                                  "all_views_pool": pool, "timed_views": timed}
        for b in instance_buffers.values():
            b.destroy()
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
