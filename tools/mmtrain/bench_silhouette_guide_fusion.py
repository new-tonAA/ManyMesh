"""Measure narrow-band fusion of a coarse mesh and a half-resolution fine guide."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import wgpu

from bench_bevy_smaa import PINNED, SmaaOffscreen, score
from bench_component_gpu import Offscreen, linear_gray_to_srgb, load_export, select_adapter


FUSION = """
@group(0) @binding(0) var coarse: texture_2d<f32>;
@group(0) @binding(1) var guide: texture_2d<f32>;
@group(0) @binding(2) var linear_clamp: sampler;
override restore_detail: bool = false;

@vertex fn vertex_main(@builtin(vertex_index) n: u32) -> @builtin(position) vec4f {
    let p = vec2f(f32((n << 1u) & 2u), f32(n & 2u));
    return vec4f(2.0 * p - 1.0, 0.0, 1.0);
}
fn coarse_mean(cell: vec2f, dims: vec2f) -> f32 {
    return textureSampleLevel(coarse, linear_clamp, (2.0 * cell + 1.0) / dims, 0.0).r;
}
@fragment fn fragment_main(@builtin(position) position: vec4f) -> @location(0) vec4f {
    let dims = vec2i(textureDimensions(coarse));
    let pixel = vec2i(position.xy);
    let value = textureLoad(coarse, pixel, 0).r;
    let foreground = value > 0.0;
    let offsets = array<vec2i, 12>(vec2i(-2,0), vec2i(2,0), vec2i(0,-2), vec2i(0,2),
                                  vec2i(-1,-1), vec2i(-1,1), vec2i(1,-1), vec2i(1,1),
                                  vec2i(-1,0), vec2i(1,0), vec2i(0,-1), vec2i(0,1));
    var edge = false;
    for (var i = 0u; i < 12u; i += 1u) {
        let p = clamp(pixel + offsets[i], vec2i(0), dims - 1);
        if (textureLoad(coarse, p, 0).r > 0.0) != foreground {
            edge = true;
            break;
        }
    }
    if !edge { return vec4f(vec3f(value), 1.0); }
    let fine = textureSampleLevel(guide, linear_clamp, position.xy / vec2f(dims), 0.0).r;
    if !restore_detail { return vec4f(vec3f(fine), 1.0); }
    // Add back frequencies that disappear when the coarse image is box averaged and upscaled.
    let g = position.xy * 0.5 - 0.5;
    let base = floor(g);
    let t = fract(g);
    let top = mix(coarse_mean(base, vec2f(dims)), coarse_mean(base + vec2f(1,0), vec2f(dims)), t.x);
    let bottom = mix(coarse_mean(base + vec2f(0,1), vec2f(dims)),
                     coarse_mean(base + vec2f(1,1), vec2f(dims)), t.x);
    return vec4f(vec3f(clamp(fine + value - mix(top, bottom, t.y), 0.0, 1.0)), 1.0);
}
"""

MODES = (("source-native", "source", None), ("source-msaa4", "source", "msaa4"),
         ("source-smaa", "source", "smaa"), ("source-linear", "source", "linear"),
         ("source-cubic", "source", "cubic"), ("qem-msaa4", "qem", "msaa4"),
         ("qem-smaa", "qem", "smaa"), ("parts-msaa4", "parts", "msaa4"),
         ("parts-smaa", "parts", "smaa"), ("guide-only", None, "guide-only"),
         ("guide-copy", None, "guide-copy"), ("guide-detail", None, "guide-detail"))

INVALID_TIMESTAMPS = {
    "Invalid GPU timestamp ordering", "GPU interval exceeds synchronized wall time",
    "Invalid reconstruction timestamp ordering", "Unexpected SMAA timestamp order",
    "SMAA timestamps exceed synchronized wall time", "Invalid GPU timestamps for the guide pipeline",
}


def checked_run(call, retries, label):
    for attempt in range(3):
        try:
            return call()
        except (RuntimeError, ValueError) as error:
            if str(error) not in INVALID_TIMESTAMPS or attempt == 2:
                raise
            retries.append({"run": label, "error": str(error)})
            print(f"Retrying {label}: {error}", flush=True)


class GuidedOffscreen(SmaaOffscreen):
    def __init__(self, device, width, height, shader_root):
        super().__init__(device, width, height, shader_root)
        usage = wgpu.TextureUsage.RENDER_ATTACHMENT
        self.guide_msaa = device.create_texture(size=(width//2, height//2, 1), sample_count=4,
                                                 format="rgba8unorm", usage=usage).create_view()
        self.guide_depth = device.create_texture(size=(width//2, height//2, 1), sample_count=4,
                                                  format="depth32float", usage=usage).create_view()
        self.coarse_output = device.create_texture(
            size=(width, height, 1), format="rgba8unorm",
            usage=usage | wgpu.TextureUsage.TEXTURE_BINDING).create_view()
        sampler = device.create_sampler(mag_filter="linear", min_filter="linear")
        module = device.create_shader_module(code=FUSION)
        self.fusion = {"guide-only": self.upscale["linear"]}
        for name in ("guide-copy", "guide-detail"):
            pipeline = device.create_render_pipeline(
                layout="auto", vertex={"module": module, "entry_point": "vertex_main"},
                fragment={"module": module, "entry_point": "fragment_main",
                          "constants": {"restore_detail": name == "guide-detail"},
                          "targets": [{"format": "rgba8unorm"}]})
            bind = device.create_bind_group(layout=pipeline.get_bind_group_layout(0), entries=[
                {"binding": 0, "resource": self.coarse_output}, {"binding": 1, "resource": self.low_view},
                {"binding": 2, "resource": sampler},
            ])
            self.fusion[name] = pipeline, bind

    def encode_guide(self, encoder, meshes, mode, query=None, first=0):
        single = mode == "guide-only"
        if not single:
            dst = self.output_view
            self.output_view = self.coarse_output
            try:
                self.encode(encoder, meshes["parts"], "msaa4", query, first)
            finally:
                self.output_view = dst
        base = first if single else first + 2
        stamp = lambda i: ({"query_set": query, "beginning_of_pass_write_index": i,
                            "end_of_pass_write_index": i+1} if query is not None else None)
        source = encoder.begin_render_pass(color_attachments=[
            {"view": self.guide_msaa, "resolve_target": self.low_view, "load_op": "clear",
             "store_op": "discard", "clear_value": (0,0,0,1)},
        ], depth_stencil_attachment={
            "view": self.guide_depth, "depth_load_op": "clear", "depth_store_op": "discard",
            "depth_clear_value": 1.,
        }, timestamp_writes=stamp(base))
        v, i, n = meshes["source"]
        source.set_pipeline(self.raster_msaa)
        source.set_bind_group(0, self.camera_msaa)
        source.set_vertex_buffer(0, v)
        source.set_index_buffer(i, "uint32")
        source.draw_indexed(n, self.instances)
        source.end()
        output = encoder.begin_render_pass(color_attachments=[
            {"view": self.output_view, "load_op": "clear", "store_op": "store",
             "clear_value": (0,0,0,1)},
        ], timestamp_writes=stamp(base+2))
        pipeline, group = self.fusion[mode]
        output.set_pipeline(pipeline)
        output.set_bind_group(0, group)
        output.draw(3)
        output.end()

    def run_guide(self, meshes, mode, frames, capture):
        def encode(encoder, query=None, first=0):
            self.encode_guide(encoder, meshes, mode, query, first)

        stride = 4 if mode == "guide-only" else 6
        return timed_passes(self, encode, stride, frames, capture)


def timed_passes(raster, encode, stride, frames, capture):
    query_count = stride * frames
    queries = raster.device.create_query_set(type="timestamp", count=query_count)
    result = raster.device.create_buffer(
        size=8*query_count, usage=wgpu.BufferUsage.QUERY_RESOLVE | wgpu.BufferUsage.COPY_SRC)
    encoder = raster.device.create_command_encoder()
    for _ in range(8):
        encode(encoder)
    for i in range(frames):
        encode(encoder, queries, i * stride)
    encoder.resolve_query_set(queries, 0, query_count, result, 0)
    commands = encoder.finish()
    start = time.perf_counter()
    raster.queue.submit([commands])
    ticks = np.frombuffer(raster.queue.read_buffer(result), dtype="<u8").reshape(frames, stride)
    wall = (time.perf_counter() - start) * 1000
    result.destroy()
    queries.destroy()
    duration = (ticks[:, -1] - ticks[:, 0]) * raster.timestamp_ns / 1e6
    if (np.any(ticks[:, :-1] > ticks[:, 1:]) or np.any(duration <= 0)
            or (ticks[-1,-1] - ticks[0,0]) * raster.timestamp_ns / 1e6 > 1.02 * wall):
        raise ValueError("Invalid GPU timestamps for the guide pipeline")
    if not capture:
        return duration.tolist(), None
    image = raster.queue.read_texture(
        {"texture": raster.output}, {"bytes_per_row": 4*raster.width, "rows_per_image": raster.height},
        (raster.width, raster.height, 1))
    return duration.tolist(), np.frombuffer(image, dtype=np.uint8).reshape(
        raster.height, raster.width, 4)[..., 0].copy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--meshes", required=True, type=Path)
    parser.add_argument("--shader-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--asset")
    parser.add_argument("--frames", type=int, default=32)
    parser.add_argument("--batches", type=int, default=3)
    args = parser.parse_args()
    if args.frames < 1 or args.batches < 1:
        parser.error("Frames and batches must be positive")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    for name, sha in PINNED.items():
        if digest(args.shader_root / name) != sha:
            raise ValueError("Input differs from the pinned Bevy shader and LUTs")
    width, height = 1280, 720
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = GuidedOffscreen(device, width, height, args.shader_root)
    high = Offscreen(device, 2*width, 2*height, 4, False)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = {"size": [width, height], "adapter": dict(adapter.info), "wgpu": wgpu.__version__,
              "instances": 16, "frames_per_batch": args.frames, "batches": args.batches,
              "manifest_sha256": digest(args.manifest), "script_sha256": digest(Path(__file__)),
              "runtime": {"python": sys.version.split()[0], "numpy": np.__version__,
                          "scikit_image": importlib.metadata.version("scikit-image"),
                          "zstandard": importlib.metadata.version("zstandard"),
                          "platform": platform.platform()},
              "parent_script_sha256": digest(Path(__file__).with_name("bench_bevy_smaa.py")),
              "raster_script_sha256": digest(Path(__file__).with_name("bench_component_gpu.py")),
              "bevy_sha256": PINNED, "timestamp_retries": [], "face_counts": {},
              "assets": {}}
    retries = report["timestamp_retries"]
    for asset, item in manifest["assets"].items():
        if args.asset is not None and asset != args.asset:
            continue
        meshes = {}
        for name in ("source", "qem", "parts"):
            vertices, indices = load_export(
                args.meshes / asset / f"{name}.ply", item["exports"][name])
            meshes[name] = (device.create_buffer_with_data(data=vertices, usage=wgpu.BufferUsage.VERTEX),
                            device.create_buffer_with_data(data=indices, usage=wgpu.BufferUsage.INDEX),
                            len(indices))

        report["face_counts"][asset] = {kind: mesh[2] // 3 for kind, mesh in meshes.items()}

        def run(name, kind, mode, frames, capture, stage):
            label = f"{asset}/{name}/{stage}"
            if kind is None:
                return checked_run(lambda: raster.run_guide(meshes, mode, frames, capture), retries, label)
            timings, image = checked_run(lambda: raster.run(meshes[kind], mode, frames, capture),
                                         retries, label)
            return timings["gpuMs"], image

        samples = {name: {"gpu_ms": []} for name, _, _ in MODES}
        for name, kind, mode in MODES:
            run(name, kind, mode, 8, False, "precondition")
        for batch in range(args.batches):
            offset = (batch * 5) % len(MODES)
            for name, kind, mode in MODES[offset:] + MODES[:offset]:
                runs, _ = run(name, kind, mode, args.frames, False, f"batch-{batch + 1}")
                samples[name]["gpu_ms"].extend(runs)
        _, raw = checked_run(lambda: high.run(meshes["source"], "msaa4", 1, True),
                             retries, f"{asset}/reference/capture")
        ref = linear_gray_to_srgb(raw.reshape(height, 2, width, 2).mean(axis=(1, 3)))
        for name, kind, mode in MODES:
            _, image = run(name, kind, mode, 1, True, "capture")
            if not np.any(image):
                raise ValueError(f"Blank image for {asset}/{name}")
            samples[name]["quality"] = score(ref, linear_gray_to_srgb(image))
            samples[name]["image_sha256"] = hashlib.sha256(image.tobytes()).hexdigest()
        report["assets"][asset] = samples
        print(asset, [(name, round(float(np.median(samples[name]["gpu_ms"])), 3),
                       round(samples[name]["quality"]["flip"], 5))
                      for name in ("guide-only", "guide-copy", "guide-detail")], flush=True)
        for v, i, _ in meshes.values():
            v.destroy()
            i.destroy()
    if not report["assets"]:
        parser.error("No matching assets")
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
