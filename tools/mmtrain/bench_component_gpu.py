"""Measure native offscreen raster and 2x reconstruction on a named WebGPU adapter."""

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import sys
import time

import numpy as np
import wgpu
from wgpu.backends.wgpu_native import lib
from skimage.metrics import structural_similarity


RASTER_SHADER = """
struct VertexOut {
    @builtin(position) clip: vec4f,
    @location(0) light: f32,
};
@group(0) @binding(0) var<uniform> projection: mat4x4f;
override columns: u32 = 1u;

@vertex fn vertex_main(@location(0) point: vec3f, @location(1) normal: vec3f,
                       @builtin(instance_index) instance: u32) -> VertexOut {
    let light = 0.20 + 0.75 * clamp(dot(normal, vec3f(0.36, 0.80, 0.48)), 0.0, 1.0);
    let clip = projection * vec4f(point, 1.0);
    let cell = vec2f(f32(instance % columns), f32(instance / columns));
    let center = (2.0 * cell + 1.0) / f32(columns) - 1.0;
    return VertexOut(vec4f(clip.xy / f32(columns) + center * clip.w, clip.zw), light);
}
@fragment fn fragment_main(in: VertexOut) -> @location(0) vec4f {
    return vec4f(vec3f(in.light), 1.0);
}
"""


UPSCALE_SHADER = """
@group(0) @binding(0) var low: texture_2d<f32>;
@group(0) @binding(1) var linear_edge: sampler;

@vertex fn full_screen(@builtin(vertex_index) index: u32) -> @builtin(position) vec4f {
    let corner = vec2f(f32((index << 1u) & 2u), f32(index & 2u));
    return vec4f(corner * 2.0 - 1.0, 0.0, 1.0);
}
@fragment fn linear(@builtin(position) position: vec4f) -> @location(0) vec4f {
    let dims = vec2f(textureDimensions(low));
    return textureSampleLevel(low, linear_edge, position.xy / (2.0 * dims), 0.0);
}
fn cubic_weights(t: f32) -> vec4f {
    let t2 = t * t;
    let t3 = t2 * t;
    return vec4f(-0.5*t + t2 - 0.5*t3, 1.0 - 2.5*t2 + 1.5*t3,
                 0.5*t + 2.0*t2 - 1.5*t3, -0.5*t2 + 0.5*t3);
}
fn cubic_row(x: vec3f, y: f32, weights: vec3f) -> vec4f {
    return weights.x * textureSampleLevel(low, linear_edge, vec2f(x.x, y), 0.0)
         + weights.y * textureSampleLevel(low, linear_edge, vec2f(x.y, y), 0.0)
         + weights.z * textureSampleLevel(low, linear_edge, vec2f(x.z, y), 0.0);
}
@fragment fn cubic(@builtin(position) position: vec4f) -> @location(0) vec4f {
    let dims = vec2f(textureDimensions(low));
    let pixel = vec2u(position.xy);
    let odd = (pixel & vec2u(1u)) != vec2u(0u);
    let base = vec2f(pixel / vec2u(2u)) + select(vec2f(-1.0), vec2f(0.0), odd);
    // 2x samples have only the 1/4 and 3/4 phases. Each phase combines its
    // positive central weights using the linear sampler.
    let near = select(vec2f(-0.0234375), vec2f(-0.0703125), odd);
    let far = select(vec2f(-0.0703125), vec2f(-0.0234375), odd);
    let middle = vec2f(1.09375);
    let offset = select(vec2f(0.7928571429), vec2f(0.2071428571), odd);
    let a = (base - 0.5) / dims;
    let b = (base + 0.5 + offset) / dims;
    let c = (base + 2.5) / dims;
    let x = vec3f(a.x, b.x, c.x);
    let wx = vec3f(near.x, middle.x, far.x);
    return near.y * cubic_row(x, a.y, wx) + middle.y * cubic_row(x, b.y, wx)
         + far.y * cubic_row(x, c.y, wx);
}
@fragment fn cubic16(@builtin(position) position: vec4f) -> @location(0) vec4f {
    let dims = vec2f(textureDimensions(low));
    let sample_position = position.xy * 0.5 - 0.5;
    let base = floor(sample_position);
    let phase = fract(sample_position);
    let wx = cubic_weights(phase.x);
    let wy = cubic_weights(phase.y);
    var color = vec4f(0.0);
    for (var row = 0u; row < 4u; row++) {
        for (var col = 0u; col < 4u; col++) {
            let coord = (base + vec2f(f32(col), f32(row)) - 0.5) / dims;
            color += wx[col] * wy[row] * textureSampleLevel(low, linear_edge, coord, 0.0);
        }
    }
    return color;
}
"""


MODES = (
    ("source", None),
    ("qem", None),
    ("whole", None),
    ("parts", None),
    ("source", "msaa4"),
    ("qem", "msaa4"),
    ("whole", "msaa4"),
    ("parts", "msaa4"),
    ("source", "linear"),
    ("qem", "linear"),
    ("whole", "linear"),
    ("parts", "linear"),
    ("source", "cubic"),
    ("qem", "cubic"),
    ("whole", "cubic"),
    ("parts", "cubic"),
)


def load_export(path, expected):
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected["sha256"]:
        raise ValueError(f"Mesh hash changed: {path}")
    header, binary = payload.split(b"end_header\n", 1)
    vertex_count = expected["vertices"]
    face_count = expected["faces"]
    if (b"format binary_little_endian 1.0" not in header
            or len(binary) != vertex_count * 24 + face_count * 13):
        raise ValueError(f"Unsupported PLY layout: {path}")
    vertices = np.frombuffer(binary, dtype="<f4", count=vertex_count * 6)
    record = np.dtype([("count", "u1"), ("index", "<u4", (3,))])
    faces = np.frombuffer(binary, dtype=record, offset=vertex_count * 24)
    indices = np.ascontiguousarray(faces["index"]).ravel()
    if not np.all(faces["count"] == 3) or indices.max() >= vertex_count:
        raise ValueError(f"Invalid triangle indices: {path}")
    return vertices, indices


def projection_matrix(width, height, eye=(1.3, 0.55, 2.8)):
    eye = np.asarray(eye)
    forward = -eye / np.linalg.norm(eye)
    right = np.cross(forward, (0, 1, 0))
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    camera = np.eye(4)
    camera[:3, :3] = (right, up, forward)
    camera[:3, 3] = -camera[:3, :3] @ eye
    focal = 1.0 / math.tan(math.radians(40.0) * 0.5)
    near, far = 0.05, 25.0
    transform = np.array(((focal * height / width, 0, 0, 0), (0, focal, 0, 0),
                          (0, 0, far / (far - near), -far * near / (far - near)), (0, 0, 1, 0)))
    return np.ascontiguousarray((transform @ camera).T, dtype=np.float32)


def linear_gray_to_srgb(image):
    linear = image.astype(np.float64) / 255.0
    srgb = np.where(linear <= 0.0031308, 12.92 * linear,
                    1.055 * np.power(linear, 1.0 / 2.4) - 0.055)
    return np.clip(np.rint(srgb * 255.0), 0, 255).astype(np.uint8)


def select_adapter(device_name, backend):
    adapters = list(wgpu.gpu.enumerate_adapters_sync())
    for adapter in adapters:
        info = adapter.info
        if (device_name.casefold() in info["device"].casefold()
                and info["backend_type"].casefold() == backend.casefold()
                and info["adapter_type"] in ("IntegratedGPU", "DiscreteGPU")
                and "timestamp-query" in adapter.features):
            return adapter
    raise RuntimeError(f"Timestamp-capable hardware adapter not found: {[dict(a.info) for a in adapters]}")


class Offscreen:
    def __init__(self, device, width, height, columns, audit):
        self.device = device
        self.width, self.height = width, height
        self.queue = device.queue
        self.instances = columns ** 2
        self.timestamp_ns = lib.wgpuQueueGetTimestampPeriod(self.queue._internal)
        if not math.isfinite(self.timestamp_ns) or self.timestamp_ns <= 0:
            raise RuntimeError(f"Invalid native GPU timestamp period: {self.timestamp_ns}")
        color_usage = wgpu.TextureUsage.RENDER_ATTACHMENT
        self.output = device.create_texture(size=(width, height, 1), format="rgba8unorm",
                                            usage=color_usage | wgpu.TextureUsage.COPY_SRC)
        self.output_view = self.output.create_view()
        self.output_msaa = device.create_texture(
            size=(width, height, 1), sample_count=4, format="rgba8unorm",
            usage=color_usage)
        self.output_msaa_view = self.output_msaa.create_view()
        self.low = device.create_texture(size=(width // 2, height // 2, 1), format="rgba8unorm",
                                         usage=color_usage | wgpu.TextureUsage.TEXTURE_BINDING)
        self.low_view = self.low.create_view()
        self.depth = device.create_texture(size=(width, height, 1), format="depth32float",
                                           usage=color_usage).create_view()
        self.depth_msaa = device.create_texture(
            size=(width, height, 1), sample_count=4, format="depth32float",
            usage=color_usage).create_view()
        self.low_depth = device.create_texture(size=(width // 2, height // 2, 1),
                                               format="depth32float", usage=color_usage).create_view()
        self.configure_raster(columns)
        module = device.create_shader_module(code=UPSCALE_SHADER)
        sampler = device.create_sampler(mag_filter="linear", min_filter="linear")
        self.upscale = {}
        for mode in (("linear", "cubic", "cubic16") if audit else ("linear", "cubic")):
            pipeline = device.create_render_pipeline(
                layout="auto", vertex={"module": module, "entry_point": "full_screen"},
                fragment={"module": module, "entry_point": mode,
                          "targets": [{"format": self.output.format}]})
            binding = device.create_bind_group(layout=pipeline.get_bind_group_layout(0), entries=[
                {"binding": 0, "resource": self.low_view}, {"binding": 1, "resource": sampler}])
            self.upscale[mode] = (pipeline, binding)

    def configure_raster(self, columns):
        device = self.device
        width, height = self.width, self.height
        module = device.create_shader_module(code=RASTER_SHADER)
        self.raster = device.create_render_pipeline(
            layout="auto",
            vertex={"module": module, "entry_point": "vertex_main",
                    "constants": {"columns": columns}, "buffers": [{
                "array_stride": 24, "attributes": [
                    {"format": "float32x3", "offset": 0, "shader_location": 0},
                    {"format": "float32x3", "offset": 12, "shader_location": 1}]}]},
            fragment={"module": module, "entry_point": "fragment_main",
                      "targets": [{"format": self.output.format}]},
            depth_stencil={"format": "depth32float", "depth_write_enabled": True,
                           "depth_compare": "less"},
            primitive={"topology": "triangle-list", "cull_mode": "none"})
        self.raster_msaa = device.create_render_pipeline(
            layout="auto",
            vertex={"module": module, "entry_point": "vertex_main",
                    "constants": {"columns": columns}, "buffers": [{
                "array_stride": 24, "attributes": [
                    {"format": "float32x3", "offset": 0, "shader_location": 0},
                    {"format": "float32x3", "offset": 12, "shader_location": 1}]}]},
            fragment={"module": module, "entry_point": "fragment_main",
                      "targets": [{"format": self.output.format}]},
            depth_stencil={"format": "depth32float", "depth_write_enabled": True,
                           "depth_compare": "less"},
            primitive={"topology": "triangle-list", "cull_mode": "none"},
            multisample={"count": 4})
        uniform = device.create_buffer_with_data(data=projection_matrix(width, height),
                                                usage=wgpu.BufferUsage.UNIFORM)
        self.camera = device.create_bind_group(layout=self.raster.get_bind_group_layout(0),
                                               entries=[{"binding": 0, "resource": {"buffer": uniform}}])
        self.camera_msaa = device.create_bind_group(
            layout=self.raster_msaa.get_bind_group_layout(0),
            entries=[{"binding": 0, "resource": {"buffer": uniform}}])

    def draw_geometry(self, rendering, mesh, msaa):
        positions, indices, count = mesh
        rendering.set_pipeline(self.raster_msaa if msaa else self.raster)
        rendering.set_bind_group(0, self.camera_msaa if msaa else self.camera)
        rendering.set_vertex_buffer(0, positions)
        rendering.set_index_buffer(indices, "uint32")
        rendering.draw_indexed(count, self.instances)

    def encode(self, encoder, mesh, mode, queries=None, index=0):
        upscaling = mode in self.upscale
        msaa = mode == "msaa4"
        first = (self.low_view if upscaling else
                 self.output_msaa_view if msaa else self.output_view)
        depth = self.low_depth if upscaling else self.depth_msaa if msaa else self.depth
        stamps = ({"query_set": queries, "beginning_of_pass_write_index": index,
                   "end_of_pass_write_index": index+1} if queries is not None else None)
        color_attachment = {"view": first, "load_op": "clear", "store_op": "store",
                            "clear_value": (0, 0, 0, 1)}
        if msaa:
            color_attachment["resolve_target"] = self.output_view
        rendering = encoder.begin_render_pass(
            color_attachments=[color_attachment],
            depth_stencil_attachment={"view": depth, "depth_load_op": "clear",
                                      "depth_store_op": "discard", "depth_clear_value": 1.0},
            timestamp_writes=stamps)
        self.draw_geometry(rendering, mesh, msaa)
        rendering.end()
        if upscaling:
            if stamps is not None:
                stamps = {"query_set": queries, "beginning_of_pass_write_index": index+2,
                          "end_of_pass_write_index": index+3}
            up = encoder.begin_render_pass(
                color_attachments=[{"view": self.output_view, "load_op": "clear", "store_op": "store",
                                    "clear_value": (0, 0, 0, 1)}], timestamp_writes=stamps)
            pipeline, binding = self.upscale[mode]
            up.set_pipeline(pipeline)
            up.set_bind_group(0, binding)
            up.draw(3)
            up.end()

    def run(self, mesh, mode, frames, capture):
        upscaling = mode in self.upscale
        stride = 4 if upscaling else 2
        count = stride * frames
        queries = self.device.create_query_set(type="timestamp", count=count)
        result = self.device.create_buffer(size=count*8,
                                           usage=wgpu.BufferUsage.QUERY_RESOLVE | wgpu.BufferUsage.COPY_SRC)
        encoder = self.device.create_command_encoder()
        for _ in range(8):
            self.encode(encoder, mesh, mode)
        for frame in range(frames):
            self.encode(encoder, mesh, mode, queries, frame*stride)
        encoder.resolve_query_set(queries, 0, count, result, 0)
        commands = encoder.finish()
        started = time.perf_counter()
        self.queue.submit([commands])
        ticks = np.frombuffer(self.queue.read_buffer(result), dtype="<u8").reshape(frames, stride)
        wall_ms = (time.perf_counter() - started) * 1000
        if np.any(ticks[:, 0] >= ticks[:, -1]) or np.any(ticks[:, 0] > ticks[:, 1]):
            raise RuntimeError("Invalid GPU timestamp ordering")
        ms_per_tick = self.timestamp_ns / 1e6
        duration = (ticks[:, -1] - ticks[:, 0]) * ms_per_tick
        timestamp_span = (ticks[-1, -1] - ticks[0, 0]) * ms_per_tick
        if timestamp_span > wall_ms * 1.02:
            raise RuntimeError("GPU interval exceeds synchronized wall time")
        timing = {"rasterMs": ((ticks[:, 1] - ticks[:, 0]) * ms_per_tick).tolist(),
                  "gpuMs": duration.tolist(), "submitAndWaitMs": wall_ms}
        if upscaling:
            if np.any(ticks[:, 2] > ticks[:, 3]):
                raise RuntimeError("Invalid reconstruction timestamp ordering")
            timing["upscaleMs"] = ((ticks[:, 3] - ticks[:, 2]) * ms_per_tick).tolist()
        result.destroy()
        queries.destroy()
        gray = None
        if capture:
            image = self.queue.read_texture(
                {"texture": self.output},
                {"bytes_per_row": 4*self.width, "rows_per_image": self.height},
                (self.width, self.height, 1))
            gray = np.frombuffer(image, dtype=np.uint8).reshape(self.height, self.width, 4)[..., 0].copy()
            if not np.any(gray):
                raise RuntimeError("Offscreen rendering produced a blank frame")
        return timing, gray


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meshes", type=Path)
    parser.add_argument("--motion-reference", type=Path, required=True)
    parser.add_argument("--asset", nargs="+", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--device", default="Iris(R) Xe")
    parser.add_argument("--backend", choices=("D3D12", "Vulkan"), default="D3D12")
    parser.add_argument("--size", choices=("640x360", "1280x720", "1920x1080"), default="1280x720")
    parser.add_argument("--frames", type=int, choices=(16, 48, 96), default=48)
    parser.add_argument("--repeats", type=int, choices=(1, 3, 5), default=3)
    parser.add_argument("--grid", type=int, choices=(1, 4), default=1)
    parser.add_argument("--audit-filter", action="store_true")
    args = parser.parse_args()
    width, height = (int(dimension) for dimension in args.size.split("x"))
    adapter = select_adapter(args.device, args.backend)
    print(dict(adapter.info), flush=True)
    gpu = Offscreen(adapter.request_device_sync(required_features=["timestamp-query"]),
                    width, height, args.grid, args.audit_filter)
    manifest = json.loads(args.motion_reference.read_text(encoding="utf-8"))
    results = {}
    for name in args.asset:
        metadata = manifest["assets"][name]
        meshes = {}
        for kind in ("source", "qem", "whole", "parts"):
            expected = metadata["exports"][kind]
            if kind != "source" and expected["faces"] != metadata["faces"]:
                raise ValueError(f"Unequal reduced-mesh face counts: {name}")
            vertices, indices = load_export(args.meshes / name / f"{kind}.ply", expected)
            gpu_vertices = gpu.device.create_buffer_with_data(data=vertices, usage=wgpu.BufferUsage.VERTEX)
            gpu_indices = gpu.device.create_buffer_with_data(data=indices, usage=wgpu.BufferUsage.INDEX)
            meshes[kind] = (gpu_vertices, gpu_indices, len(indices))
        modes = {}
        captures = {}
        raw_captures = {}
        mode_list = (*MODES, ("parts", "cubic16")) if args.audit_filter else MODES
        for repetition in range(args.repeats):
            offset = (repetition * max(1, len(mode_list) // args.repeats)) % len(mode_list)
            for kind, mode in mode_list[offset:] + mode_list[:offset]:
                timing, image = gpu.run(meshes[kind], mode, args.frames, repetition == 0)
                label = f"{kind}-{mode or 'native'}"
                row = modes.setdefault(label, {"faces": meshes[kind][2] // 3})
                row.setdefault("submitAndWaitMs", []).append(timing.pop("submitAndWaitMs"))
                for metric, samples in timing.items():
                    row.setdefault(metric, []).extend(samples)
                if image is not None:
                    raw_captures[label] = image
                    srgb_image = linear_gray_to_srgb(image)
                    captures[label] = srgb_image
                    if label == "source-native":
                        references = {"native": srgb_image}
                    if label == "source-msaa4":
                        references["msaa4"] = srgb_image
                    reference_key = "msaa4" if mode == "msaa4" else "native"
                    if reference_key not in references:
                        raise ValueError(f"Missing {reference_key} source reference before {label}")
                    delta = (srgb_image.astype(np.float32) - references[reference_key]) / 255.0
                    row["mse"] = float(np.mean(np.square(delta, dtype=np.float64)))
                    if label == "parts-cubic":
                        combined_cubic = image
                    if label == "parts-cubic16":
                        gap = int(np.abs(combined_cubic.astype(np.int16) - image).max())
                        if gap > 2:
                            raise ValueError(f"Nine-tap bicubic and direct kernel differ by {gap}")
                        row["maxDifferenceCodeValues"] = gap
        high_quality_reference = captures["source-msaa4"]
        for label, image in captures.items():
            delta = (image.astype(np.float32) - high_quality_reference) / 255.0
            mse = float(np.mean(np.square(delta, dtype=np.float64)))
            modes[label]["mse_vs_source_msaa4"] = mse
            modes[label]["psnr_db_vs_source_msaa4"] = (
                None if mse == 0 else float(-10.0 * math.log10(mse)))
            modes[label]["ssim_vs_source_msaa4"] = float(structural_similarity(
                high_quality_reference, image, data_range=255))
            modes[label]["capture_sha256"] = hashlib.sha256(
                raw_captures[label].tobytes()).hexdigest()
        for label, row in modes.items():
            print(name, label, "p50/p95 ms",
                  np.round(np.percentile(row["gpuMs"], [50, 95]), 3).tolist(), flush=True)
        results[name] = modes
        for v, i, _ in meshes.values():
            v.destroy()
            i.destroy()
    document = {"adapter": dict(adapter.info), "timestampPeriodNs": gpu.timestamp_ns,
                "size": [width, height], "instances": gpu.instances,
                "framesPerBatch": args.frames, "batchesPerMode": args.repeats,
                "warmupFramesPerBatch": 8,
                "qualityReference": "full source mesh, same camera and 4x MSAA",
                "captureEncoding": "linear-light rgba8unorm capture; PSNR/SSIM convert grayscale to 8-bit sRGB using the IEC 61966-2-1 transfer",
                "mseField": "mse_vs_source_msaa4 is total sRGB image error vs shared high-quality reference; mse is error vs same-AA full source",
                "environment": {
                    "python": sys.version,
                    "platform": platform.platform(),
                    "wgpu": importlib.metadata.version("wgpu"),
                    "numpy": importlib.metadata.version("numpy"),
                    "scikit_image": importlib.metadata.version("scikit-image"),
                },
                "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "motion_reference_sha256": hashlib.sha256(
                    args.motion_reference.read_bytes()).hexdigest(),
                "input_mesh_sha256": {
                    asset: {kind: metadata["exports"][kind]["sha256"]
                            for kind in ("source", "qem", "whole", "parts")}
                    for asset, metadata in manifest["assets"].items()
                    if asset in results
                },
                "assets": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
