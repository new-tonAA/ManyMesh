"""CPU-only research sidecar decoder for boundary-locked triangle clusters.

This polynomial decoder is a mechanical control, not a trained neural method.
It accepts geometry only; authored attributes and global intersection checks are
outside this prototype. No production file format or renderer is involved.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time

import numpy as np


VERSION = 1
FEATURES = 10


def integer_array(value, shape, name):
    array = np.asarray(value)
    if array.ndim != len(shape) or any(n is not None and array.shape[i] != n
                                        for i, n in enumerate(shape)):
        raise ValueError(f"Invalid {name} shape: {array.shape}")
    if array.dtype.kind not in "iu" or np.any(array < 0):
        raise ValueError(f"{name} must contain nonnegative integers")
    if array.size and int(array.max()) > np.iinfo(np.int64).max:
        raise ValueError(f"{name} exceeds int64 range")
    return np.array(array, dtype=np.int64, copy=True)


def finite_array(value, shape, name):
    array = np.asarray(value)
    if array.dtype.kind not in "fiu" or array.ndim != len(shape) or any(
            n is not None and array.shape[i] != n for i, n in enumerate(shape)):
        raise ValueError(f"Invalid {name}")
    result = np.array(array, dtype=np.float64, copy=True)
    if not np.isfinite(result).all():
        raise ValueError(f"Nonfinite {name}")
    return result


def array_hash(*arrays):
    digest = hashlib.sha256()
    for array in arrays:
        array = np.ascontiguousarray(array)
        digest.update(str((array.dtype.str, array.shape)).encode("ascii"))
        digest.update(array.tobytes())
    return digest.hexdigest()


@dataclass
class Mesh:
    positions: np.ndarray
    triangles: np.ndarray
    face_clusters: np.ndarray

    def checked(self):
        positions = finite_array(self.positions, (None, 3), "positions")
        triangles = integer_array(self.triangles, (None, 3), "triangles")
        clusters = integer_array(self.face_clusters, (len(triangles),), "face clusters")
        if not len(triangles) or not len(positions) or triangles.max() >= len(positions):
            raise ValueError("Empty mesh or triangle index out of bounds")
        unique = np.unique(clusters)
        if unique[0] != 0 or unique[-1] != len(unique) - 1:
            raise ValueError("Cluster IDs must be dense starting at zero")
        if len(np.unique(triangles)) != len(positions):
            raise ValueError("Remove unused vertices before sidecar encoding")
        mesh = Mesh(positions, triangles, clusters)
        topology(mesh)
        return mesh

    def digest(self):
        return array_hash(self.positions.astype("<f8"), self.triangles.astype("<i8"),
                          self.face_clusters.astype("<i8"))


def topology(mesh):
    """Audit welded edges/faces and retain directed boundary positions per cluster."""
    canonical, inverse = np.unique(mesh.positions, axis=0, return_inverse=True)
    faces = inverse[mesh.triangles]
    points = mesh.positions[mesh.triangles]
    normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    if np.any(np.linalg.norm(normals, axis=1) == 0):
        raise ValueError("Degenerate triangle")
    if len(np.unique(np.sort(faces, axis=1), axis=0)) != len(faces):
        raise ValueError("Duplicate geometric triangle")
    edges = {}
    local = {}
    owners = [set() for _ in canonical]
    for face, cluster in zip(faces, mesh.face_clusters):
        cluster = int(cluster)
        for vertex in face:
            owners[int(vertex)].add(cluster)
        for u, v in zip(face, np.roll(face, -1)):
            u, v = int(u), int(v)
            key = (min(u, v), max(u, v))
            edges.setdefault(key, []).append((u, v))
            local.setdefault((cluster, *key), []).append((u, v))
    for incident in edges.values():
        if len(incident) > 2 or (len(incident) == 2 and incident[0] != incident[1][::-1]):
            raise ValueError("Nonmanifold or inconsistently oriented edge")
    locked = np.array([len(group) > 1 for group in owners])
    # Duplicate raw positions can encode a chart seam, even within one cluster.
    locked |= np.bincount(inverse, minlength=len(canonical)) > 1
    for (u, v), incident in edges.items():
        if len(incident) == 1:
            locked[[u, v]] = True
    boundary = []
    for (cluster, _, _), incident in local.items():
        if len(incident) == 1:
            u, v = incident[0]
            boundary.append((cluster, tuple(canonical[u]), tuple(canonical[v])))
    return locked[inverse], tuple(sorted(boundary)), normals


def features(points):
    x, y, z = points.T
    return np.column_stack((np.ones(len(points)), x, y, z, x*x, x*y, x*z, y*y, y*z, z*z))


@dataclass
class Model:
    weights: np.ndarray  # [polynomial feature, latent channel, xyz]
    max_offset: float = 0.1  # Fraction of cluster bounding radius.

    def checked(self):
        weights = finite_array(self.weights, (FEATURES, None, 3), "model weights")
        if weights.shape[1] == 0 or not np.isfinite(self.max_offset) or self.max_offset <= 0:
            raise ValueError("Invalid latent width or offset cap")
        # Persist the exact float32 representation used for encoding and decoding.
        weights = weights.astype(np.float32)
        if not np.isfinite(weights).all():
            raise ValueError("Model overflows float32")
        return Model(weights, float(self.max_offset))

    def digest(self):
        return array_hash(self.weights.astype("<f4"), np.array([self.max_offset], dtype="<f8"))


def write_sidecar(path, mesh, model, latent, refine_faces=()):
    mesh, model = mesh.checked(), model.checked()
    latent = finite_array(latent, (int(mesh.face_clusters.max()) + 1,
                                  model.weights.shape[1]), "latents").astype(np.float32)
    if not np.isfinite(latent).all():
        raise ValueError("Latents overflow float32")
    refine = integer_array(np.asarray(refine_faces, dtype=np.int64) if len(refine_faces) == 0
                           else refine_faces, (None,), "refinement faces")
    if len(np.unique(refine)) != len(refine) or (len(refine) and refine.max() >= len(mesh.triangles)):
        raise ValueError("Repeated or out-of-range refinement face")
    metadata = {"version": VERSION, "mesh_sha256": mesh.digest(),
                "model_sha256": model.digest(), "latent_dtype": "float32"}
    # File handle prevents NumPy silently appending .npz to the requested sidecar name.
    with Path(path).open("wb") as stream:
        np.savez(stream, metadata=np.frombuffer(json.dumps(metadata, sort_keys=True).encode(),
                                              dtype=np.uint8),
                 latent=latent, refine_faces=refine)


def decode(mesh, model, sidecar, triangle_budget):
    """Decode once; reject outputs violating the local mechanical contract.

    This validates oriented edge topology and local normal flips, not global
    self-intersections, vertex-link manifoldness, or reference-surface error.
    """
    start = time.perf_counter()
    mesh, model = mesh.checked(), model.checked()
    if isinstance(triangle_budget, bool) or not isinstance(triangle_budget, (int, np.integer)):
        raise ValueError("Triangle budget must be an integer")
    with np.load(sidecar, allow_pickle=False) as archive:
        meta = json.loads(archive["metadata"].tobytes().decode("utf-8"))
        if meta != {"version": VERSION, "mesh_sha256": mesh.digest(),
                    "model_sha256": model.digest(), "latent_dtype": "float32"}:
            raise ValueError("Sidecar version, input mesh, or model mismatch")
        if archive["latent"].dtype != np.float32:
            raise ValueError("Sidecar latent storage must be float32")
        latent = finite_array(archive["latent"], (int(mesh.face_clusters.max()) + 1,
                                                 model.weights.shape[1]), "latents")
        refine = integer_array(archive["refine_faces"], (None,), "refinement faces")
    if len(np.unique(refine)) != len(refine) or (len(refine) and refine.max() >= len(mesh.triangles)):
        raise ValueError("Repeated or out-of-range refinement face")
    expected = len(mesh.triangles) + 2 * len(refine)
    if expected > triangle_budget:
        raise ValueError(f"Decoded {expected} triangles exceed budget {triangle_budget}")
    locked, boundary, original_normals = topology(mesh)
    positions = np.array(mesh.positions, copy=True)
    centroids = mesh.positions[mesh.triangles[refine]].mean(axis=1)
    inserted = np.array(centroids, copy=True)
    for cluster in range(len(latent)):
        ids = np.unique(mesh.triangles[mesh.face_clusters == cluster])
        points = mesh.positions[ids]
        origin = (points.min(axis=0) + points.max(axis=0)) * 0.5
        radius = np.linalg.norm(points - origin, axis=1).max()
        if not np.isfinite(radius) or radius <= 0:
            raise ValueError("Invalid cluster scale")
        free = ids[~locked[ids]]
        added = np.flatnonzero(mesh.face_clusters[refine] == cluster)
        query = np.concatenate((mesh.positions[free], centroids[added]))
        coefficients = np.einsum("flc,l->fc", model.weights.astype(np.float64), latent[cluster])
        offset = features((query - origin) / radius) @ coefficients
        if not np.isfinite(offset).all() or np.any(np.linalg.norm(offset, axis=1) > model.max_offset):
            raise ValueError("Predicted displacement exceeds normalized offset cap")
        positions[free] += offset[:len(free)] * radius
        inserted[added] += offset[len(free):] * radius
    positions = np.concatenate((positions, inserted))
    refine_lookup = {int(face): len(mesh.positions) + i for i, face in enumerate(refine)}
    triangles, clusters, parents = [], [], []
    for face_id, (face, cluster) in enumerate(zip(mesh.triangles, mesh.face_clusters)):
        if face_id in refine_lookup:
            a, b, c = face
            center = refine_lookup[face_id]
            emitted = ((a, b, center), (b, c, center), (c, a, center))
        else:
            emitted = (face,)
        triangles.extend(emitted)
        clusters.extend([cluster] * len(emitted))
        parents.extend([face_id] * len(emitted))
    result = Mesh(positions, np.asarray(triangles, dtype=np.int64),
                  np.asarray(clusters, dtype=np.int64)).checked()
    _, new_boundary, normals = topology(result)
    if not np.array_equal(result.positions[:len(mesh.positions)][locked], mesh.positions[locked]):
        raise ValueError("Locked vertex moved")
    if boundary != new_boundary:
        raise ValueError("Cluster boundary changed")
    if np.any(np.einsum("ij,ij->i", normals, original_normals[parents]) <= 0):
        raise ValueError("Local triangle flip relative to source")
    report = {"triangles": len(result.triangles), "added_triangles": 2 * len(refine),
              "vertices": len(result.positions), "locked_vertices": int(locked.sum()),
              "sidecar_bytes": Path(sidecar).stat().st_size,
              "model_weight_bytes": model.weights.nbytes,
              "decoded_array_bytes": sum(x.nbytes for x in (result.positions, result.triangles,
                                                            result.face_clusters)),
              "decode_seconds": time.perf_counter() - start,
              "boundary_preserved": True, "global_intersections_checked": False}
    return result, report
