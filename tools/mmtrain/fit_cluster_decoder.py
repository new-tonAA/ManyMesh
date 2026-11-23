"""Fit a shared low-rank polynomial residual control on training meshes only.

Per-asset encoding may read the high-detail source, as a compression encoder does.
This is a linear learned subspace control, not a neural or render-quality result.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cluster_decoder import FEATURES, Mesh, Model, decode, write_sidecar
from cluster_decoder_pilot import peak_process_bytes
from direct_cluster_control import encode_direct, decode_direct


def solve_ridge(design, target, ridge):
    if (not np.isfinite(design).all() or not np.isfinite(target).all()
            or not np.isfinite(ridge) or ridge <= 0):
        raise ValueError("Invalid regression input or regularizer")
    if not len(design):
        return np.zeros((design.shape[1], target.shape[1]), dtype=np.float64)
    return np.linalg.solve(design.T @ design / len(design) + ridge*np.eye(design.shape[1]),
                           design.T @ target / len(design))


def load_pair(root, record):
    path = root / record["file"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError("Prepared-pair hash mismatch")
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key] for key in archive.files}


def learn_basis(pairs, rank, ridge, mode):
    coefficients, asset_weights = [], []
    for pair in pairs:
        end = len(pair["free_vertices"]) if mode == "fixed" else len(pair["queries"])
        rows = []
        for cluster in np.unique(pair["query_clusters"][:end]):
            mask = pair["query_clusters"][:end] == cluster
            rows.append(solve_ridge(pair["features"][:end][mask], pair["offsets"][:end][mask],
                                    ridge).reshape(-1))
        if rows:
            coefficients.extend(rows)
            asset_weights.extend([1 / np.sqrt(len(rows))] * len(rows))
    if len(coefficients) < rank or not 1 <= rank <= FEATURES * 3:
        raise ValueError("Insufficient training clusters for requested subspace rank")
    weighted = np.asarray(coefficients) * np.asarray(asset_weights)[:, None]
    _, singular, directions = np.linalg.svd(weighted, full_matrices=False)
    weights = directions[:rank].reshape(rank, FEATURES, 3).transpose(1, 0, 2)
    return Model(weights.astype(np.float32)), singular


def encode_pair(pair, model, ridge, refinement_fraction):
    free_count = len(pair["free_vertices"])
    count = int(len(pair["triangles"]) * refinement_fraction)
    # Offline source-aware encoder selection, not a runtime refinement predictor.
    errors = np.sum((pair["queries"][free_count:] - pair["targets"][free_count:])**2, axis=1)
    refine = np.argsort(-errors, kind="stable")[:count]
    ids = np.concatenate((np.arange(free_count), free_count + refine))
    latent = np.zeros((int(pair["face_clusters"].max()) + 1, model.weights.shape[1]),
                      dtype=np.float32)
    squared_error = 0.
    target_energy = 0.
    for cluster in range(len(latent)):
        selected = ids[pair["query_clusters"][ids] == cluster]
        design = np.einsum("nf,fkc->nck", pair["features"][selected], model.weights)
        design = design.reshape(-1, model.weights.shape[1])
        target = pair["offsets"][selected].reshape(-1, 1)
        latent[cluster] = solve_ridge(design, target, ridge).ravel()
        predicted = design @ latent[cluster]
        squared_error += float(np.sum((predicted - target.ravel())**2))
        target_energy += float(np.sum(target**2))
    return latent, refine, {"normalized_label_sse": squared_error,
                             "zero_residual_label_sse": target_energy,
                             "fitted_query_count": len(ids)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pairs", type=Path, help="Training pair manifest")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rank", type=int, default=8, choices=(4, 8, 16, 30))
    parser.add_argument("--ridge", type=float, default=1e-5)
    parser.add_argument("--refinement-fraction", type=float, default=.1)
    args = parser.parse_args()
    if not np.isfinite(args.ridge) or args.ridge <= 0 or not 0 <= args.refinement_fraction <= 1:
        parser.error("Invalid regularizer or refinement fraction")
    manifest = json.loads(args.pairs.read_text(encoding="utf-8"))
    if any(row["source"]["split"] != "train" for row in manifest["records"]):
        raise ValueError("Shared basis fitting accepts only the training split")
    prepared = [row for row in manifest["records"] if row["status"] == "prepared"]
    args.out.mkdir(parents=True, exist_ok=True)
    # The bounded pilot is small; report the actual process peak including these arrays.
    pairs = [load_pair(args.pairs.parent, row) for row in prepared]
    report = {"scope": "Training subspace fit and mechanical decoding; no held-out quality claim",
              "source_manifest_sha256": hashlib.sha256(args.pairs.read_bytes()).hexdigest(),
              "preparation_failures": [row for row in manifest["records"] if row["status"] != "prepared"],
              "rank": args.rank, "ridge": args.ridge, "modes": {}}
    for mode in ("fixed", "refine"):
        folder = args.out / mode
        folder.mkdir(exist_ok=True)
        start = time.perf_counter()
        model, singular = learn_basis(pairs, args.rank, args.ridge, mode)
        path = folder / "model.npz"
        np.savez(path, weights=model.weights, max_offset=np.array(model.max_offset))
        with np.load(path, allow_pickle=False) as saved:
            model = Model(saved["weights"], float(saved["max_offset"]))
        results = []
        fit_seconds = time.perf_counter() - start
        for pair, row in zip(pairs, prepared):
            item = {"file_id": row["source"]["file_id"]}
            latent, refine, diagnostics = encode_pair(
                pair, model, args.ridge, args.refinement_fraction if mode == "refine" else 0.)
            sidecar = folder / f"{item['file_id']}.sidecar"
            mesh = Mesh(pair["positions"], pair["triangles"], pair["face_clusters"])
            write_sidecar(sidecar, mesh, model, latent, refine)
            item.update(diagnostics)
            item["sidecar_bytes"] = sidecar.stat().st_size
            try:
                decoded, metrics = decode(mesh, model, sidecar, len(mesh.triangles) + 2*len(refine))
                np.savez(folder / f"{item['file_id']}-decoded.npz", positions=decoded.positions,
                         triangles=decoded.triangles, face_clusters=decoded.face_clusters)
                item.update({"status": "decoded", **metrics})
            except ValueError as error:
                item.update({"status": "rejected", "reason": str(error)})
            direct_path = folder / f"{item['file_id']}-direct.sidecar"
            free = len(pair["free_vertices"])
            ids = np.concatenate((np.arange(free), free+refine))
            encode_direct(direct_path, mesh, pair["targets"][ids]-pair["queries"][ids], refine)
            try:
                direct, metrics = decode_direct(mesh, direct_path, len(mesh.triangles)+2*len(refine))
                np.savez(folder / f"{item['file_id']}-direct-decoded.npz", positions=direct.positions,
                         triangles=direct.triangles, face_clusters=direct.face_clusters)
                item["direct_control"] = {"status": "decoded", **metrics}
            except ValueError as error:
                item["direct_control"] = {"status": "rejected", "reason": str(error),
                                           "sidecar_bytes": direct_path.stat().st_size}
            results.append(item)
            print(f"{mode} train {item['file_id']}: {item['status']}", flush=True)
        report["modes"][mode] = {"model_file_bytes": path.stat().st_size,
                                 "basis_fit_seconds": fit_seconds,
                                 "singular_values": singular.tolist(), "records": results}
    report["process_peak_bytes"] = peak_process_bytes()
    (args.out / "report.json").write_bytes((json.dumps(report, indent=2) + "\n").encode())


if __name__ == "__main__":
    main()
