"""Screen per-instance stock LOD under measured draw and triangle budgets."""

import argparse
import json
from pathlib import Path
import subprocess
import time

import numpy as np
import wgpu

from bench_bevy_smaa import PINNED
from bench_component_gpu import projection_matrix, select_adapter
from bench_mixed_scene_layout import COMMIT, pack_geometry, read_geometry
from bench_mixed_scenes import SETTINGS, SceneRaster, SceneReference, gpu_mesh, run_view, sha
from bench_scene_lod_allocation import make_plans
from bench_silhouette_guide_fusion import checked_run


ID_SHADER = """
struct VertexOutput {
    @builtin(position) position: vec4f,
    @location(0) @interpolate(flat) identifier: f32,
};
@group(0) @binding(0) var<uniform> view_projection: mat4x4f;
@vertex fn vertex_main(@location(0) p: vec3f, @location(2) transform: vec4f,
                       @location(3) cs: vec2f, @location(4) identifier: f32) -> VertexOutput {
    let rotated = vec3f(cs.x * p.x + cs.y * p.z, p.y, cs.x * p.z - cs.y * p.x);
    let world = transform.xyz + transform.w * rotated;
    return VertexOutput(view_projection * vec4f(world, 1.0), identifier);
}
@fragment fn fragment_main(in: VertexOutput) -> @location(0) vec4f {
    return vec4f(in.identifier / 255.0, 0.0, 0.0, 1.0);
}
"""
POLICIES = ("bounds-greedy", "bounds-exact", "visible-source", "visible-coarse")


class OwnershipRaster(SceneReference):
    def configure_raster(self, _columns):
        d = self.device
        self.projection = d.create_buffer(size=64, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        module = d.create_shader_module(code=ID_SHADER)
        vertex_data = [
            {"array_stride": 24, "step_mode": "vertex", "attributes": [
                {"format": "float32x3", "offset": 0, "shader_location": 0}]},
            {"array_stride": 28, "step_mode": "instance", "attributes": [
                {"format": "float32x4", "offset": 0, "shader_location": 2},
                {"format": "float32x2", "offset": 16, "shader_location": 3},
                {"format": "float32", "offset": 24, "shader_location": 4}]},
        ]
        pipeline = d.create_render_pipeline(
            layout="auto", vertex={"module": module, "entry_point": "vertex_main", "buffers": vertex_data},
            fragment={"module": module, "entry_point": "fragment_main",
                      "targets": [{"format": self.output.format}]},
            primitive={"topology": "triangle-list", "cull_mode": "none"},
            depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"})
        binding = d.create_bind_group(layout=pipeline.get_bind_group_layout(0), entries=[
            {"binding": 0, "resource": {"buffer": self.projection}},
        ])
        self.pipelines = {1: (pipeline, binding)}


def set_up_instances(device, scene, groups, buffers, originals):
    ids, poses, corners, costs, eligible = {}, {}, [], [], []
    uploads = []
    source_draws, coarse_draws = [], []
    next_id = 1
    corners_idx = np.indices((2, 2, 2)).reshape(3, -1).T
    for a in scene["asset_order"]:
        t = np.asarray(scene["instance_transforms"][a], dtype=np.float32)
        poses[a] = t
        ids[a] = np.arange(next_id, next_id + len(t))
        next_id += len(t)
        id_payload = np.column_stack((t, ids[a])).astype(np.float32)
        b = device.create_buffer_with_data(data=id_payload, usage=wgpu.BufferUsage.VERTEX)
        uploads.append(b)
        source_draws.append((*buffers[a, "source"], b, len(t)))
        coarse_kind = "cluster2" if a in groups else "source"
        coarse_draws.append((*buffers[a, coarse_kind], b, len(t)))
        if a not in groups:
            continue
        delta = (buffers[a, "cluster1"][2] - buffers[a, "cluster2"][2]) // 3
        if delta <= 0:
            raise ValueError(f"{a} promotion must add triangles")
        positions = originals[a, "source"][0].reshape(-1, 6)[:, :3]
        bounds = np.stack((positions.min(axis=0), positions.max(axis=0)))
        x, y, z = bounds[corners_idx, np.arange(3)].T
        for identifier, (tx, ty, tz, scale, c, s) in zip(ids[a], t, strict=True):
            world = np.column_stack((c*x+s*z, y, c*z-s*x)) * scale + [tx, ty, tz]
            corners.append(world)
            costs.append(delta)
            eligible.append(identifier)
    if next_id > 256:
        raise ValueError("Instance IDs exceed the ownership texture range")
    return {"ids": ids, "poses": poses, "costs": np.asarray(costs, dtype=np.int64),
            "world_corners": np.asarray(corners), "eligible": np.asarray(eligible),
            "id_plans": {"source": source_draws, "coarse": coarse_draws},
            "id_buffers": uploads, "instance_count": next_id - 1}


def bound_areas(corners, eye, width, height):
    matrix = projection_matrix(width, height, eye)
    h = corners @ matrix[:3] + matrix[3]
    if np.any(h[:, :, 3] <= 0):
        raise ValueError("The frozen scenes must keep all bounds in front of the eye")
    ndc = h[:, :, :2] / h[:, :, 3, None]
    pixels = (ndc + 1.) * [width * .5, height * .5]
    lo = np.maximum(0, np.floor(pixels.min(axis=1)))
    hi = np.minimum([width, height], np.ceil(pixels.max(axis=1)))
    return np.prod(np.maximum(0, hi - lo), axis=1).astype(np.int64)


def greedy_subset(costs, values, cap):
    chosen = np.zeros(len(costs), dtype=bool)
    for i in np.argsort(-values / costs, kind="stable"):
        if values[i] > 0 and costs[i] <= cap:
            chosen[i] = True
            cap -= costs[i]
    return chosen


def exact_subset(costs, values, cap):
    scores = np.zeros(cap + 1, dtype=np.int64)
    decisions = np.zeros((len(costs), len(scores)), dtype=bool)
    for i, (cost, value) in enumerate(zip(costs, values, strict=True)):
        if value <= 0 or cost > cap:
            continue
        sub = scores[cost:]
        gain = scores[:-cost] + value
        improve = gain > sub
        sub[improve] = gain[improve]
        decisions[i, cost:] = improve
    remaining = int(np.flatnonzero(scores == scores[-1])[0])
    selected = np.zeros(len(costs), dtype=bool)
    for i in range(len(costs) - 1, -1, -1):
        if decisions[i, remaining]:
            selected[i] = True
            remaining -= costs[i]
    return selected


def measure_id(ownership, plan, scene, eye, args, retries, label):
    ownership.camera_at(eye)
    measurement, _ = checked_run(lambda: ownership.run(plan, None, args.frames, False),
                                 retries, label + "/timing")
    start = time.perf_counter()
    _, image = checked_run(lambda: ownership.run(plan, None, 1, True), retries, label + "/capture")
    synchronized_ms = (time.perf_counter() - start) * 1000
    ids = np.bincount(image.ravel(), minlength=scene["instance_count"] + 1)
    if len(ids) != scene["instance_count"] + 1:
        raise ValueError("Unexpected pixel ID value")
    return {"gpu_ms": measurement["gpuMs"], "capture_wall_ms_including_warmups": synchronized_ms,
            "counts_by_id": ids.tolist(), "hash": sha(image.tobytes())}


def instance_plan(device, buffers, scene, groups, promoted):
    plans, buckets = [], []
    for a, t in scene["poses"].items():
        ids = scene["ids"][a]
        rules = (("source", np.ones(len(t), dtype=bool)),) if a not in groups else (
            ("cluster2", ~np.isin(ids, promoted)), ("cluster1", np.isin(ids, promoted)))
        for kind, use in rules:
            if not use.any():
                continue
            bucket = device.create_buffer_with_data(data=np.ascontiguousarray(t[use]),
                                                    usage=wgpu.BufferUsage.VERTEX)
            buckets.append(bucket)
            plans.append((*buffers[a, kind], bucket, int(use.sum())))
    return plans, buckets


def evaluate_view(raster, high, ownership, label, scene, previous, archived, i, args, retries):
    groups, masks, triangles, modes, ref, buffers, instance = scene
    eye = previous["views"][i]["eye"]
    source = archived["timed_views"][i]
    cap = source["choices"]["50"]["cap"] - triangles[0]
    costs, eligible = instance["costs"], instance["eligible"]
    if costs.sum() != triangles[-1] - triangles[0]:
        raise ValueError("Instance and group face budgets do not agree")

    cpu = []
    for _ in range(32):
        start = time.perf_counter()
        area = bound_areas(instance["world_corners"], eye, raster.width, raster.height)
        greedy = greedy_subset(costs, area, cap)
        cpu.append((time.perf_counter() - start) * 1000)
    id_data = {k: measure_id(ownership, plan, instance, eye, args, retries, f"{label}/{k}-id")
               for k, plan in instance["id_plans"].items()}
    if sum(id_data["source"]["counts_by_id"][1:]) != source["coverage_pixels"]:
        raise ValueError(f"Ownership pass has wrong full-source coverage for {label}")

    scores = {"bounds-exact": area,
              "visible-source": np.asarray(id_data["source"]["counts_by_id"])[eligible],
              "visible-coarse": np.asarray(id_data["coarse"]["counts_by_id"])[eligible]}
    selection = {"bounds-greedy": greedy, **{k: exact_subset(costs, v, cap) for k, v in scores.items()}}
    aliases, extra, metadata, uploads = {}, {}, {}, []
    group_modes = {f"group-{key}": val["masks"]["area"] for key, val in source["choices"].items()}
    group_modes |= {"screened-low": 0, "screened-high": len(masks) - 1}
    unique = {}
    for name, code in group_modes.items():
        aliases[name] = f"mask-{code}"
        extra[aliases[name]] = masks[code]
        chosen = tuple(int(v) for j, a in enumerate(groups) if code & (1 << j) for v in instance["ids"][a])
        unique[chosen] = aliases[name]

    for policy, flags in selection.items():
        chosen = tuple(int(v) for v in eligible[flags])
        if chosen not in unique:
            unique[chosen] = policy
            extra[policy], new_uploads = instance_plan(raster.device, buffers, instance, groups, chosen)
            uploads.extend(new_uploads)
        mode = unique[chosen]
        aliases[policy] = mode
        draws = extra[mode]
        faces = sum(v[2] // 3 * v[4] for v in draws)
        if faces != triangles[0] + costs[flags].sum() or faces > triangles[0] + cap:
            raise ValueError(f"{policy} escaped its exact face budget")
        metadata[policy] = {"promoted_ids": chosen, "draws": len(draws), "faces": faces}
    settings = SETTINGS + tuple((name, name, "msaa4") for name in extra)
    result = run_view(raster, high, modes | extra, eye, args.frames, args.batches,
                      label, retries, None, settings=settings, reference_draws=ref)
    if result["reference_srgb_sha256"] != source["reference_srgb_sha256"]:
        raise ValueError("The archive reference changed")
    if result["coverage_pixels"] != source["coverage_pixels"]:
        raise ValueError("Source ownership area differs from source coverage")
    for name, prior in source["modes"].items():
        if name in result["modes"] and (result["modes"][name]["image_sha256"] != prior["image_sha256"]
                                          or result["modes"][name]["quality"] != prior["quality"]):
            raise ValueError(f"Archived control capture changed for {label}/{name}")
    result.update({"face_cap": triangles[0] + cap, "area_group_faces": triangles[group_modes["group-50"]],
                   "area_group_draws": len(masks[group_modes["group-50"]]), "reference_aliases": aliases,
                   "policies": metadata, "bounds_and_greedy_cpu_ms": cpu,
                   "bounds_area_pixels": area.tolist(), "ownership": id_data})
    for b in uploads:
        b.destroy()
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", required=True, type=Path)
    p.add_argument("--allocation", required=True, type=Path)
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
    baseline_data = args.baseline.read_bytes()
    alloc_data = args.allocation.read_bytes()
    baseline, previous = json.loads(baseline_data), json.loads(alloc_data)
    if previous["baseline_sha256"] != sha(baseline_data):
        p.error("The prior allocation belongs to different scenes")
    if args.scene is not None and args.scene not in baseline["scenes"]:
        p.error(f"No scene named {args.scene}")
    git = ["git", "-C", str(args.upstream)]
    if (subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip() != COMMIT
            or subprocess.check_output(git + ["diff", "HEAD", "--", "js"], text=True)):
        p.error(f"Expected stock meshoptimizer checkout at {COMMIT}")
    encoder = (args.upstream / "js/meshopt_encoder.js").resolve()
    if sha(encoder.read_bytes()) != previous["encoder_sha256"]:
        p.error("Meshoptimizer encoder does not match the previous benchmark")
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
    ownership = OwnershipRaster(device, *baseline["size"], 1, False)
    buffers = {(a, k): gpu_mesh(device, v, i) for (a, k, l), (v, i) in packed.items() if l == "cache-fetch"}
    supplied = {a: gpu_mesh(device, *originals[a, "source"]) for a in baseline["assets"]}
    scripts = (Path(__file__).name, "bench_scene_lod_allocation.py", "bench_mixed_scenes.py",
               "bench_mixed_scene_layout.py", "bench_component_gpu.py", "reorder_scene_indices.mjs",
               "bench_bevy_smaa.py", "bench_sparse_silhouette_guide.py", "gray_flip.py")
    report = {"baseline_sha256": sha(baseline_data), "allocation_sha256": sha(alloc_data),
              "encoder_sha256": sha(encoder.read_bytes()), "bevy_sha256": PINNED,
              "adapter": dict(adapter.info), "wgpu": wgpu.__version__,
              "scripts": {k: sha(Path(__file__).with_name(k).read_bytes()) for k in scripts},
              "frames_per_batch": args.frames, "batches": args.batches, "timestamp_retries": [], "scenes": {}}
    for name, old in baseline["scenes"].items():
        if args.scene is not None and args.scene != name:
            continue
        archived = previous["scenes"][name]
        groups, masks, triangles, modes, ref, uploads = make_plans(
            device, old, baseline["assets"], buffers, supplied)
        if groups != archived["groups"] or triangles != archived["mask_triangle_counts"]:
            raise ValueError(f"Expected frozen incidence cohort and masks for {name}")
        instance = set_up_instances(device, old, groups, buffers, originals)
        setup = groups, masks, triangles, modes, ref, buffers, instance
        views = []
        for i in range(1 if args.first_view else len(old["views"])):
            label = f"{name}/{i}"
            v = evaluate_view(raster, high, ownership, label, setup, old, archived, i,
                              args, report["timestamp_retries"])
            views.append(v)
            print(label, {k: (r["faces"], r["draws"], round(v["modes"][v["reference_aliases"][k]]["quality"]["flip"], 6))
                          for k, r in v["policies"].items()}, flush=True)
        report["scenes"][name] = {"eligible_instance_ids": instance["eligible"].tolist(),
                                  "upgrade_costs": instance["costs"].tolist(),
                                  "ids_by_asset": {k: v.tolist() for k, v in instance["ids"].items()},
                                  "base_faces": triangles[0], "views": views}
        for b in [*uploads.values(), *instance["id_buffers"]]:
            b.destroy()
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
