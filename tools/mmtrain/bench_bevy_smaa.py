"""Compare the Bevy SMAA shader against MSAA and upscaling in the desktop harness."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import struct
import time

import numpy as np
from skimage.metrics import structural_similarity
import wgpu
import zstandard

from bench_component_gpu import Offscreen, linear_gray_to_srgb, load_export, select_adapter


PINNED = {
    "smaa.wgsl": "d0a08d2394941c1b8a075aa508da641e33ee5985323642b8ac27ad16d1e7cd05",
    "SMAAAreaLUT.ktx2": "53e544bc7d3d3e334b82a3ad02e55d99218347c42438268dfcf989258c788c5c",
    "SMAASearchLUT.ktx2": "f72fcf3b139c93aca983d8ac170bbfe1281411bf376f21b5e2be524d9490d921",
}
STAGES = (
    ("SMAA_EDGE_DETECTION", "edge_detection_vertex_main", "luma_edge_detection_fragment_main"),
    ("SMAA_BLENDING_WEIGHT_CALCULATION", "blending_weight_calculation_vertex_main",
     "blending_weight_calculation_fragment_main"),
    ("SMAA_NEIGHBORHOOD_BLENDING", "neighborhood_blending_vertex_main",
     "neighborhood_blending_fragment_main"),
)


def specialize(shader, stage):
    """Apply the Bevy shader definitions for one medium preset pipeline."""
    definitions = {stage, "SMAA_PRESET_MEDIUM"}
    frames, output = [], []
    active = True
    for text in shader.splitlines():
        line = text.strip()
        if not line.startswith("#"):
            if active:
                output.append(text)
            continue
        tokens = line[1:].split("//", 1)[0].split()
        if tokens[0] in ("ifdef", "ifndef"):
            yes = (tokens[1] in definitions) == (tokens[0] == "ifdef")
            frames.append((active, yes))
            active = active and yes
        elif tokens[0] == "else":
            parent, visited = frames[-1]
            condition = len(tokens) == 1 or tokens[2] in definitions
            active = parent and not visited and condition
            frames[-1] = parent, visited or condition
        elif tokens[0] == "endif":
            active, _ = frames.pop()
        elif tokens[0] == "define":
            if active:
                definitions.add(tokens[1])
        else:
            raise ValueError(f"Unsupported shader directive: {line}")
    if frames:
        raise ValueError("Unclosed shader conditional")
    return "\n".join(output)


def lut_texture(device, path):
    payload = path.read_bytes()
    if payload[:12] != b"\xabKTX 20\xbb\r\n\x1a\n":
        raise ValueError(f"Invalid KTX2 header: {path}")
    vk, type_size, w, h, d, layers, faces, levels, codec = struct.unpack_from("<9I", payload, 12)
    if (type_size, d, layers, faces, levels, codec) != (1, 0, 0, 1, 1, 2):
        raise ValueError("Expected one Zstd-compressed unorm LUT level")
    fmt, channels = {9: ("r8unorm", 1), 16: ("rg8unorm", 2)}[vk]
    offset, count, size = struct.unpack_from("<QQQ", payload, 80)
    raw = zstandard.ZstdDecompressor().decompress(payload[offset:offset + count],
                                                  max_output_size=size)
    if len(raw) != size or size != w * h * channels:
        raise ValueError("Decoded LUT dimensions differ from the header")
    texture = device.create_texture(size=(w, h, 1), format=fmt,
                                    usage=wgpu.TextureUsage.COPY_DST | wgpu.TextureUsage.TEXTURE_BINDING)
    device.queue.write_texture({"texture": texture}, raw,
                               {"bytes_per_row": w * channels, "rows_per_image": h}, (w, h, 1))
    return texture.create_view()


class SmaaOffscreen(Offscreen):
    def __init__(self, device, width, height, shader_root):
        super().__init__(device, width, height, 4, False)
        usage = wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.TEXTURE_BINDING
        self.smaa_source = device.create_texture(size=(width, height, 1),
                                                  format="rgba8unorm", usage=usage).create_view()
        edges = device.create_texture(size=(width, height, 1), format="rg8unorm",
                                      usage=usage).create_view()
        weights = device.create_texture(size=(width, height, 1), format="rgba8unorm",
                                        usage=usage).create_view()
        stencil_texture = device.create_texture(
            size=(width, height, 1), format="stencil8", usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
        self.stencil = stencil_texture.create_view()
        sampler = device.create_sampler(mag_filter="linear", min_filter="linear")
        area = lut_texture(device, shader_root / "SMAAAreaLUT.ktx2")
        search = lut_texture(device, shader_root / "SMAASearchLUT.ktx2")
        info = device.create_buffer_with_data(
            data=np.asarray([1/width, 1/height, width, height], dtype=np.float32),
            usage=wgpu.BufferUsage.UNIFORM)
        common_layout = device.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": wgpu.ShaderStage.FRAGMENT, "texture": {}},
            {"binding": 1, "visibility": wgpu.ShaderStage.FRAGMENT | wgpu.ShaderStage.VERTEX,
             "buffer": {"type": "uniform"}},
        ])
        self.common = device.create_bind_group(layout=common_layout, entries=[
            {"binding": 0, "resource": self.smaa_source}, {"binding": 1, "resource": {"buffer": info}},
        ])
        self.smaa_passes = []
        shader = (shader_root / "smaa.wgsl").read_text(encoding="utf-8")
        resources = ((sampler,), (edges, sampler, search, area), (weights, sampler))
        for i, ((stage, vertex, fragment), dst, textures) in enumerate(
                zip(STAGES, (edges, weights, self.output_view), resources)):
            layout = device.create_bind_group_layout(entries=[
                {"binding": j, "visibility": wgpu.ShaderStage.FRAGMENT,
                 **({"sampler": {"type": "filtering"}} if entry is sampler else {"texture": {}})}
                for j, entry in enumerate(textures)])
            group = device.create_bind_group(layout=layout, entries=[
                {"binding": j, "resource": entry} for j, entry in enumerate(textures)])
            module = device.create_shader_module(code=specialize(shader, stage))
            kwargs = {}
            if i < 2:
                face = {"compare": "always" if i == 0 else "equal",
                        "pass_op": "replace" if i == 0 else "keep"}
                kwargs["depth_stencil"] = {
                    "format": "stencil8", "stencil_front": face, "stencil_back": face,
                    "stencil_read_mask": 1, "stencil_write_mask": 1,
                }
            pipeline = device.create_render_pipeline(
                layout=device.create_pipeline_layout(bind_group_layouts=[common_layout, layout]),
                vertex={"module": module, "entry_point": vertex},
                fragment={"module": module, "entry_point": fragment,
                          "targets": [{"format": "rg8unorm" if i == 0 else "rgba8unorm"}]}, **kwargs)
            self.smaa_passes.append((dst, pipeline, group))

    def encode_smaa(self, encoder, mesh, queries=None, index=0):
        # Reuse the ordinary 1x raster pass and redirect its color attachment.
        output = self.output_view
        self.output_view = self.smaa_source
        try:
            self.encode(encoder, mesh, None, queries, index)
        finally:
            self.output_view = output
        for i, (dst, pipeline, group) in enumerate(self.smaa_passes):
            desc = {}
            if i < 2:
                desc["depth_stencil_attachment"] = {
                    "view": self.stencil, "stencil_load_op": "clear" if i == 0 else "load",
                    "stencil_store_op": "store", "stencil_clear_value": 0,
                }
            if queries is not None:
                desc["timestamp_writes"] = {
                    "query_set": queries, "beginning_of_pass_write_index": index + 2 + 2*i,
                    "end_of_pass_write_index": index + 3 + 2*i,
                }
            step = encoder.begin_render_pass(color_attachments=[
                {"view": dst, "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 0)},
            ], **desc)
            if i < 2:
                step.set_stencil_reference(1)
            step.set_pipeline(pipeline)
            step.set_bind_group(0, self.common)
            step.set_bind_group(1, group)
            step.draw(3)
            step.end()

    def run(self, mesh, mode, frames, capture):
        if mode != "smaa":
            return super().run(mesh, mode, frames, capture)
        queries = self.device.create_query_set(type="timestamp", count=8 * frames)
        output = self.device.create_buffer(size=64 * frames,
                                           usage=wgpu.BufferUsage.QUERY_RESOLVE | wgpu.BufferUsage.COPY_SRC)
        encoder = self.device.create_command_encoder()
        for _ in range(8):
            self.encode_smaa(encoder, mesh)
        for i in range(frames):
            self.encode_smaa(encoder, mesh, queries, 8*i)
        encoder.resolve_query_set(queries, 0, 8*frames, output, 0)
        command = encoder.finish()
        start = time.perf_counter()
        self.queue.submit([command])
        ticks = np.frombuffer(self.queue.read_buffer(output), dtype="<u8").reshape(frames, 8)
        wall = (time.perf_counter() - start) * 1000
        if np.any(ticks[:, :-1] > ticks[:, 1:]) or np.any(ticks[:, 0] >= ticks[:, 7]):
            raise ValueError("Unexpected SMAA timestamp order")
        scale = self.timestamp_ns / 1e6
        if (ticks[-1, 7] - ticks[0, 0]) * scale > 1.02 * wall:
            raise ValueError("SMAA timestamps exceed synchronized wall time")
        timing = {"gpuMs": ((ticks[:, 7] - ticks[:, 0]) * scale).tolist(),
                  "rasterMs": ((ticks[:, 1] - ticks[:, 0]) * scale).tolist(),
                  "smaaMs": ((ticks[:, 7] - ticks[:, 2]) * scale).tolist(),
                  "submitAndWaitMs": wall}
        output.destroy()
        queries.destroy()
        if not capture:
            return timing, None
        image = self.queue.read_texture(
            {"texture": self.output}, {"bytes_per_row": 4*self.width, "rows_per_image": self.height},
            (self.width, self.height, 1))
        gray = np.frombuffer(image, dtype=np.uint8).reshape(self.height, self.width, 4)[..., 0].copy()
        if not np.any(gray):
            raise ValueError("SMAA produced a blank frame")
        return timing, gray


def score(reference, image):
    import flip_evaluator

    ref = reference.astype(np.float32) / 255.
    rgb = image.astype(np.float32) / 255.
    mse = float(np.mean((ref - rgb) ** 2, dtype=np.float64))
    _, flip, _ = flip_evaluator.evaluate(np.repeat(ref[..., None], 3, axis=-1),
                                         np.repeat(rgb[..., None], 3, axis=-1), "LDR",
                                         inputsRGB=True, applyMagma=False, parameters={"ppd": 67.})
    return {"psnr_db": -10 * float(np.log10(mse)) if mse else None,
            "ssim": float(structural_similarity(ref, rgb, data_range=1., gaussian_weights=True,
                                               sigma=1.5, use_sample_covariance=False)),
            "flip": float(flip)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--meshes", required=True, type=Path)
    parser.add_argument("--shader-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--asset")
    parser.add_argument("--size", choices=("640x360", "1280x720"), default="1280x720")
    parser.add_argument("--frames", type=int, default=48)
    parser.add_argument("--batches", type=int, default=5)
    args = parser.parse_args()
    if args.frames < 1 or args.batches < 1:
        parser.error("Frames and batches must be positive")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    if any(digest(args.shader_root / f) != fingerprint for f, fingerprint in PINNED.items()):
        raise ValueError("Shader or lookup table differs from the Bevy v0.16.1 pin")
    width, height = map(int, args.size.split("x"))
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = SmaaOffscreen(device, width, height, args.shader_root)
    high = Offscreen(device, width*2, height*2, 4, False)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = {"adapter": dict(adapter.info), "wgpu": importlib.metadata.version("wgpu"),
              "size": [width, height], "instances": 16, "views": 1,
              "shader": "Bevy v0.16.1 SMAA 1x medium (luma edges)",
              "reference": "2x raster resolution with 4x MSAA, box averaged in linear light",
              "shader_sha256": PINNED, "manifest_sha256": digest(args.manifest),
              "code_sha256": digest(Path(__file__)), "frames_per_batch": args.frames,
              "batches": args.batches, "untimed_precondition_frames_per_mode": 16, "assets": {}}
    modes = (("source", None), ("source", "msaa4"), ("source", "smaa"),
             ("source", "linear"), ("source", "cubic"), ("qem", "msaa4"), ("qem", "smaa"),
             ("parts", None), ("parts", "msaa4"), ("parts", "smaa"))
    for name, item in manifest["assets"].items():
        if args.asset is not None and name != args.asset:
            continue
        meshes = {}
        for label in ("source", "qem", "parts"):
            expected = item["exports"][label]
            if label != "source" and expected["faces"] != item["faces"]:
                raise ValueError(f"Reduced meshes differ in face count for {name}")
            vertices, indices = load_export(args.meshes / name / f"{label}.ply", expected)
            meshes[label] = (device.create_buffer_with_data(data=vertices, usage=wgpu.BufferUsage.VERTEX),
                             device.create_buffer_with_data(data=indices, usage=wgpu.BufferUsage.INDEX),
                             len(indices))
        for kind, mode in modes:
            raster.run(meshes[kind], mode, 8, False)
        results = {}
        for batch in range(args.batches):
            offset = 2 * batch % len(modes)
            for kind, mode in modes[offset:] + modes[:offset]:
                label = f"{kind}-{mode or 'native'}"
                rec = results.setdefault(label, {"face_count": meshes[kind][2]//3, "gpu_ms": []})
                samples, _ = raster.run(meshes[kind], mode, args.frames, False)
                rec["gpu_ms"].extend(samples["gpuMs"])
                if "smaaMs" in samples:
                    rec.setdefault("smaa_ms", []).extend(samples["smaaMs"])
        _, raw = high.run(meshes["source"], "msaa4", 1, True)
        ref = linear_gray_to_srgb(raw.reshape(height, 2, width, 2).mean(axis=(1, 3)))
        for kind, mode in modes:
            label = f"{kind}-{mode or 'native'}"
            _, image = raster.run(meshes[kind], mode, 1, True)
            results[label]["quality"] = score(ref, linear_gray_to_srgb(image))
            results[label]["image_sha256"] = hashlib.sha256(image.tobytes()).hexdigest()
        if results["source-smaa"]["image_sha256"] == results["source-native"]["image_sha256"]:
            raise ValueError("SMAA did not change the baseline image")
        report["assets"][name] = results
        print(name, {k: round(float(np.median(v["gpu_ms"])), 3) for k, v in results.items()}, flush=True)
        for v, i, _ in meshes.values():
            v.destroy()
            i.destroy()
    if not report["assets"]:
        parser.error("No matching assets")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
