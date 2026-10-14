#!/usr/bin/env python3

# Copyright (C) 2026 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Builds a large scene out of one mesh, for scene-scale ManyMesh experiments.

ManyMesh has so far been measured on single objects, where the camera sees all of the
geometry. A level behaves differently: most of it is off screen or far away, so what matters
is how the level of detail machinery behaves across a large, spatially spread set of clusters
rather than how well one object degrades.

This tiles a mesh across a grid and writes the result as binary PLY. It is a synthetic scene,
which is a weaker test than a scanned level and much cheaper to obtain and reproduce - the
public scene archives are hundreds of megabytes to a gigabyte each and this machine has to
stay usable.

The layout is deterministic: instance (row, column) gets a yaw of `--yaw-step` degrees times
its index and a scale that varies by a fixed small amount, so two runs produce identical
geometry.

Usage:
    make_scene.py <prop.ply> <scene.ply> --rows 6 --cols 6 --spacing 420
"""

import argparse
import sys

import numpy as np


def read_ply(path):
    """Reads a binary little-endian PLY with float xyz and uint8-count triangle faces."""
    with open(path, "rb") as handle:
        data = handle.read()

    header_end = data.index(b"end_header\n") + len(b"end_header\n")
    header = data[:header_end].decode("ascii")
    if "binary_little_endian" not in header:
        raise SystemExit(f"{path} is not binary little-endian; expected the output of mmgeo")

    vertex_count = int(next(l for l in header.splitlines() if l.startswith("element vertex")).split()[2])
    face_count = int(next(l for l in header.splitlines() if l.startswith("element face")).split()[2])

    offset = header_end
    positions = np.frombuffer(data, dtype="<f4", count=vertex_count * 3,
                              offset=offset).reshape(-1, 3)
    offset += vertex_count * 12

    # Each face is a uint8 count followed by that many int32 indices. The prop comes from
    # mmgeo, so every face is a triangle.
    raw = np.frombuffer(data, dtype=np.uint8, count=face_count * 13, offset=offset)
    raw = raw.reshape(face_count, 13)
    if not np.all(raw[:, 0] == 3):
        raise SystemExit(f"{path} has non-triangle faces")
    faces = raw[:, 1:].copy().view("<i4").reshape(face_count, 3)

    return positions.astype(np.float32), faces.astype(np.int32)


def write_ply(path, positions, faces):
    with open(path, "wb") as handle:
        handle.write(f"ply\nformat binary_little_endian 1.0\n".encode("ascii"))
        handle.write(f"element vertex {len(positions)}\n".encode("ascii"))
        handle.write(b"property float x\nproperty float y\nproperty float z\n")
        handle.write(f"element face {len(faces)}\n".encode("ascii"))
        handle.write(b"property list uchar int vertex_indices\n")
        handle.write(b"end_header\n")

        handle.write(positions.astype("<f4").tobytes())

        block = np.empty((len(faces), 13), dtype=np.uint8)
        block[:, 0] = 3
        block[:, 1:] = faces.astype("<i4").view(np.uint8).reshape(-1, 12)
        handle.write(block.tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prop")
    parser.add_argument("out")
    parser.add_argument("--rows", type=int, default=6)
    parser.add_argument("--cols", type=int, default=6)
    parser.add_argument("--spacing", type=float, default=420.0,
            help="distance between instance centres, in the prop's units")
    parser.add_argument("--yaw-step", type=float, default=37.0,
            help="degrees of yaw added per instance")
    parser.add_argument("--scale-step", type=float, default=0.05,
            help="fractional scale added per instance")
    parser.add_argument("--ground", type=int, default=0,
            help="add a ground plane of 2*N^2 triangles spanning the instances")
    args = parser.parse_args()

    positions, faces = read_ply(args.prop)
    print(f"prop: {len(positions)} vertices, {len(faces)} triangles")

    count = args.rows * args.cols
    out_positions = np.empty((len(positions) * count, 3), dtype=np.float32)
    out_faces = np.empty((len(faces) * count, 3), dtype=np.int32)

    # Centre the prop on its own origin so instances sit where the grid puts them.
    centre = (positions.min(axis=0) + positions.max(axis=0)) * 0.5
    local = positions - centre

    for index in range(count):
        row, col = divmod(index, args.cols)
        angle = np.radians(args.yaw_step * index)
        scale = 1.0 + args.scale_step * ((index % 5) - 2)

        cos_a, sin_a = np.cos(angle), np.sin(angle)
        rotated = np.empty_like(local)
        rotated[:, 0] = local[:, 0] * cos_a - local[:, 2] * sin_a
        rotated[:, 1] = local[:, 1]
        rotated[:, 2] = local[:, 0] * sin_a + local[:, 2] * cos_a
        rotated *= scale

        offset = np.array([(col - (args.cols - 1) / 2.0) * args.spacing,
                           0.0,
                           (row - (args.rows - 1) / 2.0) * args.spacing], dtype=np.float32)

        vertex_base = index * len(positions)
        out_positions[vertex_base:vertex_base + len(positions)] = rotated + offset
        out_faces[index * len(faces):(index + 1) * len(faces)] = faces + vertex_base

    if args.ground > 0:
        # A real level is mostly floor and walls, which is where its triangle count lives, and
        # it is what fills the frame. Without something large and close the scene occupies a
        # few percent of the picture and any image metric mostly measures empty background.
        n = args.ground
        span = (max(args.rows, args.cols) - 1) * args.spacing + args.spacing
        axis = np.linspace(-span / 2, span / 2, n + 1, dtype=np.float32)
        grid_x, grid_z = np.meshgrid(axis, axis)
        floor_y = float(out_positions[:, 1].min())
        vertices = np.stack([grid_x.ravel(), np.full(grid_x.size, floor_y, dtype=np.float32),
                             grid_z.ravel()], axis=1)

        index = np.arange((n + 1) * (n + 1), dtype=np.int32).reshape(n + 1, n + 1)
        a = index[:-1, :-1].ravel()
        b = index[:-1, 1:].ravel()
        c = index[1:, 1:].ravel()
        d = index[1:, :-1].ravel()
        # Wound so the normals point up. The obvious order gives (0, -dx*dz, 0), which faces
        # downwards and is therefore backface culled from any camera above the ground.
        triangles = np.concatenate([np.stack([a, c, b], axis=1), np.stack([a, d, c], axis=1)])

        base = len(out_positions)
        out_positions = np.concatenate([out_positions, vertices])
        out_faces = np.concatenate([out_faces, triangles.astype(np.int32) + base])
        print(f"ground: {2 * n * n} triangles spanning {span:.0f} units")

    write_ply(args.out, out_positions, out_faces)

    extent = out_positions.max(axis=0) - out_positions.min(axis=0)
    print(f"{count} instances -> {len(out_faces)} triangles, "
          f"extent {extent[0]:.0f} x {extent[1]:.0f} x {extent[2]:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
