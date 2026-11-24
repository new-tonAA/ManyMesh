"""Measure AA and geometry baselines in mixed million-triangle scenes."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
import wgpu

from bench_bevy_smaa import PINNED, SmaaOffscreen
from bench_component_gpu import Offscreen, linear_gray_to_srgb, load_export, projection_matrix, select_adapter
from bench_silhouette_guide_fusion import checked_run
from bench_sparse_silhouette_guide import CONTROL_MODES, score


SETTINGS = CONTROL_MODES + (
    ("cluster1-msaa4", "cluster1", "msaa4"),
    ("cluster2-msaa4", "cluster2", "msaa4"),
)
SCENES = {
    "display-wall": (
        ("AntiqueCamera", "Avocado", "FlightHelmet", "GlassVaseFlowers", "SheenCloth", "ToyCar", "WaterBottle"),
        (7, 5), ((0., .6, 17.), (3.0, 1.35, 17.), (-3.4, -.6, 17.6))),
    "layered-aisles": (
        ("BarramundiFish", "CesiumMilkTruck", "FlightHelmet", "IridescenceLamp", "Lantern", "SheenChair", "ToyCar"),
        (7, 6), ((.5, 3.2, 19.), (3.1, 4.2, 17.8), (-3.5, 4.5, 18.4))),
    "mixed-scale": (
        ("AntiqueCamera", "GlassVaseFlowers", "IridescenceLamp", "Lantern",
         "SheenChair", "SheenCloth", "StainedGlassLamp", "ToyCar"),
        (8, 6), ((.2, 2.0, 18.), (2.4, 2.65, 18.6), (-3.0, 1.5, 17.4))),
}
SHADER = """
struct VertexOutput {
    @builtin(position) position: vec4f,
    @location(0) light: f32,
};
@group(0) @binding(0) var<uniform> view_projection: mat4x4f;

fn yaw(point: vec3f, cs: vec2f) -> vec3f {
    return vec3f(cs.x * point.x + cs.y * point.z, point.y,
                 cs.x * point.z - cs.y * point.x);
}

@vertex fn vertex_main(@location(0) position: vec3f, @location(1) normal: vec3f,
                       @location(2) transform: vec4f, @location(3) cs: vec2f) -> VertexOutput {
    let world = transform.xyz + transform.w * yaw(position, cs);
    let light = 0.20 + 0.75 * clamp(dot(yaw(normal, cs), vec3f(0.36, 0.80, 0.48)), 0.0, 1.0);
    return VertexOutput(view_projection * vec4f(world, 1.0), light);
}

@fragment fn fragment_main(in: VertexOutput) -> @location(0) vec4f {
    return vec4f(vec3f(in.light), 1.0);
}
"""


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def scene_instances(scene):
    assets, (cols, rows), eyes = SCENES[scene]
    groups = {asset: [] for asset in assets}
    for row in range(rows):
        for col in range(cols):
            centered = col - (cols - 1) / 2
            asset = assets[(col + 2 * row) % len(assets)]
            angle = 0.35 * (col - row) + 0.15 * ((col + row) % 3)
            if scene == "display-wall":
                position = (centered * 1.95, (2 - row) * 1.78, 0.12 * (col % 3))
                scale = 0.88
            elif scene == "layered-aisles":
                position = (centered * 1.56 + 0.22 * (row % 2), -.6 + .11 * (col % 3), 4.5 - row * 1.78)
                scale = 1.08
            else:
                position = (centered * 1.60 + 0.27 * (row % 2), -1.4 + 0.78 * row, 4.2 - 1.52 * row)
                scale = (1.22, 1.05, .81, .65, .52, .43)[row] * (0.85 + .14 * (col % 3))
            groups[asset].append((*position, scale, math.cos(angle), math.sin(angle)))
    return {asset: np.asarray(groups[asset], dtype=np.float32) for asset in assets}, eyes


class SceneGeometry:
    def configure_raster(self, _columns):
        device = self.device
        self.projection = device.create_buffer(size=64, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        vertex_buffers = [
            {"array_stride": 24, "step_mode": "vertex", "attributes": [
                {"format": "float32x3", "offset": 0, "shader_location": 0},
                {"format": "float32x3", "offset": 12, "shader_location": 1}]},
            {"array_stride": 24, "step_mode": "instance", "attributes": [
                {"format": "float32x4", "offset": 0, "shader_location": 2},
                {"format": "float32x2", "offset": 16, "shader_location": 3}]},
        ]
        module = device.create_shader_module(code=SHADER)
        self.pipelines = {}
        for samples in (1, 4):
            pipeline = device.create_render_pipeline(
                layout="auto",
                vertex={"module": module, "entry_point": "vertex_main", "buffers": vertex_buffers},
                fragment={"module": module, "entry_point": "fragment_main",
                          "targets": [{"format": self.output.format}]},
                depth_stencil={"format": "depth32float", "depth_write_enabled": True, "depth_compare": "less"},
                primitive={"topology": "triangle-list", "cull_mode": "none"},
                multisample={"count": samples})
            group = device.create_bind_group(
                layout=pipeline.get_bind_group_layout(0),
                entries=[{"binding": 0, "resource": {"buffer": self.projection}}])
            self.pipelines[samples] = (pipeline, group)

    def camera_at(self, eye):
        self.queue.write_buffer(self.projection, 0, projection_matrix(self.width, self.height, eye))

    def draw_geometry(self, rendering, draws, msaa):
        pipeline, group = self.pipelines[4 if msaa else 1]
        rendering.set_pipeline(pipeline)
        rendering.set_bind_group(0, group)
        for positions, indices, count, transforms, instances in draws:
            rendering.set_vertex_buffer(0, positions)
            rendering.set_vertex_buffer(1, transforms)
            rendering.set_index_buffer(indices, "uint32")
            rendering.draw_indexed(count, instances)


class SceneRaster(SceneGeometry, SmaaOffscreen):
    pass


class SceneReference(SceneGeometry, Offscreen):
    pass


def gpu_mesh(device, vertices, inds, source_vertices=None):
    if source_vertices is None:
        source_vertices = device.create_buffer_with_data(data=vertices, usage=wgpu.BufferUsage.VERTEX)
    ib = device.create_buffer_with_data(data=inds, usage=wgpu.BufferUsage.INDEX)
    return source_vertices, ib, len(inds)


def load_asset_buffers(device, root, manifest, cuts_root, cuts):
    buffers = {}
    for asset, spec in manifest["assets"].items():
        entry = {}
        for kind in ("source", "qem", "parts"):
            data, inds = load_export(root / asset / f"{kind}.ply", spec["exports"][kind])
            entry[kind] = gpu_mesh(device, data, inds)
        for depth in (1, 2):
            kind = f"cluster{depth}"
            info = cuts["assets"][asset]["cuts"][kind]
            file = cuts_root / asset / f"cluster-depth{depth}.npy"
            if sha(file.read_bytes()) != info["sha256"]:
                raise ValueError(f"Invalid cluster index hash for {asset}/{kind}")
            indices = np.load(file, allow_pickle=False)
            if (indices.dtype != np.uint32 or indices.shape != (3 * info["count"],)
                    or indices.max() >= spec["exports"]["source"]["vertices"]):
                raise ValueError(f"Invalid cluster indices for {asset}/{kind}")
            entry[kind] = gpu_mesh(device, None, indices, entry["source"][0])
        if entry["qem"][2] != entry["parts"][2]:
            raise ValueError(f"Frozen QEM and component face counts differ on {asset}")
        buffers[asset] = entry
    return buffers


def run_view(raster, reference, plans, eye, frames, batches, label, retries, captures,
             settings=SETTINGS, reference_draws=None):
    raster.camera_at(eye)
    reference.camera_at(eye)

    def run(mode_name, kind, configuration, n, capture, stage):
        call = lambda: raster.run(plans[kind], configuration, n, capture)
        stats, image = checked_run(call, retries, f"{label}/{mode_name}/{stage}")
        return stats["gpuMs"], image

    rows = {mode: {"gpu_ms": []} for mode, _, _ in settings}
    for mode, kind, opt in settings:
        run(mode, kind, opt, 8, False, "precondition")
    for batch in range(batches):
        start = 4 * batch % len(settings)
        for mode, kind, opt in settings[start:] + settings[:start]:
            elapsed, _ = run(mode, kind, opt, frames, False, f"batch-{batch + 1}")
            rows[mode]["gpu_ms"].extend(elapsed)

    if reference_draws is None:
        reference_draws = plans["source"]
    _, high = checked_run(lambda: reference.run(reference_draws, "msaa4", 1, True),
                           retries, f"{label}/reference")
    ref = linear_gray_to_srgb(high.reshape(raster.height, 2, raster.width, 2).mean(axis=(1, 3)))
    for mode, kind, opt in settings:
        _, image = run(mode, kind, opt, 1, True, "capture")
        srgb = linear_gray_to_srgb(image)
        rows[mode]["image_sha256"] = sha(image.tobytes())
        rows[mode]["quality"] = score(ref, srgb)
        rows[mode]["silhouette_xor_fraction"] = float(np.mean((image > 0) != (ref > 0)))
        if mode == "source-native":
            source_coverage = image > 0
        if captures is not None and mode in ("source-msaa4", "qem-msaa4", "parts-msaa4", "cluster2-msaa4"):
            Image.fromarray(srgb).save(captures / f"{mode}.png")

    occupancy = np.zeros(ref.shape, dtype=np.uint8)
    group_pixels = []
    for i, draw in enumerate(plans["source"]):
        _, img = checked_run(lambda: raster.run([draw], None, 1, True), retries, f"{label}/group-{i}")
        active = img > 0
        occupancy += active
        group_pixels.append(int(active.sum()))
    if not np.array_equal(source_coverage, occupancy > 0):
        raise ValueError(f"Grouped source coverage differs from the combined draw: {label}")
    if captures is not None:
        Image.fromarray(ref).save(captures / "reference.png")
    return {"eye": eye, "reference_srgb_sha256": sha(ref.tobytes()),
            "coverage_pixels": int(source_coverage.sum()), "group_coverage_pixels": group_pixels,
            "cross_asset_overlap_pixels": int((occupancy > 1).sum()), "modes": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--meshes", type=Path, required=True)
    parser.add_argument("--stock", type=Path, required=True)
    parser.add_argument("--shader-root", type=Path, required=True)
    parser.add_argument("--source-lists", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--captures", type=Path)
    parser.add_argument("--scene", choices=tuple(SCENES))
    parser.add_argument("--first-view", action="store_true")
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--batches", type=int, default=3)
    args = parser.parse_args()
    if args.frames < 1 or args.batches < 1:
        parser.error("Frames and batches must be positive")
    for name, expected in PINNED.items():
        if sha((args.shader_root / name).read_bytes()) != expected:
            raise ValueError(f"Changed Bevy input {name}")
    manifest_data = args.manifest.read_bytes()
    manifest = json.loads(manifest_data)
    cuts_data = (args.stock / "cluster-cuts.json").read_bytes()
    cuts = json.loads(cuts_data)
    if cuts["manifest_sha256"] != sha(manifest_data):
        raise ValueError("Stock cuts do not match the frozen exports")
    sources = {row["name"]: row for path in args.source_lists for row in json.loads(path.read_bytes())}
    if not set(manifest["assets"]) <= sources.keys():
        raise ValueError("Missing asset provenance")
    used = {k: {"provenance": sources[k], "geometry": v["exports"], "stock": cuts["assets"][k]}
            for k, v in manifest["assets"].items()}
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    width, height = 1280, 720
    raster = SceneRaster(device, width, height, args.shader_root)
    ref = SceneReference(device, 2 * width, 2 * height, 1, False)
    buffers = load_asset_buffers(device, args.meshes, manifest, args.stock, cuts)
    scripts = (Path(__file__).name, "bench_component_gpu.py", "bench_bevy_smaa.py",
               "bench_silhouette_guide_fusion.py", "bench_sparse_silhouette_guide.py", "gray_flip.py")
    report = {"size": [width, height], "reference_size": [2 * width, 2 * height],
              "adapter": dict(adapter.info), "wgpu": wgpu.__version__, "frames_per_batch": args.frames,
              "batches": args.batches, "assets": used, "manifest_sha256": sha(manifest_data),
              "stock_manifest_sha256": sha(cuts_data), "stock_commit": cuts["upstream_commit"],
              "stock_binary_sha256": cuts["demo_sha256"], "bevy_sha256": PINNED,
              "scripts": {k: sha(Path(__file__).with_name(k).read_bytes()) for k in scripts},
              "timestamp_retries": [], "scenes": {}}
    for scene in ([args.scene] if args.scene else SCENES):
        groups, eyes = scene_instances(scene)
        transforms = {k: device.create_buffer_with_data(data=v, usage=wgpu.BufferUsage.VERTEX)
                      for k, v in groups.items()}
        plans = {kind: [(*buffers[k][kind], transforms[k], len(group)) for k, group in groups.items()]
                 for kind in ("source", "qem", "parts", "cluster1", "cluster2")}
        triangles = {kind: sum(draw[2] // 3 * draw[4] for draw in plan) for kind, plan in plans.items()}
        if triangles["source"] < 1_000_000 or len(groups) < 5:
            raise ValueError(f"{scene} does not satisfy the scene scale contract")
        row = {"asset_order": list(groups), "instance_transforms": {k: v.tolist() for k, v in groups.items()},
               "triangle_counts": triangles, "indexed_draws": len(groups), "views": []}
        for i, eye in enumerate(eyes[:1] if args.first_view else eyes):
            captures = args.captures / scene / str(i) if args.captures is not None else None
            if captures is not None:
                captures.mkdir(parents=True, exist_ok=True)
            view = run_view(raster, ref, plans, eye, args.frames, args.batches,
                            f"{scene}/{i}", report["timestamp_retries"], captures)
            row["views"].append(view)
            print(scene, i, triangles["source"], view["cross_asset_overlap_pixels"],
                  {k: round(float(np.median(view["modes"][k]["gpu_ms"])), 3)
                   for k in ("source-msaa4", "qem-msaa4", "parts-msaa4", "cluster2-msaa4")}, flush=True)
        report["scenes"][scene] = row
        for b in transforms.values():
            b.destroy()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
