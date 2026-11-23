"""Screen conservative, fixed-view source-triangle reuse in the coarse outline band."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.ndimage import binary_dilation, binary_erosion
from skimage.metrics import structural_similarity
import wgpu

from bench_bevy_smaa import PINNED, SmaaOffscreen
from bench_component_gpu import Offscreen, linear_gray_to_srgb, load_export, projection_matrix, select_adapter
from bench_silhouette_guide_fusion import MODES, checked_run, timed_passes
from gray_flip import gray_flip


CANDIDATE = "sparse-native"
CONTROL_MODES = tuple(entry for entry in MODES if entry[1] is not None)
COMPOSITE = """
@group(0) @binding(0) var coarse: texture_2d<f32>;
@group(0) @binding(1) var fine: texture_2d<f32>;
@group(0) @binding(2) var band: texture_2d<f32>;

@vertex fn vertex_main(@builtin(vertex_index) n: u32) -> @builtin(position) vec4f {
    let p = vec2f(f32((n << 1u) & 2u), f32(n & 2u));
    return vec4f(2.0 * p - 1.0, 0.0, 1.0);
}
@fragment fn fragment_main(@builtin(position) position: vec4f) -> @location(0) vec4f {
    let pixel = vec2i(position.xy);
    if textureLoad(band, pixel, 0).r > 0.0 { return textureLoad(fine, pixel, 0); }
    return textureLoad(coarse, pixel, 0);
}
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def score(ref, image):
    a, b = ref.astype(np.float32) / 255, image.astype(np.float32) / 255
    mse = float(np.mean((a - b)**2, dtype=np.float64))
    return {"psnr_db": -10 * float(np.log10(mse)) if mse else None,
            "ssim": float(structural_similarity(a, b, data_range=1., gaussian_weights=True,
                                               sigma=1.5, use_sample_covariance=False)),
            "flip": gray_flip(ref, image)}


def intersecting_faces(vertices, indices, mask, columns):
    height, width = mask.shape
    points = vertices.reshape(-1, 6)[:, :3]
    matrix = projection_matrix(width, height)
    clip = points.astype(np.float64) @ matrix[:3] + matrix[3]
    w = clip[:, 3]
    outside_depth = (w <= 0) | (clip[:, 2] < 0) | (clip[:, 2] > w)
    projected = np.divide(clip[:, :2], w[:, None], out=np.zeros_like(clip[:, :2]),
                          where=~outside_depth[:, None])
    projected *= [width / (2 * columns), -height / (2 * columns)]
    projected += [width / (2 * columns), height / (2 * columns)]
    triangles = indices.reshape(-1, 3)
    projected = projected[triangles]
    lower = np.floor(projected.min(axis=1)).astype(np.int64) - 1
    upper = np.ceil(projected.max(axis=1)).astype(np.int64) + 2
    keep = outside_depth[triangles].any(axis=1)
    integral = np.pad(mask, ((1, 0), (1, 0))).cumsum(axis=0).cumsum(axis=1)
    for row in range(columns):
        for column in range(columns):
            # Vertex shader places row zero at the bottom of the framebuffer.
            offset = [column * (width // columns), (columns - 1 - row) * (height // columns)]
            x0, y0 = np.clip(lower + offset, 0, [width, height]).T
            x1, y1 = np.clip(upper + offset, 0, [width, height]).T
            keep |= integral[y1, x1] - integral[y0, x1] - integral[y1, x0] + integral[y0, x0] > 0
    return np.ascontiguousarray(triangles[keep].ravel())


class SparseOffscreen(SmaaOffscreen):
    def __init__(self, device, width, height, shader_root):
        super().__init__(device, width, height, shader_root)
        size = width, height, 1
        self.coarse_output = device.create_texture(
            size=size, format="rgba8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.RENDER_ATTACHMENT).create_view()
        self.fine_output = device.create_texture(
            size=size, format="rgba8unorm",
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.RENDER_ATTACHMENT).create_view()
        self.band = device.create_texture(size=size, format="r8unorm",
                                        usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
        module = device.create_shader_module(code=COMPOSITE)
        self.composite = device.create_render_pipeline(
            layout="auto", vertex={"module": module, "entry_point": "vertex_main"},
            fragment={"module": module, "entry_point": "fragment_main",
                      "targets": [{"format": "rgba8unorm"}]})
        self.composite_bind = device.create_bind_group(
            layout=self.composite.get_bind_group_layout(0), entries=[
                {"binding": 0, "resource": self.coarse_output},
                {"binding": 1, "resource": self.fine_output},
                {"binding": 2, "resource": self.band.create_view()},
            ])

    def prepare(self, meshes, vertices, indices, coarse):
        start = time.perf_counter()
        foreground = coarse > 0
        mask = (binary_dilation(foreground, iterations=2)
                & ~binary_erosion(foreground, iterations=2, border_value=1))
        retained = intersecting_faces(vertices, indices, mask, 4)
        if retained.size == 0:
            raise ValueError("The outline band did not retain any source faces")
        cached = mask.astype(np.uint8) * 255
        prep_ms = 1000 * (time.perf_counter() - start)

        start = time.perf_counter()
        v, _, _ = meshes["source"]
        buf = self.device.create_buffer_with_data(data=retained, usage=wgpu.BufferUsage.INDEX)
        meshes["sparse"] = v, buf, len(retained)
        self.queue.write_texture({"texture": self.band}, cached,
                                 {"bytes_per_row": self.width, "rows_per_image": self.height},
                                 (self.width, self.height, 1))
        self.queue.on_submitted_work_done_sync()
        upload_ms = 1000 * (time.perf_counter() - start)
        costs = {"prep_ms": prep_ms, "upload_wait_ms": upload_ms,
                 "mask_pixels": int(mask.sum()), "mask_bytes": cached.nbytes,
                 "retained_faces": len(retained) // 3, "retained_index_bytes": retained.nbytes,
                 "mask_sha256": sha(cached.tobytes()), "index_sha256": sha(retained.tobytes())}
        return mask, costs

    def encode_sparse(self, encoder, meshes, query=None, first=0):
        destination = self.output_view
        try:
            self.output_view = self.coarse_output
            self.encode(encoder, meshes["parts"], "msaa4", query, first)
            self.output_view = self.fine_output
            self.encode(encoder, meshes["sparse"], "msaa4", query, first + 2)
        finally:
            self.output_view = destination
        timestamps = ({"query_set": query, "beginning_of_pass_write_index": first + 4,
                       "end_of_pass_write_index": first + 5} if query is not None else None)
        output = encoder.begin_render_pass(color_attachments=[
            {"view": self.output_view, "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)},
        ], timestamp_writes=timestamps)
        output.set_pipeline(self.composite)
        output.set_bind_group(0, self.composite_bind)
        output.draw(3)
        output.end()

    def run_sparse(self, meshes, frames, capture):
        def encode(encoder, query=None, first=0):
            self.encode_sparse(encoder, meshes, query, first)

        return timed_passes(self, encode, 6, frames, capture)


def evaluate(raster, high, mesh_dir, asset, item, baseline, frames, batches, retries):
    meshes = {}
    for kind in ("qem", "parts", "source"):
        vertices, indices = load_export(mesh_dir / f"{kind}.ply", item["exports"][kind])
        meshes[kind] = (raster.device.create_buffer_with_data(data=vertices, usage=wgpu.BufferUsage.VERTEX),
                        raster.device.create_buffer_with_data(data=indices, usage=wgpu.BufferUsage.INDEX),
                        len(indices))

    def run(name, kind, mode, n, capture, stage):
        label = f"{asset}/{name}/{stage}"
        if name == CANDIDATE:
            return checked_run(lambda: raster.run_sparse(meshes, n, capture), retries, label)
        stats, raw = checked_run(lambda: raster.run(meshes[kind], mode, n, capture), retries, label)
        return stats["gpuMs"], raw

    start = time.perf_counter()
    _, coarse = run("parts-msaa4", "parts", "msaa4", 1, True, "prepare")
    coarse_capture_ms = 1000 * (time.perf_counter() - start)
    mask, costs = raster.prepare(meshes, vertices, indices, coarse)
    costs["coarse_capture_wall_ms"] = coarse_capture_ms
    costs["source_faces"] = len(indices) // 3
    costs["source_vertex_bytes"] = vertices.nbytes
    settings = CONTROL_MODES + ((CANDIDATE, None, None),)
    rows = {name: {"gpu_ms": []} for name, _, _ in settings}
    for name, kind, mode in settings:
        run(name, kind, mode, 8, False, "precondition")
    for batch in range(batches):
        offset = (3 * batch) % len(settings)
        for name, kind, mode in settings[offset:] + settings[:offset]:
            samples, _ = run(name, kind, mode, frames, False, f"batch-{batch + 1}")
            rows[name]["gpu_ms"].extend(samples)

    _, ref_hi = checked_run(lambda: high.run(meshes["source"], "msaa4", 1, True),
                            retries, f"{asset}/reference")
    ref = linear_gray_to_srgb(ref_hi.reshape(raster.height, 2, raster.width, 2).mean(axis=(1, 3)))
    for name, kind, mode in settings:
        _, raw = run(name, kind, mode, 1, True, "capture")
        rows[name]["image_sha256"] = sha(raw.tobytes())
        rows[name]["quality"] = score(ref, linear_gray_to_srgb(raw))
        if name in baseline:
            original = baseline[name]
            if (rows[name]["image_sha256"] != original["image_sha256"] or any(
                    rows[name]["quality"][metric] != original["quality"][metric]
                    for metric in ("psnr_db", "ssim"))):
                raise ValueError(f"Shared capture or unchanged metrics differ for {asset}/{name}")
            rows[name]["flip_difference_from_native_1_7"] = (
                rows[name]["quality"]["flip"] - original["quality"]["flip"])
        if name == "source-msaa4":
            fine = raw
        if name == CANDIDATE:
            candidate = raw

    mismatched = int(np.count_nonzero(candidate != np.where(mask, fine, coarse)))
    costs["pixels_different_from_full_guide_copy"] = mismatched
    if mismatched:
        raise ValueError(f"{asset}: {mismatched} pixels differ from the full guide copy")
    for _, i, _ in meshes.values():
        i.destroy()
    for kind in ("qem", "parts", "source"):
        meshes[kind][0].destroy()
    return {"costs": costs, "modes": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--meshes", required=True, type=Path)
    parser.add_argument("--shader-root", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--asset")
    parser.add_argument("--frames", type=int, default=32)
    parser.add_argument("--batches", type=int, default=3)
    args = parser.parse_args()
    if args.frames < 1 or args.batches < 1:
        parser.error("Frames and batches must be positive")
    for name, expected in PINNED.items():
        if sha((args.shader_root / name).read_bytes()) != expected:
            raise ValueError(f"Changed Bevy input {name}")
    manifest_data = args.manifest.read_bytes()
    manifest = json.loads(manifest_data)
    baseline_data = args.baseline.read_bytes()
    baseline = json.loads(baseline_data)
    if baseline["manifest_sha256"] != sha(manifest_data):
        raise ValueError("Geometry differs from the guide benchmark")
    width, height = baseline["size"]
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    if dict(adapter.info) != baseline["adapter"] or wgpu.__version__ != baseline["wgpu"]:
        raise ValueError("Adapter or wgpu differs from the guide benchmark")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = SparseOffscreen(device, width, height, args.shader_root)
    high = Offscreen(device, width * 2, height * 2, 4, False)
    names = [Path(__file__).name, "bench_silhouette_guide_fusion.py",
             "bench_bevy_smaa.py", "bench_component_gpu.py", "gray_flip.py"]
    report = {"manifest_sha256": sha(manifest_data), "baseline_sha256": sha(baseline_data),
              "script_sha256": {name: sha(Path(__file__).with_name(name).read_bytes()) for name in names},
              "bevy_sha256": PINNED, "flip_backend": "achromatic CPU LDR-FLIP at 67 ppd",
              "size": [width, height], "adapter": dict(adapter.info),
              "wgpu": wgpu.__version__, "instances": raster.instances, "frames_per_batch": args.frames,
              "batches": args.batches, "timestamp_retries": [], "assets": {}}
    for asset, controls in baseline["assets"].items():
        if args.asset is not None and asset != args.asset:
            continue
        result = evaluate(raster, high, args.meshes / asset, asset, manifest["assets"][asset],
                          controls, args.frames, args.batches, report["timestamp_retries"])
        report["assets"][asset] = result
        row = result["modes"][CANDIDATE]
        print(asset, result["costs"]["retained_faces"], round(float(np.median(row["gpu_ms"])), 3),
              round(row["quality"]["flip"], 6), flush=True)
    if not report["assets"]:
        parser.error("No matching assets")
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
