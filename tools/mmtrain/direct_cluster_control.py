"""Direct float32 displacement sidecar control for the geometry-only pilot."""

import json
from pathlib import Path
import time

import numpy as np

from cluster_decoder import Mesh, finite_array, integer_array, topology


def encode_direct(path, mesh, displacement, refine):
    mesh = mesh.checked()
    locked = topology(mesh)[0]
    refine = integer_array(refine, (None,), "refinement faces")
    if len(np.unique(refine)) != len(refine) or (len(refine) and refine.max() >= len(mesh.triangles)):
        raise ValueError("Invalid refinement faces")
    displacement = finite_array(displacement, (int((~locked).sum()) + len(refine), 3),
                                "direct displacement").astype(np.float32)
    if not np.isfinite(displacement).all():
        raise ValueError("Direct displacement overflows float32")
    metadata = {"version": 1, "kind": "direct-float32", "mesh_sha256": mesh.digest()}
    with Path(path).open("wb") as stream:
        np.savez(stream, displacement=displacement, refine_faces=refine,
                 metadata=np.frombuffer(json.dumps(metadata, sort_keys=True).encode(), dtype=np.uint8))


def decode_direct(mesh, path, budget, max_offset=.1):
    start = time.perf_counter()
    if (isinstance(budget, bool) or not isinstance(budget, (int, np.integer))
            or not np.isfinite(max_offset) or max_offset <= 0):
        raise ValueError("Invalid direct decoder budget or offset cap")
    mesh = mesh.checked()
    locked, boundary, before = topology(mesh)
    free = np.flatnonzero(~locked)
    with np.load(path, allow_pickle=False) as archive:
        metadata = json.loads(archive["metadata"].tobytes().decode())
        if metadata != {"version": 1, "kind": "direct-float32", "mesh_sha256": mesh.digest()}:
            raise ValueError("Direct sidecar input mismatch")
        refine = integer_array(archive["refine_faces"], (None,), "refinement faces")
        if archive["displacement"].dtype != np.float32:
            raise ValueError("Direct sidecar requires float32 storage")
        offsets = finite_array(archive["displacement"], (len(free)+len(refine), 3), "offsets")
    if len(np.unique(refine)) != len(refine) or (len(refine) and refine.max() >= len(mesh.triangles)):
        raise ValueError("Invalid refinement faces")
    if len(mesh.triangles) + 2*len(refine) > budget:
        raise ValueError("Direct output exceeds budget")
    owners = np.full(len(mesh.positions), -1, dtype=np.int64)
    for face, cluster in zip(mesh.triangles, mesh.face_clusters):
        owners[face] = cluster
    groups = np.concatenate((owners[free], mesh.face_clusters[refine]))
    for cluster in range(int(mesh.face_clusters.max())+1):
        points = mesh.positions[np.unique(mesh.triangles[mesh.face_clusters == cluster])]
        center = (points.min(axis=0)+points.max(axis=0))*.5
        radius = np.linalg.norm(points-center, axis=1).max()
        if np.any(np.linalg.norm(offsets[groups == cluster], axis=1) > max_offset*radius):
            raise ValueError("Direct displacement exceeds normalized offset cap")
    positions = mesh.positions.copy()
    positions[free] += offsets[:len(free)]
    added = mesh.positions[mesh.triangles[refine]].mean(axis=1) + offsets[len(free):]
    positions = np.concatenate((positions, added))
    lookup = {int(face): len(mesh.positions)+i for i, face in enumerate(refine)}
    faces, clusters, parents = [], [], []
    for index, (face, cluster) in enumerate(zip(mesh.triangles, mesh.face_clusters)):
        if index in lookup:
            a, b, c = face
            center = lookup[index]
            emitted = ((a, b, center), (b, c, center), (c, a, center))
        else:
            emitted = (face,)
        faces.extend(emitted)
        clusters.extend([cluster]*len(emitted))
        parents.extend([index]*len(emitted))
    result = Mesh(positions, np.asarray(faces, dtype=np.int64),
                  np.asarray(clusters, dtype=np.int64)).checked()
    _, after_boundary, normals = topology(result)
    if boundary != after_boundary or not np.array_equal(result.positions[:len(mesh.positions)][locked],
                                                       mesh.positions[locked]):
        raise ValueError("Direct displacement changed boundaries")
    if np.any(np.sum(normals*before[parents], axis=1) <= 0):
        raise ValueError("Direct displacement caused local flip")
    return result, {"sidecar_bytes": Path(path).stat().st_size,
                    "decode_seconds": time.perf_counter()-start,
                    "triangles": len(result.triangles), "boundary_preserved": True,
                    "global_intersections_checked": False}
