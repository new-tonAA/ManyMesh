"""Recheck the closed multi-cut placement result after real 4x MSAA resolve."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np
import wgpu

from bench_component_gpu import Offscreen, linear_gray_to_srgb, select_adapter
from bench_contour_priority_aa import upload


ROOT = Path(__file__).resolve().parents[2]
SIZE = 640
DISTANCE = 3.2
FOCAL = 0.9 * DISTANCE
NEAR, FAR = 0.05, 25.0
CUTS = ((2286, "meshoptimizer"), (5290, "meshoptimizer"), (7934, "qem"))
MODES = ("native", "msaa4")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def camera_matrix(raster, basis):
    """Match the square Mitsuba sensor basis and screen scale used by the fit."""
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
    matrix = np.ascontiguousarray((transform @ camera).T, dtype=np.float32)
    uniform = raster.device.create_buffer_with_data(data=matrix, usage=wgpu.BufferUsage.UNIFORM)
    raster.camera = raster.device.create_bind_group(
        layout=raster.raster.get_bind_group_layout(0),
        entries=[{"binding": 0, "resource": {"buffer": uniform}}])
    raster.camera_msaa = raster.device.create_bind_group(
        layout=raster.raster_msaa.get_bind_group_layout(0),
        entries=[{"binding": 0, "resource": {"buffer": uniform}}])
    return uniform


def render(raster, mesh, mode):
    encoder = raster.device.create_command_encoder()
    raster.encode(encoder, mesh, mode)
    raster.device.queue.submit([encoder.finish()])
    payload = raster.device.queue.read_texture(
        {"texture": raster.output},
        {"bytes_per_row": 4 * raster.width, "rows_per_image": raster.height},
        (raster.width, raster.height, 1))
    return np.frombuffer(payload, dtype=np.uint8).reshape(
        raster.height, raster.width, 4)[..., 0].copy()


def geometry_arms(arrays, face_count):
    suffix = f"{face_count:05d}"
    ids = arrays[f"cut_{suffix}_union_ids"]
    global_faces = arrays[f"cut_{suffix}_faces"]
    global_to_local = np.full(len(arrays["global_ids"]), -1, dtype=np.int64)
    global_to_local[ids] = np.arange(len(ids))
    faces = global_to_local[global_faces]
    if np.any(faces < 0):
        raise ValueError(f"Cut {face_count} references a vertex outside its position array")
    faces = faces.astype(np.uint32)
    baseline_faces = arrays[f"cut_{suffix}_baseline_faces"].astype(np.uint32)
    if len(faces) != face_count or len(baseline_faces) != face_count:
        raise ValueError(f"Face-count mismatch at {face_count}")
    return {
        "joint_fit": (arrays["joint_positions"][ids].astype(np.float32), faces),
        "fitted_control": (arrays[f"cut_{suffix}_baseline_fit"].astype(np.float32),
                           baseline_faces),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--prior-receipt", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    prior = json.loads(args.prior_receipt.read_text(encoding="utf-8"))
    if digest(args.geometry) != prior["geometry_sha256"]:
        raise ValueError("Geometry archive does not match the prior experiment receipt")
    if digest(args.source) != prior["source_sha256"]:
        raise ValueError("Source OBJ does not match the pinned original source hash")
    protocol = ROOT / "tools/mmtrain/CLUSTER_DAG_MULTICUT_FINAL_MSAA_RECHECK_PROTOCOL_20261127.md"
    archive = np.load(args.geometry, allow_pickle=False)
    source = (archive["source_positions"].astype(np.float32),
              archive["source_faces"].astype(np.uint32))
    if len(source[1]) != 10580:
        raise ValueError("The full source reference must have exactly 10,580 faces")

    adapter = select_adapter("Intel(R) Iris(R) Xe Graphics", "D3D12")
    if adapter.info["adapter_type"] != "IntegratedGPU":
        raise ValueError(f"Refusing software adapter: {dict(adapter.info)}")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = Offscreen(device, SIZE, SIZE, 1, False)
    high = Offscreen(device, SIZE * 2, SIZE * 2, 1, False)

    all_rows = []
    captures = {}
    for face_count, control_name in CUTS:
        arms = geometry_arms(archive, face_count)
        source_mesh = upload(device, *source)
        candidate_meshes = {name: upload(device, *mesh) for name, mesh in arms.items()}
        cut_rows = []
        old_cut = next(cut for cut in prior["cuts"] if cut["face_count"] == face_count)
        source_hashes = {"reference": [], "joint_fit": {mode: [] for mode in MODES},
                         "fitted_control": {mode: [] for mode in MODES}}
        for view in old_cut["means_and_per_view"]["views"]:
            buffers = [camera_matrix(raster, view["basis"]),
                       camera_matrix(high, view["basis"])]
            high_linear = render(high, source_mesh, "msaa4")
            reference_linear = high_linear.reshape(SIZE, 2, SIZE, 2).mean(axis=(1, 3))
            reference = linear_gray_to_srgb(reference_linear)
            reference_key = f"b{face_count:05d}_v{view['view']:02d}_reference"
            captures[reference_key] = reference
            source_hashes["reference"].append(hashlib.sha256(reference.tobytes()).hexdigest())
            row = {"view": view["view"], "screen_scale": view["screen_scale"],
                   "reference_capture": reference_key, "arms": {}}
            for arm_name, mesh in candidate_meshes.items():
                row["arms"][arm_name] = {}
                for mode in MODES:
                    linear = render(raster, mesh, mode)
                    image = linear_gray_to_srgb(linear)
                    capture_key = f"b{face_count:05d}_v{view['view']:02d}_{arm_name}_{mode}"
                    captures[capture_key] = image
                    image_hash = hashlib.sha256(image.tobytes()).hexdigest()
                    source_hashes[arm_name][mode].append(image_hash)
                    row["arms"][arm_name][mode] = {
                        "capture": capture_key, "image_sha256": image_hash,
                        "silhouette_xor_fraction": float(np.mean(
                            (reference_linear > 0) != (linear > 0))),
                    }
            cut_rows.append(row)
            for buffer in buffers:
                buffer.destroy()
        all_rows.append({"face_count": face_count, "control": control_name,
                         "views": cut_rows,
                         "image_sha256": source_hashes,
                         "geometry_bytes": {
                             name: int(pos.nbytes + inds.nbytes)
                             for name, (pos, inds) in arms.items()}})
        for vertices, indices, _ in (*candidate_meshes.values(), source_mesh):
            vertices.destroy()
            indices.destroy()

    report = {
        "status": "hardware_capture_complete",
        "scope": "post-hoc one-asset D3D12 hardware raster sensitivity check",
        "source_sha256": digest(args.source), "geometry_sha256": digest(args.geometry),
        "prior_receipt_sha256": digest(args.prior_receipt),
        "protocol_sha256": digest(protocol),
        "script_sha256": {name: digest(ROOT / "tools/mmtrain" / name) for name in (
            Path(__file__).name, "bench_component_gpu.py", "bench_contour_priority_aa.py")},
        "adapter": dict(adapter.info), "wgpu_version": importlib.metadata.version("wgpu"),
        "resolution": [SIZE, SIZE], "reference_resolution": [SIZE * 2, SIZE * 2],
        "reference": "original source, hardware 4x MSAA at 2x linear resolution, then 2x2 linear box resolve",
        "metric_plan": "sRGB PSNR pooled over pixels and views; gaussian SSIM; LDR-FLIP at 67 ppd; coverage-mask XOR",
        "camera_views_reused_from_prior_receipt": 24,
        "correlated_views_are_not_independent_samples": True,
        "budgets": all_rows,
        "capture_archive": str(args.out.with_suffix(".captures.npz")),
        "limitations": ["one reused train asset", "fixed flat-neutral shader",
                        "no independent test set", "no frame-time comparison",
                        "not mobile hardware evidence"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    capture_path = args.out.with_suffix(".captures.npz")
    with capture_path.open("wb") as stream:
        np.savez_compressed(stream, **captures)
    report["capture_archive_sha256"] = digest(capture_path)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(json.dumps({"status": "hardware captures complete", "device": dict(adapter.info),
                      "capture_count": len(captures), "capture_archive": str(capture_path)},
                     separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
