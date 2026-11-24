#!/usr/bin/env python3
"""Audit closed-manifold topology for one frozen source and cluster cut."""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools" / "mmgeo"))
from audit_obj_contract_floor import component_floor  # noqa: E402
from bench_component_gpu import load_export  # noqa: E402


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def connected_face_components(faces: np.ndarray) -> list[np.ndarray]:
    edge_faces: dict[tuple[int, int], list[int]] = defaultdict(list)
    for face_id, face in enumerate(faces):
        for start, end in zip(face, np.roll(face, -1)):
            a, b = int(start), int(end)
            edge_faces[(min(a, b), max(a, b))].append(face_id)

    parent = list(range(len(faces)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    for incident in edge_faces.values():
        if len(incident) < 2:
            continue
        root = find(incident[0])
        for face_id in incident[1:]:
            other = find(face_id)
            if root != other:
                parent[other] = root

    groups: dict[int, list[int]] = defaultdict(list)
    for face_id in range(len(faces)):
        groups[find(face_id)].append(face_id)
    return [faces[ids] for ids in groups.values()]


def audit_mesh(faces: np.ndarray) -> dict[str, object]:
    components = [
        component_floor([tuple(map(int, face)) for face in group])
        for group in connected_face_components(faces)
    ]
    components.sort(key=lambda item: (item["chi"], item["triangles"]))
    signature = [
        {key: item[key] for key in ("chi", "orientable")}
        for item in components
    ]
    return {
        "supported_closed_manifold": all(
            item["supported"] and item["boundary_edges"] == 0 for item in components
        ),
        "components": components,
        "topology_signature": signature,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--meshes", type=Path, required=True)
    parser.add_argument("--stock", type=Path, required=True)
    parser.add_argument("--asset", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    stock_path = args.stock / "cluster-cuts.json"
    stock_bytes = stock_path.read_bytes()
    stock = json.loads(stock_bytes)
    if stock["manifest_sha256"] != sha256(manifest_bytes):
        raise ValueError("Stock cut manifest does not match the geometry manifest")
    if args.asset not in manifest["assets"] or args.asset not in stock["assets"]:
        raise ValueError(f"Asset is missing from a frozen manifest: {args.asset}")

    spec = manifest["assets"][args.asset]["exports"]["source"]
    source_path = args.meshes / args.asset / "source.ply"
    vertex_data, source_indices = load_export(source_path, spec)
    positions = vertex_data.reshape(-1, 6)[:, :3]
    _, vertex_map = np.unique(positions, axis=0, return_inverse=True)
    source_faces = vertex_map[source_indices.reshape(-1, 3)]

    cut_info = stock["assets"][args.asset]["cuts"]["cluster2"]
    cut_path = args.stock / args.asset / "cluster-depth2.npy"
    cut_bytes = cut_path.read_bytes()
    if sha256(cut_bytes) != cut_info["sha256"]:
        raise ValueError("Cluster cut bytes do not match the frozen stock manifest")
    cut_indices = np.load(cut_path, allow_pickle=False)
    if (cut_indices.dtype != np.uint32
            or cut_indices.shape != (3 * cut_info["count"],)
            or cut_indices.max() >= len(vertex_map)):
        raise ValueError("Cluster cut has an invalid dtype, count, or vertex index")
    cut_faces = vertex_map[cut_indices.reshape(-1, 3)]

    source_audit = audit_mesh(source_faces)
    cut_audit = audit_mesh(cut_faces)
    same_signature = (
        source_audit["topology_signature"] == cut_audit["topology_signature"]
    )
    receipt = {
        "schema": 1,
        "asset": args.asset,
        "license": "CC0-1.0; see the pinned source-list record in the benchmark receipts",
        "manifest_sha256": sha256(manifest_bytes),
        "stock_manifest_sha256": sha256(stock_bytes),
        "source_mesh_sha256": spec["sha256"],
        "cluster2_indices_sha256": cut_info["sha256"],
        "position_welding": "exact float32 xyz coordinate equality",
        "source": source_audit,
        "cluster2": cut_audit,
        "same_closed_orientable_component_signature": same_signature,
        "eligible_for_combinatorial_topology_comparison": (
            source_audit["supported_closed_manifold"]
            and cut_audit["supported_closed_manifold"]
            and same_signature
        ),
        "limitations": [
            "Does not test geometric self-intersections or near-coincident seams.",
            "Does not compare surface distance, attributes, or image quality.",
        ],
        "audit_script_sha256": sha256(Path(__file__).read_bytes()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    args.output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "source_components": source_audit["topology_signature"],
        "cluster2_components": cut_audit["topology_signature"],
        "eligible": receipt["eligible_for_combinatorial_topology_comparison"],
        "limitations": receipt["limitations"],
    }, indent=2))


if __name__ == "__main__":
    main()
