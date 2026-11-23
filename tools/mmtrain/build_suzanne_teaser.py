"""Render the README figure from the licensed Khronos Suzanne sample."""

import argparse
import json
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from bench_upstream_clusterlod import (
    OBJ_SCALE, UPSTREAM_COMMIT, canonical_faces, compact, digest, restore_indices, run_demo,
    write_obj,
)
from cluster_decoder_quality import render
from compare_qem_meshopt_validation_70pct import image_metrics


SOURCE_REVISION = "f0920f5b32d172a30efe3f9257e965918831e6ea"
SOURCE_SHA256 = {
    "Suzanne.gltf": "7e8ae013010aff530162ef2795cec74c2646019e224af17bcfb691664f0f0aec",
    "Suzanne.bin": "b85c2727aa41318e00673d8892f5879d46fb6e476e280f28ee1febd07602b6b8",
}


def load_sample(path):
    gltf = json.loads(path.read_text(encoding="utf-8"))
    primitive = gltf["meshes"][0]["primitives"][0]
    buffer_path = path.with_name("Suzanne.bin")
    buffer = buffer_path.read_bytes()
    if len(buffer) != gltf["buffers"][0]["byteLength"]:
        raise ValueError("Suzanne geometry buffer size differs from the glTF asset")

    def read(index, dtype, width, component, kind):
        accessor = gltf["accessors"][index]
        view = gltf["bufferViews"][accessor["bufferView"]]
        if (view["buffer"] != 0 or accessor["type"] != kind
                or accessor["componentType"] != component or "byteStride" in view):
            raise ValueError("Unexpected Suzanne accessor")
        return np.frombuffer(buffer, dtype=dtype, count=accessor["count"] * width,
                             offset=view.get("byteOffset", 0) + accessor.get("byteOffset", 0))

    if primitive.get("mode", 4) != 4:
        raise ValueError("Expected indexed Suzanne triangles")
    positions = read(primitive["attributes"]["POSITION"], "<f4", 3, 5126, "VEC3").reshape(-1, 3)
    indices = read(primitive["indices"], "<u2", 1, 5123, "SCALAR")
    vertices, remap = np.unique(positions, axis=0, return_inverse=True)
    return vertices.astype(np.float64), remap[indices].reshape(-1, 3), buffer_path


def load_cut(demo, positions, triangles):
    upload = (positions * OBJ_SCALE).astype(np.float32)
    indices, first = np.unique(triangles, return_index=True)
    order = indices[np.argsort(first)]
    with tempfile.TemporaryDirectory(dir=Path("out"), prefix="suzanne-teaser-") as directory:
        folder = Path(directory)
        obj = folder / "source.obj"
        write_obj(obj, upload, triangles)
        p0, t0, _, _, _ = run_demo(demo, obj, 0, folder)
        if not np.array_equal(canonical_faces(restore_indices(p0, t0, upload, order)),
                              canonical_faces(triangles)):
            raise ValueError("Demo did not preserve the reference faces")
        p2, t2, clusters, _, _ = run_demo(demo, obj, 2, folder)
        return (*compact(positions, restore_indices(p2, t2, upload, order)), len(clusters))


def camera():
    yaw, pitch = np.deg2rad((20, 10))
    eye = np.array((np.sin(yaw) * np.cos(pitch), np.sin(pitch), np.cos(yaw) * np.cos(pitch)))
    right = np.cross((0., 1., 0.), eye)
    right /= np.linalg.norm(right)
    return np.stack((right, -np.cross(eye, right), -eye), axis=1).astype(np.float32)


def compose(images, counts, font_path, output):
    size = images[0].shape[0]
    border, gap, heading = 20, 16, 92
    canvas = Image.new("RGB", (2 * border + 2 * gap + 3 * size, heading + size + 60), "#141920")
    draw = ImageDraw.Draw(canvas)
    title = ImageFont.truetype(str(font_path), size=32)
    body = ImageFont.truetype(str(font_path), size=21)
    draw.text((border, 12), "Suzanne  |  Geometry at two triangle budgets", fill="#f1f3f6", font=title)
    labels = ("Full mesh", "Cluster LOD", "Silhouette mismatch")
    subtitles = (f"{counts[0]:,} triangles", f"{counts[1]:,} triangles",
                 "Orange: missing   Blue: extra")
    for i, (pixels, label, subtitle) in enumerate(zip(images, labels, subtitles)):
        x = border + i * (size + gap)
        draw.text((x, 58), label, fill="#f1f3f6", font=body)
        canvas.paste(Image.fromarray(pixels), (x, heading))
        draw.text((x, heading + size + 9), subtitle, fill="#c1c9d3", font=body)
    canvas.save(output, optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gltf", required=True, type=Path)
    parser.add_argument("--demo", required=True, type=Path)
    parser.add_argument("--font", required=True, type=Path)
    parser.add_argument("--figure", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    positions, triangles, buffer = load_sample(args.gltf)
    source_hashes = {path.name: digest(path) for path in (args.gltf, buffer)}
    if source_hashes != SOURCE_SHA256:
        raise ValueError("Suzanne source differs from the licensed, pinned sample")
    center = (positions.min(axis=0) + positions.max(axis=0)) * .5
    radius = np.linalg.norm(positions - center, axis=1).max()
    positions = ((positions - center) / radius).astype(np.float32).astype(np.float64)
    reduced, faces, cluster_count = load_cut(args.demo.resolve(), positions, triangles)
    size, samples = 384, 2
    basis = camera()
    full, full_coverage = render(positions, triangles, basis, size, samples)
    lod, lod_coverage = render(reduced, faces, basis, size, samples)
    signed = (full_coverage > 0).astype(np.int8) - (lod_coverage > 0)
    differences = (full.astype(np.float32) * .38).astype(np.uint8)
    differences[signed > 0] = (255, 144, 78)
    differences[signed < 0] = (73, 191, 255)
    args.figure.parent.mkdir(parents=True, exist_ok=True)
    compose((full, lod, differences), (len(triangles), len(faces)), args.font, args.figure)
    receipt = {
        "asset": "Khronos glTF Sample Assets Suzanne, 2017 UX3D, Norbert Nopper, CC0-1.0",
        "source_revision": SOURCE_REVISION, "source_sha256": source_hashes,
        "upstream_meshoptimizer_revision": UPSTREAM_COMMIT,
        "demo_sha256": digest(args.demo), "figure_sha256": digest(args.figure),
        "generator_sha256": digest(Path(__file__)),
        "source_faces": len(triangles), "cut_faces": len(faces), "cut_clusters": cluster_count,
        "camera": {"projection": "orthographic", "yaw_degrees": 20, "pitch_degrees": 10},
        "resolution": [size, size], "samples_per_pixel": samples**2,
        "metrics": image_metrics(full, lod, full_coverage, lod_coverage, 67.),
    }
    args.receipt.write_text(json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(len(triangles), len(faces), cluster_count, args.figure)


if __name__ == "__main__":
    main()
