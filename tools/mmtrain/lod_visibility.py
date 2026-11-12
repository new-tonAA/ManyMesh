#!/usr/bin/env python3
#
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

"""Extract geometry-only screen-space features for equal-triangle LOD swaps."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from lod_oracle import digest


VISIBILITY_FIELDS = (
    "removed_visible_fraction", "added_visible_fraction",
    "removed_visibility", "added_visibility",
    "silhouette_loss_fraction", "silhouette_gain_fraction",
    "changed_boundary_fraction", "relative_depth_change",
)
SILHOUETTE_METRIC = "geometry_silhouette_xor_over_union"


def read_cut(path, load_positions):
    vertex_digest = hashlib.sha256()
    positions, faces = [], []
    with path.open("rb") as stream:
        for line in stream:
            if line.startswith(b"v "):
                vertex_digest.update(line)
                if load_positions:
                    positions.append(tuple(map(float, line.split()[1:])))
            elif line.startswith(b"f "):
                faces.append(tuple(sorted(int(x.split(b"/", 1)[0]) - 1
                                          for x in line.split()[1:])))
    if any(len(face) != 3 or face[0] < 0 for face in faces):
        raise ValueError(f"Expected triangles with absolute OBJ indices: {path}")
    return np.asarray(positions), faces, vertex_digest.hexdigest()


def project(positions, eye, target, width, height):
    eye = np.fromstring(eye, sep=",")
    forward = np.fromstring(target, sep=",") - eye
    distance = np.linalg.norm(forward)
    if distance == 0:
        raise ValueError("Eye coincides with target")
    forward /= distance
    right = np.cross(forward, [0, 1, 0])
    right_length = np.linalg.norm(right)
    if right_length == 0:
        raise ValueError("Camera direction is parallel to up")
    right /= right_length
    up = np.cross(right, forward)
    delta = positions - eye
    depth = delta @ forward
    near = max(0.01 * distance, 1e-3)
    if np.any(depth <= near) or np.any(depth >= 20 * distance):
        raise ValueError("Capture requires vertices between the near and far planes")
    inverse_depth = 1 / depth
    focal = height / (2 * math.tan(math.radians(45) / 2))
    return np.column_stack((width / 2 + (delta @ right) * inverse_depth * focal,
                            height / 2 - (delta @ up) * inverse_depth * focal,
                            inverse_depth))


def fragments(projected, faces, width, height):
    if not len(faces):
        return np.empty(0, dtype=np.intp), np.empty(0, dtype=np.intp), np.empty(0)
    tri = projected[np.asarray(faces)]
    xy = tri[:, :, :2]
    lo = np.maximum(np.ceil(xy.min(axis=1) - 0.5), 0).astype(np.intp)
    hi = np.minimum(np.floor(xy.max(axis=1) - 0.5), [width - 1, height - 1]).astype(np.intp)
    dims = np.maximum(0, hi - lo + 1)
    area = ((xy[:, 1, 0] - xy[:, 0, 0]) * (xy[:, 2, 1] - xy[:, 0, 1])
            - (xy[:, 1, 1] - xy[:, 0, 1]) * (xy[:, 2, 0] - xy[:, 0, 0]))
    size = np.where(np.abs(area) > 1e-10, dims[:, 0] * dims[:, 1], 0)
    offsets = np.r_[0, np.cumsum(size)]
    face_ids, pixels, depths = [], [], []
    start = 0
    while start < len(tri):
        end = max(start + 1, int(np.searchsorted(offsets, offsets[start] + 250000,
                                                 side="right")) - 1)
        face = np.repeat(np.arange(start, end), size[start:end])
        offset = np.arange(offsets[start], offsets[end]) - offsets[face]
        x = lo[face, 0] + offset % dims[face, 0]
        y = lo[face, 1] + offset // dims[face, 0]
        a, b, c = xy[face, 0], xy[face, 1], xy[face, 2]
        px, py = x + 0.5 - a[:, 0], y + 0.5 - a[:, 1]
        w1 = (px * (c[:, 1] - a[:, 1]) - py * (c[:, 0] - a[:, 0])) / area[face]
        w2 = ((b[:, 0] - a[:, 0]) * py - (b[:, 1] - a[:, 1]) * px) / area[face]
        w0 = 1 - w1 - w2
        inside = (w0 >= -1e-8) & (w1 >= -1e-8) & (w2 >= -1e-8)
        depth = tri[face, :, 2]
        face_ids.append(face[inside])
        pixels.append((y * width + x)[inside])
        depths.append((w0 * depth[:, 0] + w1 * depth[:, 1] + w2 * depth[:, 2])[inside])
        start = end
    return tuple(np.concatenate(part) for part in (face_ids, pixels, depths))


def z_buffer(pixels, depths, count):
    z = np.zeros(count)
    np.maximum.at(z, pixels, depths)
    return z


def boundary(mask):
    pad = np.pad(mask, 1)
    return mask & ~(pad[:-2, 1:-1] & pad[2:, 1:-1] & pad[1:-1, :-2] & pad[1:-1, 2:])


def silhouette_error(mask, reference):
    return int(np.count_nonzero(mask ^ reference)) / max(
        int(np.count_nonzero(mask | reference)), 1)


def frame_features(path, meta, width, height, measure_silhouette=False):
    positions, base_faces, vertices = read_cut(path / "oracle_baseline.obj", True)
    with (path / "oracle.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    swaps = rows[2:]
    if not swaps and not measure_silhouette:
        return {}, {}
    if len(base_faces) != int(rows[1]["triangles"]) or len(set(base_faces)) != len(base_faces):
        raise ValueError(f"Invalid baseline face list: {path}")
    projected = project(positions, meta["eye"], meta["target"], width, height)
    count = width * height
    base_ids = {face: i for i, face in enumerate(base_faces)}
    face, pixel, depth = fragments(projected, base_faces, width, height)
    base_depth = z_buffer(pixel, depth, count)
    base_mask = base_depth > 0
    silhouette = {}
    if measure_silhouette:
        reference_positions, reference_faces, _ = read_cut(path / "oracle_reference.obj", True)
        reference_projection = project(reference_positions, meta["eye"], meta["target"],
                                       width, height)
        _, reference_pixel, reference_depth = fragments(
            reference_projection, reference_faces, width, height)
        reference_mask = z_buffer(reference_pixel, reference_depth, count) > 0
        silhouette["oracle_baseline"] = silhouette_error(base_mask, reference_mask)
    covered = max(int(base_mask.sum()), 1)
    base_boundary = boundary(base_mask.reshape(height, width)).ravel()
    result = {}
    for row in swaps:
        stem = row["stem"]
        _, candidate, candidate_vertices = read_cut(path / f"{stem}.obj", False)
        if (candidate_vertices != vertices or len(candidate) != len(base_faces)
                or len(set(candidate)) != len(candidate)):
            raise ValueError(f"Candidate changes vertex space or face count: {path / stem}")
        removed = np.ones(len(base_faces), dtype=bool)
        added = []
        for tri in candidate:
            index = base_ids.get(tri)
            if index is None:
                added.append(tri)
            else:
                removed[index] = False
        gone = removed[face]
        removed_depth = z_buffer(pixel[gone], depth[gone], count)
        retained_depth = z_buffer(pixel[~gone], depth[~gone], count)
        _, new_pixel, new_depth = fragments(projected, added, width, height)
        added_depth = z_buffer(new_pixel, new_depth, count)
        candidate_depth = np.maximum(retained_depth, added_depth)
        candidate_mask = candidate_depth > 0
        if measure_silhouette:
            silhouette[stem] = silhouette_error(candidate_mask, reference_mask)
        # A coplanar shared triangle wins ties, so swapping duplicate coverage
        # cannot create artificial changes in the depth or visibility features.
        removed_visible = removed_depth > retained_depth
        added_visible = added_depth > retained_depth
        changed = removed_visible | added_visible
        new_boundary = boundary(candidate_mask.reshape(height, width)).ravel()
        overlap = base_mask & candidate_mask & changed
        relative_depth = np.abs(base_depth[overlap] - candidate_depth[overlap])
        relative_depth /= np.maximum(base_depth[overlap], candidate_depth[overlap])
        result[stem] = [
            int(removed_visible.sum()) / covered,
            int(added_visible.sum()) / covered,
            int(removed_visible.sum()) / max(int(np.count_nonzero(removed_depth)), 1),
            int(added_visible.sum()) / max(int(np.count_nonzero(added_depth)), 1),
            int(np.count_nonzero(base_mask & ~candidate_mask)) / covered,
            int(np.count_nonzero(candidate_mask & ~base_mask)) / covered,
            int(np.count_nonzero(changed & (base_boundary | new_boundary))) / covered,
            float(relative_depth.sum()) / covered,
        ]
    return result, silhouette


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", nargs="+", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--silhouette-out", type=Path,
                        help="Write reference-dependent silhouette labels separately")
    args = parser.parse_args()
    if args.silhouette_out and args.silhouette_out.resolve() == args.out.resolve():
        parser.error("feature and silhouette label outputs must be different")
    captures, silhouettes = {}, {}
    for root in args.capture:
        manifest = root / "geometry.json"
        config = json.loads(manifest.read_text(encoding="utf-8"))
        frames, outlines = {}, {}
        for view in config["views"]:
            directory = view["directory"]
            frames[directory], outlines[directory] = frame_features(
                root / directory, view, config["width"], config["height"],
                measure_silhouette=args.silhouette_out is not None)
        capture_id = digest(manifest)
        captures[capture_id] = frames
        if args.silhouette_out:
            silhouettes[capture_id] = outlines
        print(f"{root}: {len(frames)} frames, {sum(map(len, frames.values()))} swaps", flush=True)
    result = {"features": VISIBILITY_FIELDS, "captures": captures}
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if args.silhouette_out:
        labels = {"metric": SILHOUETTE_METRIC, "captures": silhouettes}
        args.silhouette_out.write_text(json.dumps(labels, indent=2, allow_nan=False) + "\n",
                                       encoding="utf-8")


if __name__ == "__main__":
    main()
