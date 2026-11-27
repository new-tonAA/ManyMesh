#!/usr/bin/env python3
"""Wrap a triangle-only OBJ geometry in a minimal untextured glTF binary."""

import argparse
import json
import math
import struct
from pathlib import Path


def parse_obj(path: Path) -> tuple[list[tuple[float, float, float]], list[int]]:
    positions: list[tuple[float, float, float]] = []
    indices: list[int] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        if fields[0] == "v":
            if len(fields) < 4:
                raise ValueError(f"line {line_number}: expected three vertex coordinates")
            position = tuple(float(value) for value in fields[1:4])
            if not all(math.isfinite(value) for value in position):
                raise ValueError(f"line {line_number}: vertex has a non-finite coordinate")
            positions.append(position)
        elif fields[0] == "f":
            if len(fields) != 4:
                raise ValueError(f"line {line_number}: only triangle faces are supported")
            face = []
            for item in fields[1:]:
                index = int(item.split("/", 1)[0])
                index = index - 1 if index > 0 else len(positions) + index
                if index < 0 or index >= len(positions):
                    raise ValueError(f"line {line_number}: vertex index is out of range")
                face.append(index)
            indices.extend(face)

    if not positions or not indices:
        raise ValueError("input OBJ must contain vertices and triangle faces")
    return positions, indices


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    positions, indices = parse_obj(args.input)
    vertex_count = len(positions)
    position_values = [value for position in positions for value in position]
    position_bytes = struct.pack("<" + "f" * len(position_values), *position_values)
    use_u16 = max(indices) <= 65535
    index_component_type = 5123 if use_u16 else 5125
    index_format = "H" if use_u16 else "I"
    index_bytes = struct.pack("<" + index_format * len(indices), *indices)
    binary = position_bytes + index_bytes
    gltf = {
        "asset": {"version": "2.0", "generator": "ManyMesh local baseline adapter"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(position_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(position_bytes), "byteLength": len(index_bytes), "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": vertex_count,
                "type": "VEC3",
                "min": [min(position_values[axis::3]) for axis in range(3)],
                "max": [max(position_values[axis::3]) for axis in range(3)],
            },
            {
                "bufferView": 1,
                "componentType": index_component_type,
                "count": len(indices),
                "type": "SCALAR",
                "min": [min(indices)],
                "max": [max(indices)],
            },
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    json_chunk = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((-len(json_chunk)) % 4)
    binary += b"\0" * ((-len(binary)) % 4)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(binary)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as stream:
        stream.write(struct.pack("<4sII", b"glTF", 2, total_length))
        stream.write(struct.pack("<II", len(json_chunk), 0x4E4F534A))
        stream.write(json_chunk)
        stream.write(struct.pack("<II", len(binary), 0x004E4942))
        stream.write(binary)
    print(f"{vertex_count} vertices, {len(indices) // 3} faces, {total_length} bytes")


if __name__ == "__main__":
    main()
