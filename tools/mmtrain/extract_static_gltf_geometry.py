"""Extract static GLB triangle geometry from every default-scene mesh instance."""

import argparse
import hashlib
import json
from pathlib import Path
import struct

import numpy as np


GLB_JSON = 0x4E4F534A
GLB_BIN = 0x004E4942


def read_glb(path):
    data = path.read_bytes()
    if len(data) < 12:
        raise ValueError("GLB header is truncated")
    magic, version, declared_length = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2 or declared_length != len(data):
        raise ValueError("Expected a complete glTF 2.0 binary file")
    offset = 12
    document = None
    binary = None
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("GLB chunk header is truncated")
        length, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset:offset + length]
        if len(chunk) != length:
            raise ValueError("GLB chunk is truncated")
        if kind == GLB_JSON:
            document = json.loads(chunk.decode("utf-8"))
        elif kind == GLB_BIN:
            binary = chunk
        offset += length
    if document is None or binary is None:
        raise ValueError("GLB must contain JSON and BIN chunks")
    if document.get("asset", {}).get("version") != "2.0":
        raise ValueError("Only glTF 2.0 is supported")
    if len(document.get("buffers", [])) != 1 or "uri" in document["buffers"][0]:
        raise ValueError("Expected one embedded GLB buffer")
    if document["buffers"][0]["byteLength"] > len(binary):
        raise ValueError("GLB buffer is shorter than its declared length")
    return document, binary


def read_accessor(document, binary, accessor_id, expected_type):
    accessors = document.get("accessors", [])
    views = document.get("bufferViews", [])
    accessor = accessors[accessor_id]
    if accessor.get("type") != expected_type or "sparse" in accessor:
        raise ValueError(f"Unsupported accessor {accessor_id}")
    view = views[accessor["bufferView"]]
    if view.get("buffer", 0) != 0:
        raise ValueError("Only the embedded buffer is supported")
    component_type = accessor["componentType"]
    if component_type == 5126:
        dtype = np.dtype("<f4")
    elif component_type == 5121:
        dtype = np.dtype("u1")
    elif component_type == 5123:
        dtype = np.dtype("<u2")
    elif component_type == 5125:
        dtype = np.dtype("<u4")
    else:
        raise ValueError(f"Unsupported component type {component_type}")
    width = {"SCALAR": 1, "VEC3": 3}.get(expected_type)
    if width is None:
        raise ValueError(f"Unsupported accessor shape {expected_type}")
    stride = view.get("byteStride", dtype.itemsize * width)
    if stride < dtype.itemsize * width:
        raise ValueError("Accessor byte stride is too small")
    base = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    count = accessor["count"]
    end = base + (count - 1) * stride + dtype.itemsize * width
    if count == 0 or end > len(binary):
        raise ValueError(f"Accessor {accessor_id} exceeds the GLB buffer")
    if stride == dtype.itemsize * width:
        values = np.frombuffer(binary, dtype=dtype, count=count * width, offset=base)
        return values.reshape(count, width)
    return np.vstack([
        np.frombuffer(binary, dtype=dtype, count=width,
                      offset=base + i * stride)
        for i in range(count)
    ])


def node_transform(node):
    if "matrix" in node:
        matrix = np.asarray(node["matrix"], dtype=np.float64)
        if matrix.shape != (16,) or not np.isfinite(matrix).all():
            raise ValueError("Invalid node matrix")
        return matrix.reshape(4, 4).T

    translation = np.asarray(node.get("translation", [0, 0, 0]), dtype=np.float64)
    rotation = np.asarray(node.get("rotation", [0, 0, 0, 1]), dtype=np.float64)
    scale = np.asarray(node.get("scale", [1, 1, 1]), dtype=np.float64)
    if translation.shape != (3,) or rotation.shape != (4,) or scale.shape != (3,):
        raise ValueError("Invalid node TRS transform")
    if not (np.isfinite(translation).all() and np.isfinite(rotation).all()
            and np.isfinite(scale).all()):
        raise ValueError("Node transform contains non-finite values")
    norm = np.linalg.norm(rotation)
    if norm == 0:
        raise ValueError("Node quaternion has zero length")
    x, y, z, w = rotation / norm
    rotation_matrix = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0],
        [0, 0, 0, 1],
    ], dtype=np.float64)
    scale_matrix = np.diag([scale[0], scale[1], scale[2], 1.0])
    translation_matrix = np.eye(4, dtype=np.float64)
    translation_matrix[:3, 3] = translation
    return translation_matrix @ rotation_matrix @ scale_matrix


def extract(document, binary):
    scene_id = document.get("scene", 0)
    scenes = document.get("scenes", [])
    if not scenes or scene_id >= len(scenes):
        raise ValueError("The default scene is missing")
    active = set()
    positions_out = []
    triangles_out = []
    vertex_offset = 0
    instance_count = 0
    primitive_count = 0

    def visit(node_id, parent_transform):
        nonlocal vertex_offset, instance_count, primitive_count
        if node_id in active:
            raise ValueError("Scene graph contains a cycle")
        active.add(node_id)
        node = document["nodes"][node_id]
        world_transform = parent_transform @ node_transform(node)
        if "mesh" in node:
            instance_count += 1
            if "skin" in node:
                raise ValueError("Skinned meshes require a skinning-aware extractor")
            mesh = document["meshes"][node["mesh"]]
            for primitive in mesh.get("primitives", []):
                primitive_count += 1
                if primitive.get("mode", 4) != 4 or primitive.get("targets"):
                    raise ValueError("Expected static triangle-list primitives without morph targets")
                positions_id = primitive.get("attributes", {}).get("POSITION")
                if positions_id is None:
                    raise ValueError("Mesh primitive has no POSITION attribute")
                accessor = document["accessors"][positions_id]
                if accessor["componentType"] != 5126:
                    raise ValueError("POSITION must use 32-bit floating-point values")
                positions = read_accessor(document, binary, positions_id, "VEC3").astype(np.float64)
                positions = (np.column_stack([positions, np.ones(len(positions))])
                             @ world_transform.T)[:, :3]

                if "indices" in primitive:
                    indices = read_accessor(
                        document, binary, primitive["indices"], "SCALAR").reshape(-1)
                    if len(indices) % 3:
                        raise ValueError("Triangle-list index count is not divisible by three")
                    triangles = indices.astype(np.int64).reshape(-1, 3)
                else:
                    if len(positions) % 3:
                        raise ValueError("Non-indexed triangle vertex count is not divisible by three")
                    triangles = np.arange(len(positions), dtype=np.int64).reshape(-1, 3)
                if len(triangles) == 0 or triangles.min() < 0 or triangles.max() >= len(positions):
                    raise ValueError("Mesh indices are empty or out of range")
                if np.linalg.det(world_transform[:3, :3]) < 0:
                    triangles = triangles[:, [0, 2, 1]]
                if not np.isfinite(positions).all():
                    raise ValueError("Mesh positions contain non-finite values")
                positions_out.append(positions)
                triangles_out.append(triangles + vertex_offset)
                vertex_offset += len(positions)
        for child in node.get("children", []):
            visit(child, world_transform)
        active.remove(node_id)

    for root in scenes[scene_id].get("nodes", []):
        visit(root, np.eye(4, dtype=np.float64))
    if instance_count == 0 or primitive_count == 0:
        raise ValueError("The default scene contains no triangle mesh primitives")
    return np.concatenate(positions_out), np.concatenate(triangles_out), {
        "mesh_instances": instance_count,
        "triangle_primitives": primitive_count,
        "animation_count_ignored": len(document.get("animations", [])),
    }


def write_obj(path, positions, triangles):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("# Geometry-only static bind-pose extraction; materials and animation omitted.\n")
        for point in positions:
            stream.write("v %.9g %.9g %.9g\n" % tuple(point))
        for face in triangles:
            stream.write("f %d %d %d\n" % tuple(face + 1))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    document, binary = read_glb(args.input)
    positions, triangles, scene_stats = extract(document, binary)
    write_obj(args.output, positions, triangles)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "input_path": str(args.input),
        "input_sha256": sha256(args.input),
        "extractor_sha256": sha256(Path(__file__)),
        "output_path": str(args.output),
        "output_sha256": sha256(args.output),
        "vertices": len(positions),
        "triangles": len(triangles),
        "mesh_instances": scene_stats["mesh_instances"],
        "triangle_primitives": scene_stats["triangle_primitives"],
        "animation_count_ignored": scene_stats["animation_count_ignored"],
        "geometry_scope": "all default-scene static mesh instances at default node transforms; animation channels ignored; no skinning, materials, or texture data",
    }
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}: {len(positions)} vertices, {len(triangles)} triangles")
    print(f"receipt: {args.receipt}")


if __name__ == "__main__":
    main()
