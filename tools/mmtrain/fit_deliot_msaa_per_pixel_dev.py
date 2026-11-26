"""Fit a fixed-topology mesh with per-pixel stochastic gradients on D3D12."""

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import wgpu

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/mmtrain"))
from bench_component_gpu import select_adapter  # noqa: E402


SIZE = 640
REFERENCE_SCALE = 2
DISTANCE = 3.2
FOCAL = 0.9 * DISTANCE
NEAR, FAR = 0.05, 25.0
SAMPLE_COUNT = 4
GRADIENT_SAMPLES = 8
UPDATES = 4
EPSILON = 1.0 / 288.0
MAX_DISPLACEMENT = 0.012
NORMAL_FLOOR = 0.20
SEED = 20261127
LIGHT = np.asarray((0.36, 0.80, 0.48), dtype=np.float32)
LIGHT /= np.linalg.norm(LIGHT)

SHADER = """
struct VertexOut {
    @builtin(position) clip: vec4f,
    @location(0) light: f32,
    @location(1) @interpolate(flat) face_id: f32,
};
struct FragmentOut {
    @location(0) color: vec4f,
    @location(1) face_id: f32,
};
@group(0) @binding(0) var<uniform> projection: mat4x4f;
@vertex fn vertex_main(@location(0) point: vec3f, @location(1) normal: vec3f,
                       @location(2) face_id: f32) -> VertexOut {
    let diffuse = 0.20 + 0.75 * clamp(dot(normal, vec3f(0.36, 0.80, 0.48)), 0.0, 1.0);
    var out: VertexOut;
    out.clip = projection * vec4f(point, 1.0);
    out.light = diffuse;
    out.face_id = face_id;
    return out;
}
@fragment fn fragment_color(in: VertexOut) -> @location(0) vec4f {
    return vec4f(vec3f(in.light), 1.0);
}
@fragment fn fragment_color_id(in: VertexOut) -> FragmentOut {
    var out: FragmentOut;
    out.color = vec4f(vec3f(in.light), 1.0);
    out.face_id = in.face_id;
    return out;
}
@group(1) @binding(0) var id_samples: texture_multisampled_2d<f32>;
@group(1) @binding(1) var<storage, read_write> copied_ids: array<f32>;
@compute @workgroup_size(8, 8, 1)
fn copy_ids(@builtin(global_invocation_id) gid: vec3u) {
    let dims = textureDimensions(id_samples);
    if (gid.x >= dims.x || gid.y >= dims.y) { return; }
    let pixel = vec2i(gid.xy);
    let base = (gid.y * dims.x + gid.x) * 4u;
    for (var sample = 0u; sample < 4u; sample++) {
        copied_ids[base + sample] = textureLoad(id_samples, pixel, i32(sample)).x;
    }
}
"""


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def camera_matrix(basis, width):
    basis = np.asarray(basis, dtype=np.float64)
    scale = float(np.linalg.norm(basis[:, 0]))
    right, up, forward = basis[:, 0] / scale, -basis[:, 1] / scale, basis[:, 2] / scale
    eye = -DISTANCE * basis[:, 2] / scale**2
    camera = np.eye(4)
    camera[:3, :3] = (right, up, forward)
    camera[:3, 3] = -camera[:3, :3] @ eye
    transform = np.array(((FOCAL, 0, 0, 0), (0, FOCAL, 0, 0),
                          (0, 0, FAR / (FAR - NEAR), -FAR * NEAR / (FAR - NEAR)),
                          (0, 0, 1, 0)), dtype=np.float64)
    # The square sensor uses the same focal scale at both reference sizes.
    del width
    return np.ascontiguousarray((transform @ camera).T, dtype=np.float32)


def pack_vertices(positions, faces):
    tri = np.asarray(positions, dtype=np.float32)[faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths <= 1e-12) or not np.isfinite(lengths).all():
        raise ValueError("Cannot render degenerate or nonfinite faces")
    normals /= lengths[:, None]
    packed = np.empty((len(faces), 3, 7), dtype=np.float32)
    packed[:, :, :3] = tri
    packed[:, :, 3:6] = normals[:, None, :]
    packed[:, :, 6] = (np.arange(len(faces), dtype=np.float32) + 1)[:, None]
    return np.ascontiguousarray(packed.reshape(-1, 7))


class Raster:
    def __init__(self, device, width, height, max_faces):
        self.device, self.width, self.height = device, width, height
        self.render_count = 0
        usage = wgpu.TextureUsage.RENDER_ATTACHMENT
        self.output = device.create_texture(size=(width, height, 1), format="rgba8unorm",
                                            usage=usage | wgpu.TextureUsage.COPY_SRC)
        self.output_view = self.output.create_view()
        self.color_msaa = device.create_texture(size=(width, height, 1), sample_count=4,
                                                format="rgba8unorm", usage=usage)
        self.color_msaa_view = self.color_msaa.create_view()
        self.id_msaa = device.create_texture(size=(width, height, 1), sample_count=4,
                                             format="r32float",
                                             usage=usage | wgpu.TextureUsage.TEXTURE_BINDING)
        self.id_msaa_view = self.id_msaa.create_view()
        self.depth_msaa = device.create_texture(size=(width, height, 1), sample_count=4,
                                                format="depth32float", usage=usage).create_view()
        self.uniform = device.create_buffer(size=64,
                                            usage=wgpu.BufferUsage.UNIFORM |
                                            wgpu.BufferUsage.COPY_DST)
        self.vertex_buffer = device.create_buffer(size=max_faces * 3 * 28,
                                                   usage=wgpu.BufferUsage.VERTEX |
                                                   wgpu.BufferUsage.COPY_DST)
        self.shader = device.create_shader_module(code=SHADER)
        vertex = {"module": self.shader, "entry_point": "vertex_main", "buffers": [{
            "array_stride": 28, "attributes": [
                {"format": "float32x3", "offset": 0, "shader_location": 0},
                {"format": "float32x3", "offset": 12, "shader_location": 1},
                {"format": "float32", "offset": 24, "shader_location": 2},
            ]}]}
        self.color_pipeline = device.create_render_pipeline(
            layout="auto", vertex=vertex,
            fragment={"module": self.shader, "entry_point": "fragment_color",
                      "targets": [{"format": "rgba8unorm"}]},
            depth_stencil={"format": "depth32float", "depth_write_enabled": True,
                           "depth_compare": "less"},
            primitive={"topology": "triangle-list", "cull_mode": "none"},
            multisample={"count": 4})
        self.id_pipeline = device.create_render_pipeline(
            layout="auto", vertex=vertex,
            fragment={"module": self.shader, "entry_point": "fragment_color_id",
                      "targets": [{"format": "rgba8unorm"}, {"format": "r32float"}]},
            depth_stencil={"format": "depth32float", "depth_write_enabled": True,
                           "depth_compare": "less"},
            primitive={"topology": "triangle-list", "cull_mode": "none"},
            multisample={"count": 4})
        self.camera_group = device.create_bind_group(
            layout=self.color_pipeline.get_bind_group_layout(0),
            entries=[{"binding": 0, "resource": {"buffer": self.uniform}}])
        self.camera_group_id = device.create_bind_group(
            layout=self.id_pipeline.get_bind_group_layout(0),
            entries=[{"binding": 0, "resource": {"buffer": self.uniform}}])
        self.id_buffer = device.create_buffer(
            size=width * height * 4 * 4,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC)
        self.id_copy_pipeline = device.create_compute_pipeline(
            layout="auto", compute={"module": self.shader, "entry_point": "copy_ids"})
        self.id_group = device.create_bind_group(
            layout=self.id_copy_pipeline.get_bind_group_layout(1), entries=[
                {"binding": 0, "resource": self.id_msaa_view},
                {"binding": 1, "resource": {"buffer": self.id_buffer}},
            ])

    def render(self, positions, faces, basis, with_ids=False):
        packed = pack_vertices(positions, faces)
        self.device.queue.write_buffer(self.vertex_buffer, 0, packed.tobytes())
        matrix = camera_matrix(basis, self.width)
        self.device.queue.write_buffer(self.uniform, 0, matrix.tobytes())
        encoder = self.device.create_command_encoder()
        attachments = [{"view": self.color_msaa_view, "resolve_target": self.output_view,
                        "load_op": "clear", "store_op": "discard",
                        "clear_value": (0, 0, 0, 1)}]
        if with_ids:
            attachments.append({"view": self.id_msaa_view, "load_op": "clear",
                                "store_op": "store", "clear_value": (0, 0, 0, 0)})
        rendering = encoder.begin_render_pass(
            color_attachments=attachments,
            depth_stencil_attachment={"view": self.depth_msaa, "depth_load_op": "clear",
                                      "depth_store_op": "discard", "depth_clear_value": 1.0})
        rendering.set_pipeline(self.id_pipeline if with_ids else self.color_pipeline)
        rendering.set_bind_group(0, self.camera_group_id if with_ids else self.camera_group)
        rendering.set_vertex_buffer(0, self.vertex_buffer)
        rendering.draw(len(faces) * 3)
        rendering.end()
        if with_ids:
            compute = encoder.begin_compute_pass()
            compute.set_pipeline(self.id_copy_pipeline)
            compute.set_bind_group(1, self.id_group)
            compute.dispatch_workgroups(math.ceil(self.width / 8), math.ceil(self.height / 8), 1)
            compute.end()
        self.device.queue.submit([encoder.finish()])
        image_bytes = self.device.queue.read_texture(
            {"texture": self.output},
            {"bytes_per_row": self.width * 4, "rows_per_image": self.height},
            (self.width, self.height, 1))
        image = np.frombuffer(image_bytes, dtype=np.uint8).reshape(
            self.height, self.width, 4).copy()
        ids = None
        if with_ids:
            ids = np.frombuffer(self.device.queue.read_buffer(self.id_buffer),
                                dtype=np.float32).reshape(self.height, self.width, 4).copy()
        self.render_count += 1
        return image, ids


def linear_gray_to_srgb_u8(image):
    gray = image[..., 0].astype(np.float64) / 255.0
    srgb = np.where(gray <= 0.0031308, 12.92 * gray,
                    1.055 * np.power(gray, 1.0 / 2.4) - 0.055)
    gray8 = np.clip(np.rint(srgb * 255), 0, 255).astype(np.uint8)
    return np.repeat(gray8[..., None], 3, axis=-1)


def boundary_mask(faces, vertex_count):
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    _, inverse, counts = np.unique(np.sort(edges, axis=1), axis=0,
                                   return_inverse=True, return_counts=True)
    border_edges = np.unique(np.sort(edges, axis=1)[counts[inverse] == 1])
    mask = np.zeros(vertex_count, dtype=bool)
    mask[border_edges] = True
    return mask


def normal_diagnostics(initial, fitted, faces):
    def normals(points):
        tri = points[faces]
        return np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    reference = normals(initial)
    candidate = normals(fitted)
    denom = np.einsum("ij,ij->i", reference, reference)
    ratio = np.einsum("ij,ij->i", candidate, reference) / np.maximum(denom, 1e-30)
    return {"minimum_face_normal_dot_ratio": float(ratio.min()),
            "degenerate_faces": int(np.count_nonzero(
                np.linalg.norm(candidate, axis=1) <= 1e-12))}


def train_loss(raster, positions, faces, views, references):
    losses = []
    for basis, reference in zip(views, references, strict=True):
        image, _ = raster.render(positions, faces, basis)
        gray = image[..., 0].astype(np.float32) / 255.0
        losses.append(float(np.mean((gray - reference) ** 2, dtype=np.float64)))
    return float(np.mean(losses)), losses


def per_pixel_accumulate(gradient, ids, plus, minus, reference, faces, signs):
    plus_gray = plus[..., 0].astype(np.float32) / 255.0
    minus_gray = minus[..., 0].astype(np.float32) / 255.0
    difference = ((plus_gray - reference) ** 2 - (minus_gray - reference) ** 2)
    difference = difference.reshape(-1) / (SIZE * SIZE)
    face_samples = np.rint(ids.reshape(-1, 4)).astype(np.int32) - 1
    for sample in range(4):
        face_id = face_samples[:, sample]
        valid = face_id >= 0
        if not np.any(valid):
            continue
        face_delta = np.bincount(face_id[valid], weights=difference[valid] * 0.25,
                                 minlength=len(faces))
        for axis in range(3):
            for corner in range(3):
                vertex_ids = faces[:, corner]
                valid_vertices = signs[vertex_ids, axis] != 0
                contribution = np.zeros(len(faces), dtype=np.float64)
                contribution[valid_vertices] = (
                    face_delta[valid_vertices] /
                    (2.0 * signs[vertex_ids[valid_vertices], axis] * EPSILON))
                np.add.at(gradient[:, axis], vertex_ids, contribution)


def fit_arm(raster, name, positions, faces, locked, views, references, seed):
    initial = positions.astype(np.float32).copy()
    current = initial.copy()
    locked = np.asarray(locked, dtype=bool)
    if locked.shape != (len(current),):
        raise ValueError(f"{name}: lock mask does not match vertex count")
    signs_rng = np.random.default_rng(seed)
    m = np.zeros_like(current, dtype=np.float64)
    v = np.zeros_like(current, dtype=np.float64)
    trace = []
    fit_started = time.perf_counter()
    for iteration in range(UPDATES):
        before, per_view_before = train_loss(raster, current, faces, views, references)
        gradient = np.zeros_like(current, dtype=np.float64)
        per_view = []
        for view_index, (basis, reference) in enumerate(zip(views, references, strict=True)):
            _, base_ids = raster.render(current, faces, basis, with_ids=True)
            view_gradient = np.zeros_like(gradient)
            for sample_index in range(GRADIENT_SAMPLES):
                signs = signs_rng.choice((-1., 1.), size=current.shape).astype(np.float32)
                signs[locked] = 0.
                positive, _ = raster.render(current + EPSILON * signs, faces, basis)
                negative, _ = raster.render(current - EPSILON * signs, faces, basis)
                per_pixel_accumulate(view_gradient, base_ids, positive, negative,
                                     reference, faces, signs)
            gradient += view_gradient / GRADIENT_SAMPLES
            per_view.append({"view_index": view_index,
                             "gradient_l2": float(np.linalg.norm(view_gradient))})
        gradient /= len(views)
        gradient[locked] = 0.
        m = 0.9 * m + 0.1 * gradient
        v = 0.999 * v + 0.001 * gradient * gradient
        m_hat = m / (1.0 - 0.9 ** (iteration + 1))
        v_hat = v / (1.0 - 0.999 ** (iteration + 1))
        step = -EPSILON * m_hat / (np.sqrt(v_hat) + 1e-8)
        step[locked] = 0.
        row = {"iteration": iteration, "train_mse_before": before,
               "per_view_train_mse_before": per_view_before,
               "gradient_l2": float(np.linalg.norm(gradient)),
               "step_l2_max": float(np.linalg.norm(step, axis=1).max()),
               "gradient_samples_per_view": GRADIENT_SAMPLES,
               "per_view_gradient_l2": per_view, "accepted_halving": None,
               "train_mse_after": before}
        for half in range(5):
            candidate = current + step * (0.5 ** half)
            offset = candidate - initial
            length = np.linalg.norm(offset, axis=1, keepdims=True)
            offset *= np.minimum(1.0, MAX_DISPLACEMENT / np.maximum(length, 1e-30))
            candidate = initial + offset
            candidate[locked] = initial[locked]
            normal = normal_diagnostics(initial, candidate, faces)
            if normal["degenerate_faces"] or normal["minimum_face_normal_dot_ratio"] < NORMAL_FLOOR:
                continue
            after, per_view_after = train_loss(raster, candidate, faces, views, references)
            if after < before - 1e-12:
                current = candidate
                row.update(accepted_halving=half, train_mse_after=after,
                           per_view_train_mse_after=per_view_after)
                break
        trace.append(row)
    elapsed = time.perf_counter() - fit_started
    diagnostics = normal_diagnostics(initial, current, faces)
    diagnostics.update({
        "maximum_displacement": float(np.linalg.norm(current - initial, axis=1).max()),
        "locked_vertices": int(np.count_nonzero(locked)),
        "locked_vertices_unchanged": bool(np.array_equal(current[locked], initial[locked])),
        "fit_seconds": elapsed,
        "trace": trace,
    })
    return current, diagnostics


def make_arms(arrays):
    suffix = "05290"
    ids = arrays[f"cut_{suffix}_union_ids"]
    global_faces = arrays[f"cut_{suffix}_faces"]
    mapping = np.full(len(arrays["global_ids"]), -1, dtype=np.int64)
    mapping[ids] = np.arange(len(ids))
    many_faces = mapping[global_faces]
    if np.any(many_faces < 0) or len(many_faces) != 5290:
        raise ValueError("ManyMesh cut does not map to its exact 5,290-face budget")
    many_positions = arrays["union_initial_positions"][ids].astype(np.float32)
    many_locked = arrays[f"cut_{suffix}_local_locked"].astype(bool)
    many_locked |= boundary_mask(many_faces, len(many_positions))
    meshopt_faces = arrays[f"cut_{suffix}_baseline_faces"].astype(np.int64)
    meshopt_positions = arrays[f"cut_{suffix}_baseline_positions"].astype(np.float32)
    meshopt_locked = boundary_mask(meshopt_faces, len(meshopt_positions))
    return {
        "manymesh": (many_positions, many_faces.astype(np.int64), many_locked),
        "meshoptimizer": (meshopt_positions, meshopt_faces, meshopt_locked),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--prior-receipt", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    process_started = time.perf_counter()
    prior = json.loads(args.prior_receipt.read_text(encoding="utf-8"))
    if digest(args.geometry) != prior["geometry_sha256"]:
        parser.error("Geometry archive does not match its frozen receipt")
    if digest(args.source) != "b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c":
        parser.error("Source OBJ differs from the frozen Thingi10K asset")
    archive = np.load(args.geometry, allow_pickle=False)
    adapter = select_adapter("Intel(R) Iris(R) Xe Graphics", "D3D12")
    if adapter.info["adapter_type"] != "IntegratedGPU":
        raise RuntimeError(f"Refusing software adapter: {dict(adapter.info)}")
    device = adapter.request_device_sync(required_features=["timestamp-query"])

    from fit_projective_rgb_cpu import camera_sets
    training_views, _ = camera_sets()
    diagnostic = next(cut for cut in prior["cuts"] if cut["face_count"] == 5290)
    diagnostic_views = diagnostic["means_and_per_view"]["views"]
    all_bases = [np.asarray(basis, dtype=np.float64) for basis in training_views]
    all_bases.extend(np.asarray(view["basis"], dtype=np.float64) for view in diagnostic_views)
    source = (archive["source_positions"].astype(np.float32),
              archive["source_faces"].astype(np.int64))
    arms = make_arms(archive)
    high = Raster(device, SIZE * REFERENCE_SCALE, SIZE * REFERENCE_SCALE,
                  len(source[1]))
    low = Raster(device, SIZE, SIZE, 5290)

    references = []
    reference_captures = {}
    for index, basis in enumerate(all_bases):
        image, _ = high.render(*source, basis)
        linear = image.astype(np.float32) / 255.0
        downsampled = linear.reshape(SIZE, 2, SIZE, 2, 4).mean(axis=(1, 3))
        references.append(downsampled[..., 0].copy())
        if index >= len(training_views):
            diagnostic_index = index - len(training_views)
            reference_captures[f"view_{diagnostic_index:02d}_reference"] = np.rint(
                downsampled * 255).astype(np.uint8)

    output_geometry = {}
    arm_rows = {}
    for arm_index, (name, (positions, faces, locked)) in enumerate(arms.items()):
        fitted, report = fit_arm(low, name, positions, faces, locked,
                                 all_bases[:len(training_views)],
                                 references[:len(training_views)], SEED + arm_index)
        output_geometry[f"{name}_raw_positions"] = positions
        output_geometry[f"{name}_faces"] = faces.astype(np.uint32)
        output_geometry[f"{name}_fit_positions"] = fitted
        output_geometry[f"{name}_locked"] = locked
        arm_rows[name] = {"initial_face_count": int(len(faces)),
                          "initial_vertex_count": int(len(positions)),
                          "fit": report}

    image_rows = {"validation": []}
    for view_index, (basis, view) in enumerate(zip(all_bases[len(training_views):],
                                                   diagnostic_views, strict=True)):
        row = {"view": int(view["view"]), "screen_scale": float(view["screen_scale"]),
               "basis": basis.tolist(), "arms": {}}
        reference_key = f"view_{view_index:02d}_reference"
        reference_linear = np.rint(references[len(training_views) + view_index] * 255)
        reference_captures[reference_key] = linear_gray_to_srgb_u8(
            np.repeat(reference_linear[..., None], 4, axis=-1).astype(np.uint8))
        row["reference_capture"] = reference_key
        row["reference_sha256"] = hashlib.sha256(
            reference_captures[reference_key].tobytes()).hexdigest()
        for name, (positions, faces, _) in arms.items():
            variants = (("raw", positions), ("fit", output_geometry[f"{name}_fit_positions"]))
            row["arms"][name] = {}
            for variant, geometry in variants:
                image, _ = low.render(geometry, faces, basis)
                key = f"view_{view_index:02d}_{name}_{variant}"
                captured = linear_gray_to_srgb_u8(image)
                reference_captures[key] = captured
                row["arms"][name][variant] = {
                    "capture": key,
                    "image_sha256": hashlib.sha256(captured.tobytes()).hexdigest(),
                    "silhouette_xor_fraction": float(np.mean(
                        (references[len(training_views) + view_index] > 0) !=
                        (image[..., 0] > 0))),
                }
        image_rows["validation"].append(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    geometry_path = args.out.with_name("result.geometry.npz")
    with geometry_path.open("wb") as stream:
        np.savez_compressed(stream, source_positions=source[0],
                            source_faces=source[1].astype(np.uint32), **output_geometry)
    capture_path = args.out.with_name("result.captures.npz")
    with capture_path.open("wb") as stream:
        np.savez_compressed(stream, **reference_captures)
    protocol = ROOT / "tools/mmtrain/DELIOT_MSAA_PER_PIXEL_FIT_DEV_PROTOCOL_20261127.md"
    receipt = {
        "status": "capture_complete",
        "scope": "one-asset Deliot-style fixed-topology optimizer feasibility screen",
        "source_sha256": digest(args.source), "geometry_sha256": digest(args.geometry),
        "prior_receipt_sha256": digest(args.prior_receipt),
        "protocol_sha256": digest(protocol),
        "script_sha256": digest(__file__),
        "helper_sha256": digest(ROOT / "tools/mmtrain/bench_component_gpu.py"),
        "fit_helper_sha256": digest(ROOT / "tools/mmtrain/fit_projective_rgb_cpu.py"),
        "adapter": dict(adapter.info), "wgpu_version": importlib.metadata.version("wgpu"),
        "resolution": [SIZE, SIZE], "reference_resolution": [SIZE * 2, SIZE * 2],
        "sample_count": SAMPLE_COUNT, "epsilon": EPSILON,
        "gradient_samples_per_update": GRADIENT_SAMPLES, "updates": UPDATES,
        "training_camera_bases": [np.asarray(b).tolist() for b in training_views],
        "diagnostic_views": [{"view": int(v["view"]), "basis": v["basis"],
                              "screen_scale": v["screen_scale"]} for v in diagnostic_views],
        "arms": arm_rows,
        "image_rows": image_rows,
        "render_count": {"high_reference": high.render_count,
                         "low_candidate_and_fit": low.render_count},
        "elapsed_seconds": time.perf_counter() - process_started,
        "geometry_archive": str(geometry_path),
        "geometry_archive_sha256": digest(geometry_path),
        "capture_archive": str(capture_path),
        "capture_archive_sha256": digest(capture_path),
        "limitations": ["single reused train asset", "diagnostic views previously scored",
                        "no asset-held-out confirmation", "flat grayscale shader",
                        "no mobile device", "no equal-frame-time measurement"],
    }
    args.out.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"status": receipt["status"], "adapter": dict(adapter.info),
                      "render_count": receipt["render_count"],
                      "elapsed_seconds": receipt["elapsed_seconds"],
                      "capture_archive_sha256": receipt["capture_archive_sha256"]},
                     separators=(",", ":"), allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
