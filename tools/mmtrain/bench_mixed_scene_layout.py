"""Compare geometry layouts with fixed faces, views, and 4x MSAA in mixed scenes."""

import argparse
import json
from pathlib import Path
import struct
import subprocess

import numpy as np
import wgpu

from bench_component_gpu import linear_gray_to_srgb, load_export, select_adapter
from bench_mixed_scenes import SceneReference, gpu_mesh, sha
from bench_silhouette_guide_fusion import checked_run
from bench_sparse_silhouette_guide import score


GEOMETRIES = ("source", "qem", "parts", "cluster1", "cluster2")
LAYOUTS = ("supplied", "fetch", "cache-fetch")
MODES = tuple((k, layout) for k in GEOMETRIES for layout in LAYOUTS)
COMMIT = "9d9890c73011d75920af614485296d1e03e95448"


def sorted_triangles(indices):
    triangles = indices.reshape(-1, 3)
    return triangles[np.lexsort(triangles.T[::-1])]


def read_geometry(baseline, root, stock):
    geometries = {}
    for asset, fixture in baseline["assets"].items():
        originals = {k: load_export(root / asset / f"{k}.ply", fixture["geometry"][k])
                     for k in ("source", "qem", "parts")}
        for depth in (1, 2):
            kind = f"cluster{depth}"
            path = stock / asset / f"cluster-depth{depth}.npy"
            if sha(path.read_bytes()) != fixture["stock"]["cuts"][kind]["sha256"]:
                raise ValueError(f"Stock cut hash mismatch for {asset}/{kind}")
            indices = np.load(path, allow_pickle=False)
            if (indices.dtype != np.uint32 or indices.shape != (3 * fixture["stock"]["cuts"][kind]["count"],)
                    or indices.max() >= originals["source"][0].size // 6):
                raise ValueError(f"Invalid {asset}/{kind} index buffer")
            originals[kind] = originals["source"][0], indices
        geometries.update({(asset, k): originals[k] for k in GEOMETRIES})
    return geometries


def pack_geometry(geometries, encoder):
    data = bytearray()
    for _, original in geometries.values():
        data += struct.pack("<I", original.size)
        data += original.tobytes()
    helper = Path(__file__).with_name("reorder_scene_indices.mjs")
    result = subprocess.run(["node", str(helper), str(encoder)], input=data, capture_output=True,
                            check=True, timeout=90).stdout
    offset = 0
    packed = {}
    audit = {}
    for (asset, kind), (vertices, original) in geometries.items():
        audit.setdefault(asset, {})[kind] = {
            "faces": original.size // 3, "supplied_vertex_bytes": vertices.nbytes,
            "index_bytes": original.nbytes,
        }
        for layout in LAYOUTS[1:]:
            remap_count, vertex_count = struct.unpack_from("<II", result, offset)
            offset += 8
            indices = np.frombuffer(result, dtype="<u4", count=original.size, offset=offset)
            offset += indices.nbytes
            remap = np.frombuffer(result, dtype="<u4", count=remap_count, offset=offset)
            offset += remap.nbytes
            used = np.flatnonzero(remap != np.iinfo(np.uint32).max)
            if (len(used) != vertex_count or not len(used) or used[-1] >= vertices.size // 6
                    or not np.array_equal(np.sort(remap[used]), np.arange(vertex_count))
                    or indices.max() >= vertex_count):
                raise ValueError(f"Malformed remap for {asset}/{kind}/{layout}")
            inverse = np.empty(vertex_count, dtype=np.uint32)
            inverse[remap[used]] = used
            restored = inverse[indices]
            unchanged = (np.array_equal(restored, original) if layout == "fetch" else
                         np.array_equal(sorted_triangles(restored), sorted_triangles(original)))
            if not unchanged:
                raise ValueError(f"Triangle identity changed for {asset}/{kind}/{layout}")
            data = vertices.reshape(-1, 6)[inverse].ravel()
            packed[(asset, kind, layout)] = data, indices
            audit[asset][kind][layout] = {
                "vertex_bytes": data.nbytes, "vertex_sha256": sha(data.tobytes()),
                "index_sha256": sha(indices.tobytes()), "exact_face_verification": True,
            }
    if offset != len(result):
        raise ValueError("Unexpected trailing meshoptimizer output")
    return packed, audit


def run_view(raster, high, plans, eye, source_view, frames, batches, label, retries):
    raster.camera_at(eye)
    high.camera_at(eye)

    def measure(mode, samples, capture, stage):
        k, layout = mode
        call = lambda: raster.run(plans[mode], "msaa4", samples, capture)
        stats, image = checked_run(call, retries, f"{label}/{k}/{layout}/{stage}")
        return stats["gpuMs"], image

    rows = {k: {layout: {"gpu_ms": []} for layout in LAYOUTS} for k in GEOMETRIES}
    for mode in MODES:
        measure(mode, 8, False, "precondition")
    for batch in range(batches):
        start = (4 * batch) % len(MODES)
        ordered = MODES[start:] + MODES[:start]
        if batch % 2:
            ordered = ordered[::-1]
        for k, layout in ordered:
            timings, _ = measure((k, layout), frames, False, f"batch-{batch+1}")
            rows[k][layout]["gpu_ms"].extend(timings)
    _, high_image = checked_run(lambda: high.run(plans[("source", "supplied")], "msaa4", 1, True),
                               retries, f"{label}/reference")
    ref = linear_gray_to_srgb(high_image.reshape(raster.height, 2, raster.width, 2).mean(axis=(1, 3)))
    if sha(ref.tobytes()) != source_view["reference_srgb_sha256"]:
        raise ValueError(f"Reference does not reproduce the mixed-scene benchmark at {label}")
    for k in GEOMETRIES:
        for layout in LAYOUTS:
            _, image = measure((k, layout), 1, True, "capture")
            digest = sha(image.tobytes())
            quality = score(ref, linear_gray_to_srgb(image))
            if layout == "supplied":
                expected = source_view["modes"][f"{k}-msaa4"]
                if digest != expected["image_sha256"] or quality != expected["quality"]:
                    raise ValueError(f"Original layout capture changed in {label}/{k}")
                original = image
            delta = np.abs(image.astype(np.int16) - original)
            if layout == "fetch" and np.any(delta):
                raise ValueError(f"Fetch-only altered pixels in {label}/{k}")
            rows[k][layout].update({"image_sha256": digest, "quality": quality,
                                    "changed_pixels": int(np.count_nonzero(delta)),
                                    "max_linear_8bit_delta": int(delta.max())})
    return {"eye": eye, "reference_srgb_sha256": sha(ref.tobytes()), "modes": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--meshes", required=True, type=Path)
    parser.add_argument("--stock", required=True, type=Path)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--scene")
    parser.add_argument("--first-view", action="store_true")
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--batches", type=int, default=4)
    args = parser.parse_args()
    if args.frames < 1 or args.batches < 1:
        parser.error("Frames and batches must be positive")
    repo_command = ["git", "-C", str(args.upstream)]
    revision = subprocess.check_output(repo_command + ["rev-parse", "HEAD"], text=True).strip()
    if revision != COMMIT or subprocess.check_output(repo_command + ["diff", "HEAD", "--", "js"], text=True):
        parser.error(f"Expected the unmodified meshoptimizer JS tree at {COMMIT}")
    encoder = args.upstream / "js/meshopt_encoder.js"
    baseline_bytes = args.baseline.read_bytes()
    baseline = json.loads(baseline_bytes)
    if args.scene is not None and args.scene not in baseline["scenes"]:
        parser.error(f"No scene named {args.scene}")
    originals = read_geometry(baseline, args.meshes, args.stock)
    packed, packing_audit = pack_geometry(originals, encoder.resolve())
    adapter = select_adapter("Iris(R) Xe", "D3D12")
    if dict(adapter.info) != baseline["adapter"] or wgpu.__version__ != baseline["wgpu"]:
        raise ValueError("Adapter or wgpu differs from the mixed-scene benchmark")
    device = adapter.request_device_sync(required_features=["timestamp-query"])
    raster = SceneReference(device, *baseline["size"], 1, False)
    high = SceneReference(device, *baseline["reference_size"], 1, False)
    buffers = {}
    for (asset, kind), (vertices, indices) in originals.items():
        source = buffers[(asset, "source", "supplied")][0] if kind.startswith("cluster") else None
        buffers[(asset, kind, "supplied")] = gpu_mesh(device, vertices, indices, source)
    buffers.update({key: gpu_mesh(device, v, i) for key, (v, i) in packed.items()})
    names = (Path(__file__).name, "reorder_scene_indices.mjs", "bench_mixed_scenes.py",
             "bench_component_gpu.py", "bench_silhouette_guide_fusion.py", "bench_bevy_smaa.py",
             "bench_sparse_silhouette_guide.py", "gray_flip.py")
    report = {"baseline_sha256": sha(baseline_bytes), "adapter": dict(adapter.info),
              "size": baseline["size"], "wgpu": wgpu.__version__,
              "node": subprocess.check_output(["node", "--version"], text=True).strip(),
              "meshoptimizer_commit": revision, "encoder_sha256": sha(encoder.read_bytes()),
              "scripts": {k: sha(Path(__file__).with_name(k).read_bytes()) for k in names},
              "frames_per_batch": args.frames, "batches": args.batches,
              "packing": packing_audit, "timestamp_retries": [], "scenes": {}}
    for name, scene in baseline["scenes"].items():
        if args.scene and name != args.scene:
            continue
        transforms = {a: device.create_buffer_with_data(
            data=np.asarray(scene["instance_transforms"][a], dtype=np.float32),
            usage=wgpu.BufferUsage.VERTEX) for a in scene["asset_order"]}
        plans = {mode: [(*buffers[(a, *mode)], buf, len(scene["instance_transforms"][a]))
                        for a, buf in transforms.items()] for mode in MODES}
        views = []
        for i, view in enumerate(scene["views"][:1] if args.first_view else scene["views"]):
            measured = run_view(raster, high, plans, view["eye"], view, args.frames, args.batches,
                                f"{name}/{i}", report["timestamp_retries"])
            views.append(measured)
            print(name, i, {k: [round(float(np.median(m["gpu_ms"])), 3)
                                for m in measured["modes"][k].values()]
                             for k in ("qem", "parts", "cluster2")}, flush=True)
        report["scenes"][name] = {"triangle_counts": scene["triangle_counts"], "views": views}
        for buffer in transforms.values():
            buffer.destroy()
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
