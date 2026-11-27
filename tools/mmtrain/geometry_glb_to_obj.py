#!/usr/bin/env python3
"""Export one untextured triangle primitive from a GLB to a geometry-only OBJ."""

import argparse
import json
import struct
from pathlib import Path

import numpy as np


def read_glb(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = path.read_bytes()
    magic, version, total_length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2 or total_length != len(data):
        raise ValueError("invalid GLB header")
    offset = 12
    json_length, json_type = struct.unpack_from("<II", data, offset)
    offset += 8
    if json_type != 0x4E4F534A:
        raise ValueError("first GLB chunk is not JSON")
    gltf = json.loads(data[offset : offset + json_length])
    offset += json_length
    binary_length, binary_type = struct.unpack_from("<II", data, offset)
    offset += 8
    if binary_type != 0x004E4942:
        raise ValueError("second GLB chunk is not BIN")
    binary = data[offset : offset + binary_length]
    meshes = gltf.get("meshes", [])
    if len(meshes) != 1 or len(meshes[0].get("primitives", [])) != 1:
        raise ValueError("expected exactly one mesh and one primitive")
    primitive = meshes[0]["primitives"][0]
    if primitive.get("mode", 4) != 4:
        raise ValueError("primitive is not a triangle list")

    def accessor(index: int) -> tuple[dict, dict, int]:
        item = gltf["accessors"][index]
        view = gltf["bufferViews"][item["bufferView"]]
        start = view.get("byteOffset", 0) + item.get("byteOffset", 0)
        return item, view, start

    position_accessor, position_view, position_start = accessor(primitive["attributes"]["POSITION"])
    if position_accessor["componentType"] != 5126 or position_accessor["type"] != "VEC3":
        raise ValueError("POSITION accessor must be float VEC3")
    stride = position_view.get("byteStride", 12)
    positions = np.asarray(
        [struct.unpack_from("<3f", binary, position_start + row * stride)
         for row in range(position_accessor["count"])],
        dtype=np.float64,
    )

    if "indices" in primitive:
        index_accessor, _, index_start = accessor(primitive["indices"])
        if index_accessor["type"] != "SCALAR":
            raise ValueError("index accessor must be SCALAR")
        formats = {5121: "B", 5123: "H", 5125: "I"}
        index_format = formats.get(index_accessor["componentType"])
        if index_format is None:
            raise ValueError("unsupported index component type")
        indices = np.asarray(
            struct.unpack_from("<" + index_format * index_accessor["count"], binary, index_start),
            dtype=np.int64,
        )
    else:
        indices = np.arange(len(positions), dtype=np.int64)
    if indices.size % 3 or indices.size == 0:
        raise ValueError("triangle index count must be a positive multiple of three")
    if indices.min() < 0 or indices.max() >= len(positions):
        raise ValueError("index is outside the POSITION accessor")

    mesh_nodes = [node for node in gltf.get("nodes", []) if node.get("mesh") == 0]
    if len(mesh_nodes) > 1:
        raise ValueError("multiple nodes reference the mesh; export each transformed instance separately")
    node = mesh_nodes[0] if mesh_nodes else {}
    if "matrix" in node:
        matrix = np.asarray(node["matrix"], dtype=np.float64).reshape(4, 4).T
        positions = (np.column_stack((positions, np.ones(len(positions)))) @ matrix.T)[:, :3]
    else:
        scale = np.asarray(node.get("scale", [1, 1, 1]), dtype=np.float64)
        translation = np.asarray(node.get("translation", [0, 0, 0]), dtype=np.float64)
        x, y, z, w = node.get("rotation", [0, 0, 0, 1])
        rotation = np.asarray(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ],
            dtype=np.float64,
        )
        positions = (positions * scale) @ rotation.T + translation
    if not np.isfinite(positions).all():
        raise ValueError("transformed positions contain non-finite values")
    return positions, indices.reshape(-1, 3)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    positions, faces = read_glb(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="ascii", newline="\n") as stream:
        for x, y, z in positions:
            stream.write(f"v {x:.9g} {y:.9g} {z:.9g}\n")
        for a, b, c in faces + 1:
            stream.write(f"f {a} {b} {c}\n")
    print(f"{len(positions)} vertices, {len(faces)} faces")


if __name__ == "__main__":
    main()
