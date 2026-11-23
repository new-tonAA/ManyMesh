"""Measure how desktop antialiasing changes the paired contour priority result."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np
import wgpu

from bench_bevy_smaa import PINNED, SmaaOffscreen, score
from bench_component_gpu import Offscreen, linear_gray_to_srgb, projection_matrix, select_adapter


WIDTH, HEIGHT = 640, 360
COLUMNS = 4
VIEWS = 6
FRAMES = 8
MODES = (("native", None), ("msaa4", "msaa4"), ("smaa", "smaa"), ("cubic", "cubic"))
ARMS = ("source", "qem", "contour_priority")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def upload(device, vertices, indices):
    # One vertex per corner reproduces the CPU geometry screen's flat shading.
    triangles = vertices[indices]
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    corners = np.column_stack((triangles.reshape(-1, 3), np.repeat(normals, 3, axis=0)))
    packed = np.ascontiguousarray(corners, dtype=np.float32)
    sequence = np.arange(len(packed), dtype=np.uint32)
    return (device.create_buffer_with_data(data=packed, usage=wgpu.BufferUsage.VERTEX),
            device.create_buffer_with_data(data=sequence, usage=wgpu.BufferUsage.INDEX),
            len(sequence))


def bind_camera(raster, eye):
    matrix = projection_matrix(raster.width, raster.height, eye=eye)
    buffer = raster.device.create_buffer_with_data(data=matrix, usage=wgpu.BufferUsage.UNIFORM)
    entries = [{"binding": 0, "resource": {"buffer": buffer}}]
    raster.camera = raster.device.create_bind_group(
        layout=raster.raster.get_bind_group_layout(0), entries=entries)
    raster.camera_msaa = raster.device.create_bind_group(
        layout=raster.raster_msaa.get_bind_group_layout(0), entries=entries)
    return buffer


def camera_eye(view):
    yaw = np.deg2rad(13 + 60 * view)
    pitch = np.deg2rad((-15, 20, 35)[view % 3])
    distance = (3.2, 4.7)[view % 2]
    return distance * np.array((np.sin(yaw) * np.cos(pitch), np.sin(pitch),
                                np.cos(yaw) * np.cos(pitch)))


def load_geometry(device, path, replay, earlier):
    if digest(path) != replay["geometry_sha256"]:
        raise ValueError(f"Prepared mesh archive changed: {path}")
    if any(replay[key] != earlier[key] for key in ("source_sha256", "target_faces", "views")):
        raise ValueError(f"Prepared mesh does not replay the prior CPU scores: {path}")
    with np.load(path, allow_pickle=False) as arrays:
        meshes = {name: upload(device, arrays[f"{name}_vertices"], arrays[f"{name}_triangles"])
                  for name in ARMS}
    if (meshes["source"][2] != 3 * replay["source_faces"]
            or any(meshes[name][2] != 3 * replay["target_faces"] for name in ARMS[1:])):
        raise ValueError(f"Face counts in prepared geometry differ from the receipt: {path}")
    return meshes


def measure(raster, high, meshes, view):
    eye = camera_eye(view)
    buffers = [bind_camera(raster, eye), bind_camera(high, eye)]
    _, high_image = high.run(meshes["source"], "msaa4", 2, True)
    reference = linear_gray_to_srgb(
        high_image.reshape(HEIGHT, 2, WIDTH, 2).mean(axis=(1, 3)))
    pairs = [(name, label, mode) for name in ARMS for label, mode in MODES]
    ordered = pairs[view:] + pairs[:view]
    rows = {}
    for schedule in (ordered, ordered[::-1]):
        for name, label, mode in schedule:
            result, _ = raster.run(meshes[name], mode, FRAMES, False)
            row = rows.setdefault(f"{name}/{label}", {"batches": []})
            row["batches"].append(result)
    for name, label, mode in ordered:
        _, gray = raster.run(meshes[name], mode, 1, True)
        row = rows[f"{name}/{label}"]
        row["quality"] = score(reference, linear_gray_to_srgb(gray))
        row["image_sha256"] = hashlib.sha256(gray.tobytes()).hexdigest()
    for buffer in buffers:
        buffer.destroy()
    return {"view": view, "eye": eye.tolist(), "modes": rows,
            "reference_sha256": hashlib.sha256(reference.tobytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--prior-results", type=Path, required=True)
    parser.add_argument("--shader-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--asset", required=True)
    args = parser.parse_args()
    if any(digest(args.shader_root / file) != expected for file, expected in PINNED.items()):
        parser.error("SMAA source or lookup tables differ from the pinned version")
    earlier = json.loads(args.prior_results.read_text(encoding="utf-8"))["assets"][args.asset]["scored"]
    replay_path = args.prepared / f"{args.asset}.json"
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = SmaaOffscreen(device, WIDTH, HEIGHT, args.shader_root)
    high = Offscreen(device, WIDTH * 2, HEIGHT * 2, COLUMNS, False)
    meshes = load_geometry(device, args.prepared / f"{args.asset}.npz", replay, earlier)
    result = {
        "asset": args.asset, "source_sha256": replay["source_sha256"],
        "geometry_sha256": replay["geometry_sha256"], "prepare_receipt_sha256": digest(replay_path),
        "cpu_screen_sha256": digest(args.prior_results),
        "adapter": dict(adapter.info), "wgpu_version": importlib.metadata.version("wgpu"),
        "numpy_version": np.__version__, "size": [WIDTH, HEIGHT],
        "instances": COLUMNS ** 2, "frames_per_batch": FRAMES,
        "timing_protocol": "two capture-free batches before separate color capture and scoring",
        "source_faces": replay["source_faces"], "target_faces": replay["target_faces"],
        "shader_sha256": PINNED,
        "script_sha256": {name: digest(Path(__file__).with_name(name)) for name in
                          (Path(__file__).name, "bench_component_gpu.py", "bench_bevy_smaa.py")},
        "reference": "full source, 2x resolution with hardware 4x MSAA, linear 2x box resolve",
        "views": [measure(raster, high, meshes, view) for view in range(VIEWS)],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
