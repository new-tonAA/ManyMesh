"""Probe per-sample float-encoded primitive IDs on local D3D12 WebGPU."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np
import wgpu

from bench_component_gpu import select_adapter


SIZE = 64
SAMPLES = 4
ID = np.float32(17.0)
SHADER = """
struct VertexOut { @builtin(position) position: vec4f };
struct FragmentOut { @location(0) color: vec4f, @location(1) id: f32 };
@vertex fn vertex_main(@builtin(vertex_index) index: u32) -> VertexOut {
    var p = vec2f(0.0, 0.0);
    if (index == 0u) { p = vec2f(-0.8, -0.8); }
    if (index == 1u) { p = vec2f( 0.8, -0.8); }
    if (index == 2u) { p = vec2f( 0.0,  0.8); }
    return VertexOut(vec4f(p, 0.5, 1.0));
}
@fragment fn fragment_main() -> FragmentOut {
    var out: FragmentOut;
    out.color = vec4f(0.8, 0.7, 0.6, 1.0);
    out.id = 17.0;
    return out;
}
@group(0) @binding(0) var ids: texture_multisampled_2d<f32>;
@group(0) @binding(1) var<storage, read_write> samples: array<f32>;
@compute @workgroup_size(8, 8, 1)
fn copy_samples(@builtin(global_invocation_id) gid: vec3u) {
    let dims = textureDimensions(ids);
    if (gid.x >= dims.x || gid.y >= dims.y) { return; }
    let pixel = vec2i(gid.xy);
    let base = (gid.y * dims.x + gid.x) * 4u;
    for (var sample = 0u; sample < 4u; sample++) {
        samples[base + sample] = textureLoad(ids, pixel, i32(sample)).x;
    }
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    adapter = select_adapter("Intel(R) Iris(R) Xe Graphics", "D3D12")
    if adapter.info["adapter_type"] != "IntegratedGPU":
        raise RuntimeError(f"Refusing non-hardware adapter: {dict(adapter.info)}")
    receipt = {
        "experiment": "D3D12 four-sample float-encoded primitive-ID feasibility",
        "status": "failed", "adapter": dict(adapter.info), "backend": "D3D12",
        "resolution": [SIZE, SIZE], "sample_count": SAMPLES,
        "id_format": "r32float", "primitive_id_exact_float": float(ID),
        "wgpu_version": importlib.metadata.version("wgpu"),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    try:
        device = adapter.request_device_sync(required_features=["timestamp-query"])
        usage = wgpu.TextureUsage.RENDER_ATTACHMENT
        color = device.create_texture(size=(SIZE, SIZE, 1), sample_count=SAMPLES,
                                      format="rgba8unorm", usage=usage)
        resolved = device.create_texture(size=(SIZE, SIZE, 1), format="rgba8unorm",
                                         usage=usage | wgpu.TextureUsage.COPY_SRC)
        ids = device.create_texture(size=(SIZE, SIZE, 1), sample_count=SAMPLES,
                                    format="r32float", usage=usage |
                                    wgpu.TextureUsage.TEXTURE_BINDING)
        module = device.create_shader_module(code=SHADER)
        render_pipeline = device.create_render_pipeline(
            layout="auto", vertex={"module": module, "entry_point": "vertex_main"},
            fragment={"module": module, "entry_point": "fragment_main", "targets": [
                {"format": "rgba8unorm"}, {"format": "r32float"}]},
            primitive={"topology": "triangle-list", "cull_mode": "none"},
            multisample={"count": SAMPLES})
        byte_count = SIZE * SIZE * SAMPLES * np.dtype(np.float32).itemsize
        result = device.create_buffer(size=byte_count,
                                      usage=wgpu.BufferUsage.STORAGE |
                                      wgpu.BufferUsage.COPY_SRC)
        compute_pipeline = device.create_compute_pipeline(
            layout="auto", compute={"module": module, "entry_point": "copy_samples"})
        binding = device.create_bind_group(
            layout=compute_pipeline.get_bind_group_layout(0), entries=[
                {"binding": 0, "resource": ids.create_view()},
                {"binding": 1, "resource": {"buffer": result}},
            ])
        encoder = device.create_command_encoder()
        render = encoder.begin_render_pass(color_attachments=[
            {"view": color.create_view(), "resolve_target": resolved.create_view(),
             "load_op": "clear", "store_op": "discard", "clear_value": (0, 0, 0, 1)},
            {"view": ids.create_view(), "load_op": "clear", "store_op": "store",
             "clear_value": (0.0, 0.0, 0.0, 0.0)},
        ])
        render.set_pipeline(render_pipeline)
        render.draw(3)
        render.end()
        compute = encoder.begin_compute_pass()
        compute.set_pipeline(compute_pipeline)
        compute.set_bind_group(0, binding)
        compute.dispatch_workgroups(SIZE // 8, SIZE // 8, 1)
        compute.end()
        device.queue.submit([encoder.finish()])
        values = np.frombuffer(device.queue.read_buffer(result), dtype=np.float32)
        covered = values[values != 0]
        receipt.update({
            "pixel_sample_count": int(values.size),
            "covered_sample_count": int(covered.size),
            "id_17_sample_count": int(np.count_nonzero(values == ID)),
            "unexpected_nonzero_values": [float(v) for v in np.unique(covered)
                                          if v != ID],
        })
        passed = (receipt["id_17_sample_count"] > 0
                  and receipt["unexpected_nonzero_values"] == [])
        receipt["status"] = "pass" if passed else "fail_wrong_sample_values"
    except Exception as exc:  # Keep backend validation failures as probe results.
        receipt["exception_type"] = type(exc).__name__
        receipt["exception"] = str(exc)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps(receipt, separators=(",", ":"), allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
