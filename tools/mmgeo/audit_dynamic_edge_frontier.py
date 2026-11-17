#!/usr/bin/env python3
"""Separate refreshed placements from newly created edges in dynamic image simplification.

Both policies recapture and rescore every currently legal visible Corner placement after each
collapse. ``all-current-edges`` accepts every captured edge. ``initial-edge-frontier`` accepts
only current edges whose endpoint identities descend from an edge in the initial mesh. This
keeps placements and local legality current while testing whether newly created adjacencies help.
The experiment is geometry-only and makes no novelty or production-quality claim.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def load_module(name, filename):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


depth = load_module("edge_frontier_depth", "depth_candidate_pilot.py")
multi = load_module("edge_frontier_multi", "audit_multi_collapse_interactions.py")
recapture = load_module("edge_frontier_recapture", "audit_dynamic_recapture.py")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def directed_edges(faces):
    result = set()
    for a, b, c in faces:
        for x, y in ((a, b), (b, c), (c, a)):
            result.add((int(x), int(y)))
            result.add((int(y), int(x)))
    return result


def find_visible_candidates(positions, faces, candidates, transform, size, scale):
    projected = depth.project(positions, transform)
    _, owners = depth.raster(projected, faces, recapture.valid_faces(faces),
            (0, 0, size, size), scale)
    visible = set(np.unique(owners[owners >= 0]).tolist())
    return [i for i, candidate in enumerate(candidates)
            if visible.intersection(candidate["affected"])]


def resolve(parent, label):
    label = int(label)
    root = label
    while int(parent[root]) != root:
        root = int(parent[root])
    while int(parent[label]) != label:
        next_label = int(parent[label])
        parent[label] = root
        label = next_label
    return root


def remap_labels(old_positions, old_faces, old_labels, new_positions):
    active = np.unique(old_faces[recapture.valid_faces(old_faces)])
    active_positions = old_positions[active]
    active_labels = old_labels[active]
    if not len(new_positions) or not len(active_positions):
        raise AssertionError("recapture produced an empty mesh")
    delta = new_positions[:, None, :] - active_positions[None, :, :]
    distance2 = np.einsum("nvc,nvc->nv", delta, delta)
    order = np.argsort(distance2, axis=1)
    nearest = order[:, 0]
    scale = max(1.0, float(np.linalg.norm(np.ptp(old_positions, axis=0))))
    max_distance = float(np.sqrt(distance2[np.arange(len(new_positions)), nearest].max()))
    if max_distance > 2e-6 * scale:
        raise AssertionError(f"OBJ recapture vertex remap drifted by {max_distance}")
    if distance2.shape[1] > 1:
        first = distance2[np.arange(len(new_positions)), order[:, 0]]
        second = distance2[np.arange(len(new_positions)), order[:, 1]]
        if np.any(second - first < (1e-12 * scale * scale)):
            raise AssertionError("recapture vertex identity is ambiguous at coincident positions")
    return active_labels[nearest].copy(), max_distance


def topology_passes(positions, faces, alive, source_topology):
    current = multi.topology_summary(positions, faces[alive])
    keys = ("eulerCharacteristic", "connectedComponents", "closedTwoManifold",
            "orientationConsistent", "duplicateFaces", "zeroAreaFaces")
    same = all(current[k] == source_topology[k] for k in keys)
    same &= bool(np.sign(current["signedVolume"]) == np.sign(source_topology["signedVolume"]))
    return same, current


def run_policy(name, source_positions, source_faces, initial_candidates, initial_edges,
               transform, original_raw, source_topology, args):
    positions = source_positions.copy()
    faces = source_faces.copy()
    labels = np.arange(len(positions), dtype=np.int64)
    parent = np.arange(len(positions), dtype=np.int64)
    candidates = initial_candidates
    rows = []
    total_capture = 0.0
    output_dir = args.out / name
    output_dir.mkdir(parents=True, exist_ok=True)

    for step in range(args.steps):
        step_start = time.perf_counter()
        current_raw, current_residual = recapture.full_residual(positions, faces,
                transform, original_raw, args.size, args.scale, args.sigma)
        visible_ids = find_visible_candidates(positions, faces, candidates, transform,
                args.size, args.scale)
        if name == "initial-edge-frontier":
            visible_ids = [cid for cid in visible_ids
                    if (resolve(parent, labels[candidates[cid]["remove"]]),
                        resolve(parent, labels[candidates[cid]["keep"]])) in initial_edges]

        best = None
        for cid in visible_ids:
            candidate = candidates[cid]
            result = recapture.evaluate_candidate(positions, faces, current_raw,
                    current_residual, candidate, transform, args.size, args.scale, args.sigma)
            if result is None:
                continue
            score, proposal, changed, rect = result
            key = (score, float(candidate["priority"]), int(cid))
            if best is None or key < best[0]:
                best = (key, cid, proposal, changed, rect)
        if best is None:
            raise RuntimeError(f"{name} has no visible legal candidate at step {step}")

        _, cid, predicted_residual, changed, rect = best
        candidate = candidates[cid]
        p2, f2, alive2 = changed
        removed = int(np.count_nonzero(~alive2) -
                np.count_nonzero(~recapture.valid_faces(faces)))
        if removed != 2:
            raise AssertionError(f"{name} step {step} removed {removed} triangles")
        topology_ok, topology = topology_passes(p2, f2, alive2, source_topology)
        if not topology_ok:
            raise AssertionError(f"{name} step {step} failed topology: {topology}")
        actual_raw, actual_residual = recapture.full_residual(p2, f2, transform,
                original_raw, args.size, args.scale, args.sigma)
        patch_gap = float(np.max(np.abs(predicted_residual - actual_residual)))
        if patch_gap > 1e-9:
            raise AssertionError(f"patch/full mismatch {patch_gap} at {name} step {step}")

        remove_label = resolve(parent, labels[int(candidate["remove"])])
        keep_label = resolve(parent, labels[int(candidate["keep"])])
        if remove_label == keep_label:
            raise AssertionError("selected candidate aliases both endpoints")
        parent[remove_label] = keep_label

        obj_path = output_dir / f"step-{step:03d}.obj"
        json_path = output_dir / f"step-{step:03d}.json"
        recapture.dump_obj(obj_path, p2, f2, alive2)
        capture_seconds, capture_log = recapture.capture_obj(args.executable, obj_path, json_path)
        new_positions, new_faces, new_candidates = depth.load_capture(json_path)
        labels2, remap_gap = remap_labels(p2, f2, labels, new_positions)
        round_raw, _ = recapture.full_residual(new_positions, new_faces, transform,
                original_raw, args.size, args.scale, args.sigma)
        roundtrip_gap = float(np.max(np.abs(round_raw - actual_raw)))
        if roundtrip_gap > 1e-10:
            raise AssertionError(f"OBJ recapture changed raster by {roundtrip_gap}")

        if name == "initial-edge-frontier":
            next_eligible = sum((resolve(parent, labels2[c["remove"]]),
                    resolve(parent, labels2[c["keep"]])) in initial_edges
                    for c in new_candidates)
        else:
            next_eligible = len(new_candidates)
        row = {"step": step, "currentLegalCandidates": len(candidates),
                "visibleCandidatesScored": len(visible_ids),
                "nextLegalCandidates": len(new_candidates),
                "nextEligibleCandidates": int(next_eligible),
                "selectedId": int(cid), "selectedRemove": int(candidate["remove"]),
                "selectedKeep": int(candidate["keep"]),
                "selectedStableEndpoints": [remove_label, keep_label],
                "selectedTarget": list(map(float, candidate["target"])),
                "removedTriangles": removed,
                "filteredSse": float(np.square(actual_residual).sum()),
                "patchVsFullMaxAbsoluteDifference": patch_gap,
                "recaptureRasterMaxDifference": roundtrip_gap,
                "vertexIdentityRemapMaxDistance": remap_gap,
                "captureSeconds": capture_seconds, "captureLog": capture_log[-500:],
                "topology": topology,
                "stepSeconds": time.perf_counter() - step_start}
        rows.append(row)
        total_capture += capture_seconds
        positions, faces, labels, candidates = new_positions, new_faces, labels2, new_candidates
        print(name, "step", step + 1, "faces", int(len(faces)), "SSE",
                f"{row['filteredSse']:.8g}", "scored", len(visible_ids), flush=True)

    _, residual = recapture.full_residual(positions, faces, transform, original_raw,
            args.size, args.scale, args.sigma)
    return {"steps": rows, "finalFaces": int(len(faces)),
            "finalFilteredSse": float(np.square(residual).sum()),
            "totalSelectionCaptureAndRerenderSeconds": float(sum(r["stepSeconds"] for r in rows)),
            "totalCaptureSeconds": total_capture,
            "finalTopology": multi.topology_summary(positions,
                    faces[recapture.valid_faces(faces)])}, (positions, faces)


def run(args):
    args.out.mkdir(parents=True, exist_ok=True)
    original_positions, original_faces, _ = depth.load_capture(args.capture)
    source_topology = multi.topology_summary(original_positions, original_faces)
    transform = depth.camera(original_positions, args.angle, args.size)
    source_raw, _ = depth.raster(depth.project(original_positions, transform),
            original_faces, recapture.valid_faces(original_faces),
            (0, 0, args.size, args.size), args.scale)

    initial_obj = args.out / "initial.obj"
    initial_json = args.out / "initial.json"
    recapture.dump_obj(initial_obj, original_positions, original_faces)
    initial_capture_seconds, initial_log = recapture.capture_obj(args.executable,
            initial_obj, initial_json)
    positions, faces, candidates = depth.load_capture(initial_json)
    roundtrip_raw, _ = recapture.full_residual(positions, faces, transform,
            source_raw, args.size, args.scale, args.sigma)
    initial_gap = float(np.max(np.abs(roundtrip_raw - source_raw)))
    if initial_gap > 1e-10:
        raise AssertionError(f"initial OBJ roundtrip changed raster by {initial_gap}")
    edges = directed_edges(faces)

    report = {"scope": "single fitted view; geometry-only coverage and normalized depth; full current legal visible candidates; no PBR or runtime claim",
            "comparison": "both policies recapture all current legal candidates and placements after each edit; only all-current-edges may use edges absent from the initial mesh",
            "settings": {"angleRadians": args.angle, "imageSize": args.size,
                    "supersample": args.scale, "gaussianSigma": args.sigma,
                    "collapseSteps": args.steps,
                    "initialDirectedEdgeCount": len(edges)},
            "sourceTriangles": int(len(original_faces)),
            "sourceTopology": source_topology,
            "initialRoundtrip": {"seconds": initial_capture_seconds,
                    "maxRawImageDifference": initial_gap,
                    "legalCandidates": len(candidates), "captureLog": initial_log[-1000:]},
            "hashes": {"capture": sha256(args.capture),
                    "captureExecutable": sha256(args.executable),
                    "script": sha256(Path(__file__)),
                    "depthRenderer": sha256(Path(depth.__file__))},
            "policies": {}}

    final_states = {}
    for name in ("initial-edge-frontier", "all-current-edges"):
        result, state = run_policy(name, positions, faces, candidates, edges, transform,
                source_raw, source_topology, args)
        report["policies"][name] = result
        final_states[name] = state

    holdout = recapture.holdout_views(original_positions, original_faces, final_states,
            args.audit_size, args.audit_scale, args.sigma, args.angle)
    edge_score = holdout["initial-edge-frontier"]["sumFilteredSse"]
    all_score = holdout["all-current-edges"]["sumFilteredSse"]
    report["finalMultiViewAudit"] = {"size": args.audit_size,
            "supersample": args.audit_scale, "sigma": args.sigma,
            "views": [row["view"] for row in holdout["initial-edge-frontier"]["views"]],
            "policies": holdout,
            "allCurrentEdgesImprovementPercent": 100.0 * (edge_score - all_score) /
                    max(edge_score, 1e-30)}
    report["singleViewComparison"] = {
            "allCurrentEdgesImprovementPercent": 100.0 *
                    (report["policies"]["initial-edge-frontier"]["finalFilteredSse"] -
                     report["policies"]["all-current-edges"]["finalFilteredSse"]) /
                    max(report["policies"]["initial-edge-frontier"]["finalFilteredSse"],
                        1e-30)}
    report_path = args.out / "dynamic-edge-frontier-audit.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path),
            "singleView": report["singleViewComparison"],
            "multiViewImprovement": report["finalMultiViewAudit"][
                    "allCurrentEdgesImprovementPercent"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--size", type=int, default=96)
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--sigma", type=float, default=0.9)
    parser.add_argument("--angle", type=float, default=2.25)
    parser.add_argument("--audit-size", type=int, default=128)
    parser.add_argument("--audit-scale", type=int, default=3)
    args = parser.parse_args()
    if min(args.steps, args.size, args.scale) < 1:
        parser.error("steps, size, and scale must be positive")
    run(args)


if __name__ == "__main__":
    main()
