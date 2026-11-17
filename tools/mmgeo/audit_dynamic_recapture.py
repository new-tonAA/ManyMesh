#!/usr/bin/env python3
"""Kill-test greedy view-error selection with fresh Corner candidates per collapse.

This is an offline geometry-only experiment. It compares a sampled initial candidate pool
kept frozen against the same pool size re-captured from the edited mesh after every collapse.
Both policies greedily minimize exact filtered coverage/depth SSE to the original view.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
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


depth = load_module("dynamic_recapture_depth", "depth_candidate_pilot.py")
audit = load_module("dynamic_recapture_multi", "audit_multi_collapse_interactions.py")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def dump_obj(path, positions, faces, valid=None):
    if valid is None:
        valid = np.ones(len(faces), dtype=bool)
    with Path(path).open("w", encoding="ascii", newline="\n") as out:
        out.write("# geometry-only dynamic candidate capture\n")
        for x, y, z in positions:
            out.write(f"v {x:.17g} {y:.17g} {z:.17g}\n")
        for a, b, c in faces[valid]:
            out.write(f"f {int(a)+1} {int(b)+1} {int(c)+1}\n")


def capture_obj(executable, obj_path, json_path):
    start = time.perf_counter()
    proc = subprocess.run([str(executable), str(obj_path), str(json_path)],
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False)
    elapsed = time.perf_counter() - start
    if proc.returncode:
        raise RuntimeError(f"capture failed ({proc.returncode}): {proc.stderr[-4000:]}")
    return elapsed, proc.stderr.strip()


def valid_faces(faces):
    return ((faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) &
            (faces[:, 2] != faces[:, 0]))


def apply_world(positions, faces, candidate):
    changed_positions = positions.copy()
    changed_positions[int(candidate["keep"])] = np.asarray(candidate["target"], dtype=float)
    changed_faces = faces.copy()
    changed_faces[changed_faces == int(candidate["remove"])] = int(candidate["keep"])
    alive = valid_faces(changed_faces)
    removed = int(np.count_nonzero(~alive) - np.count_nonzero(~valid_faces(faces)))
    return changed_positions, changed_faces, alive, removed


def topology_passes(positions, faces, alive, source_topology):
    current = audit.topology_summary(positions, faces[alive])
    keys = ("eulerCharacteristic", "connectedComponents", "closedTwoManifold",
            "orientationConsistent", "duplicateFaces", "zeroAreaFaces")
    same = all(current[k] == source_topology[k] for k in keys)
    same &= bool(np.sign(current["signedVolume"]) == np.sign(source_topology["signedVolume"]))
    return same, current


def sample_candidates(positions, faces, candidates, transform, size, scale, sigma,
                      source_topology, wanted, include_hidden):
    projected = depth.project(positions, transform)
    raw, owners = depth.raster(projected, faces, valid_faces(faces),
            (0, 0, size, size), scale)
    visible = set(np.unique(owners[owners >= 0]).tolist())
    halo = int(np.ceil(4 * sigma)) + 2
    groups = {True: [], False: []}
    rejected = {"outside": 0, "faceBudget": 0, "topology": 0}
    for index, candidate in enumerate(candidates):
        rect = depth.support(projected, faces, candidate, transform, size, halo)
        if rect is None:
            rejected["outside"] += 1
            continue
        p2, f2, alive2, removed = apply_world(positions, faces, candidate)
        if removed != 2:
            rejected["faceBudget"] += 1
            continue
        hidden = not bool(visible.intersection(candidate["affected"]))
        groups[hidden].append((float(candidate["priority"]), index, rect))
    selected = []
    hidden_wanted = max(1, wanted // 4) if include_hidden else 0
    for hidden, count in ((False, wanted), (True, hidden_wanted)):
        if count == 0:
            continue
        group = sorted(groups[hidden])
        if group:
            slots = np.unique(np.linspace(0, len(group) - 1,
                    min(count, len(group))).astype(int))
            selected.extend((hidden, *group[int(slot)]) for slot in slots)
    legal_counts = {"visibleLegal": len(groups[False]), "hiddenLegal": len(groups[True])}
    topology_valid = []
    for row in selected:
        _, index, _ = row[1:]
        p2, f2, alive2, _ = apply_world(positions, faces, candidates[index])
        if topology_passes(p2, f2, alive2, source_topology)[0]:
            topology_valid.append(row)
        else:
            rejected["topology"] += 1
    return topology_valid, raw, rejected, {**legal_counts, "sampled": len(topology_valid)}


def evaluate_candidate(positions, faces, current_raw, current_residual, candidate,
                       transform, size, scale, sigma):
    projected = depth.project(positions, transform)
    alive = valid_faces(faces)
    rect = depth.support(projected, faces, candidate, transform, size,
            int(np.ceil(4 * sigma)) + 2)
    if rect is None:
        return None
    p2, f2, alive2, removed = apply_world(positions, faces, candidate)
    if removed != 2:
        return None
    projected2 = depth.project(p2, transform)
    changed_patch, _ = depth.raster(projected2, f2, alive2, rect, scale)
    x0, y0, x1, y1 = rect
    current_patch = current_raw[y0 * scale:y1 * scale, x0 * scale:x1 * scale]
    filtered_delta = depth.filtered(changed_patch - current_patch, sigma, scale)
    proposal = current_residual.copy()
    proposal[y0:y1, x0:x1] += filtered_delta
    return float(np.square(proposal).sum()), proposal, (p2, f2, alive2), rect


def full_residual(positions, faces, transform, original_raw, size, scale, sigma):
    projected = depth.project(positions, transform)
    raw, _ = depth.raster(projected, faces, valid_faces(faces),
            (0, 0, size, size), scale)
    return raw, depth.filtered(raw - original_raw, sigma, scale)


def conflict_vertices(faces, candidate):
    affected = np.asarray(candidate["affected"], dtype=np.int64)
    return set(faces[affected].reshape(-1).tolist())


def holdout_views(source_positions, source_faces, final_states, size, scale, sigma,
                  fitted_angle):
    views = [("fitted", float(fitted_angle))]
    views.extend((f"near-{i}", float(angle)) for i, angle in
            enumerate(np.linspace(2.13, 2.48, 6)))
    views.extend((f"orbit-{i}", float(angle)) for i, angle in
            enumerate(np.linspace(0.0, 2 * np.pi, 6, endpoint=False)))
    result = {name: [] for name in final_states}
    for view_name, angle in views:
        transform = depth.camera(source_positions, angle, size)
        source_raw, _ = depth.raster(depth.project(source_positions, transform),
                source_faces, valid_faces(source_faces), (0, 0, size, size), scale)
        for policy, (positions, faces) in final_states.items():
            raw, _ = depth.raster(depth.project(positions, transform), faces,
                    valid_faces(faces), (0, 0, size, size), scale)
            residual = depth.filtered(raw - source_raw, sigma, scale)
            result[policy].append({"view": view_name, "angleRadians": angle,
                    "filteredSse": float(np.square(residual).sum())})
    return {policy: {"views": rows, "sumFilteredSse": float(sum(
            row["filteredSse"] for row in rows))} for policy, rows in result.items()}


def step_policy(name, positions, faces, candidate_source, frozen_pool, chosen_vertices,
                transform, original_raw, source_topology, size, scale, sigma, wanted,
                include_hidden, executable, work_dir, step):
    before = time.perf_counter()
    current_raw, current_residual = full_residual(positions, faces, transform,
            original_raw, size, scale, sigma)
    if name == "dynamic":
        selected, current_raw, rejected, screen = sample_candidates(positions, faces,
                candidate_source, transform, size, scale, sigma, source_topology, wanted,
                include_hidden)
        candidate_ids = [row[2] for row in selected]
        choices = [(candidate_source[cid], cid) for cid in candidate_ids]
        filtered_rows = [row for row in selected if not row[0]]
        priority_sample = [row[2] for row in filtered_rows]
        sampled_hidden = sum(bool(row[0]) for row in selected)
    else:
        choices = []
        blocked = 0
        for cid, candidate in enumerate(frozen_pool):
            vertices = conflict_vertices(faces, candidate)
            if vertices & chosen_vertices:
                blocked += 1
                continue
            p2, f2, alive2, removed = apply_world(positions, faces, candidate)
            if removed != 2 or not topology_passes(p2, f2, alive2, source_topology)[0]:
                continue
            choices.append((candidate, cid))
        selected = []
        rejected = {"outside": 0, "faceBudget": 0, "topology": 0}
        screen = {"visibleLegal": len(choices), "hiddenLegal": 0,
                "sampled": len(choices), "frozenBlockedByEarlierSupport": blocked}
        priority_sample = []
        sampled_hidden = 0

    best = None
    evaluated = 0
    for candidate, cid in choices:
        result = evaluate_candidate(positions, faces, current_raw, current_residual,
                candidate, transform, size, scale, sigma)
        if result is None:
            continue
        score, proposal, changed, rect = result
        key = (score, float(candidate["priority"]), int(cid))
        if best is None or key < best[0]:
            best = (key, candidate, cid, proposal, changed, rect)
        evaluated += 1
    if best is None:
        raise RuntimeError(f"{name} has no legal sampled candidate at step {step}")
    _, candidate, cid, predicted_residual, changed, rect = best
    p2, f2, alive2 = changed
    removed = int(np.count_nonzero(~alive2) - np.count_nonzero(~valid_faces(faces)))
    if removed != 2:
        raise AssertionError(f"{name} step {step} removed {removed} faces, expected 2")
    topology_ok, topology = topology_passes(p2, f2, alive2, source_topology)
    if not topology_ok:
        raise AssertionError(f"{name} step {step} failed topology checks: {topology}")
    actual_raw, actual_residual = full_residual(p2, f2, transform, original_raw,
            size, scale, sigma)
    model_gap = float(np.max(np.abs(predicted_residual - actual_residual)))
    if model_gap > 1e-9:
        raise AssertionError(f"patch/full mismatch {model_gap} at {name} step {step}")
    row = {"step": step, "sampledCandidates": len(choices), "evaluatedCandidates": evaluated,
            "rejected": rejected, "screen": screen, "sampledHidden": sampled_hidden,
            "selectedCandidateId": int(cid), "selectedPriority": float(candidate["priority"]),
            "selectedRemove": int(candidate["remove"]), "selectedKeep": int(candidate["keep"]),
            "selectedTarget": list(map(float, candidate["target"])),
            "removedTriangles": removed, "filteredSse": float(np.square(actual_residual).sum()),
            "filteredRmsePerPixelChannel": float(np.sqrt(np.square(actual_residual).mean())),
            "patchVsFullMaxAbsoluteDifference": model_gap, "topology": topology,
            "stepSeconds": time.perf_counter() - before}
    if name == "dynamic":
        # The changed state is exported and the candidate set is regenerated on every iteration.
        obj_path = work_dir / f"dynamic-step-{step:03d}.obj"
        json_path = work_dir / f"dynamic-step-{step:03d}.json"
        dump_obj(obj_path, p2, f2, alive2)
        recapture_seconds, stderr = capture_obj(executable, obj_path, json_path)
        new_positions, new_faces, new_candidates = depth.load_capture(json_path)
        # The import/capture round trip must preserve the rendered state exactly.
        round_raw, _ = full_residual(new_positions, new_faces, transform, original_raw,
                size, scale, sigma)
        round_gap = float(np.max(np.abs(round_raw - actual_raw)))
        if round_gap > 1e-10:
            raise AssertionError(f"OBJ recapture changed rendered image by {round_gap}")
        row.update({"freshLegalCandidateCount": len(new_candidates),
                "freshCaptureLegalCount": int(json.loads(json_path.read_text())["units"][0]["legalCandidates"]),
                "recaptureSeconds": recapture_seconds, "roundtripMaxRawImageDifference": round_gap,
                "captureLog": stderr[-500:]})
        return new_positions, new_faces, new_candidates, set(), row

    chosen_vertices.update(conflict_vertices(faces, candidate))
    return p2, f2, frozen_pool, chosen_vertices, row


def run(args):
    args.out.mkdir(parents=True, exist_ok=True)
    archived_positions, archived_faces, _ = depth.load_capture(args.capture)
    source_topology = audit.topology_summary(archived_positions, archived_faces)
    transform = depth.camera(archived_positions, args.angle, args.size)
    original_projected = depth.project(archived_positions, transform)
    original_raw, _ = depth.raster(original_projected, archived_faces,
            valid_faces(archived_faces), (0, 0, args.size, args.size), args.scale)

    initial_obj = args.out / "initial-roundtrip.obj"
    initial_capture = args.out / "initial-roundtrip.json"
    dump_obj(initial_obj, archived_positions, archived_faces)
    initial_capture_seconds, initial_log = capture_obj(args.executable, initial_obj, initial_capture)
    p0, f0, c0 = depth.load_capture(initial_capture)
    initial_raw, initial_residual = full_residual(p0, f0, transform, original_raw,
            args.size, args.scale, args.sigma)
    baseline_roundtrip_gap = float(np.max(np.abs(initial_raw - original_raw)))
    if baseline_roundtrip_gap > 1e-10:
        raise AssertionError(f"initial OBJ roundtrip changed rendered image by {baseline_roundtrip_gap}")
    frozen_sample, _, frozen_rejected, frozen_screen = sample_candidates(p0, f0, c0,
            transform, args.size, args.scale, args.sigma, source_topology, args.candidates,
            args.include_hidden)
    frozen_ids = [row[2] for row in frozen_sample]
    frozen_pool = [c0[cid] for cid in frozen_ids]

    report = {"scope": "single-view, geometry-only opaque coverage plus normalized depth; greedy exact filtered SSE; sampled candidates; no PBR or runtime claim",
            "comparison": "same initial sampled pool, either held frozen or regenerated from the current OBJ after each selected collapse",
            "settings": {"angleRadians": args.angle, "imageSize": args.size,
                    "supersample": args.scale, "gaussianSigma": args.sigma,
                    "sampledVisibleCandidates": args.candidates,
                    "sampledHiddenCandidates": (max(1, args.candidates // 4)
                            if args.include_hidden else 0),
                    "collapseSteps": args.steps},
            "sourceTriangles": int(len(archived_faces)),
            "sourceTopology": source_topology,
            "initialRoundtrip": {"seconds": initial_capture_seconds,
                    "maxRawImageDifference": baseline_roundtrip_gap,
                    "legalCandidates": len(c0), "log": initial_log[-1000:]},
            "initialCandidateSample": {"screen": frozen_screen, "rejected": frozen_rejected,
                    "selectedIds": frozen_ids},
            "hashes": {"capture": sha256(args.capture), "captureExecutable": sha256(args.executable),
                    "script": sha256(Path(__file__)), "depthRenderer": sha256(Path(depth.__file__))},
            "policies": {}}

    final_states = {}
    for policy in ("frozen", "dynamic"):
        positions, faces = p0.copy(), f0.copy()
        candidate_source = c0
        chosen_vertices = set()
        rows = []
        total_recapture = 0.0
        for step in range(args.steps):
            positions, faces, candidate_source, chosen_vertices, row = step_policy(policy,
                    positions, faces, candidate_source, frozen_pool, chosen_vertices,
                    transform, original_raw, source_topology, args.size, args.scale,
                    args.sigma, args.candidates, args.include_hidden, args.executable,
                    args.out, step)
            rows.append(row)
            total_recapture += float(row.get("recaptureSeconds", 0.0))
            print(policy, "step", step + 1, "faces", int(np.count_nonzero(valid_faces(faces))),
                    "SSE", f"{row['filteredSse']:.8g}", "candidates",
                    row["screen"]["sampled"], flush=True)
        final_raw, final_residual = full_residual(positions, faces, transform,
                original_raw, args.size, args.scale, args.sigma)
        final_states[policy] = (positions.copy(), faces.copy())
        report["policies"][policy] = {"steps": rows,
                "finalFaces": int(np.count_nonzero(valid_faces(faces))),
                "removedTriangles": int(2 * len(rows)),
                "finalFilteredSse": float(np.square(final_residual).sum()),
                "totalRecaptureSeconds": total_recapture,
                "totalSelectionAndRerenderSeconds": float(sum(r["stepSeconds"] for r in rows)),
                "finalTopology": audit.topology_summary(positions, faces[valid_faces(faces)])}
    frozen_score = report["policies"]["frozen"]["finalFilteredSse"]
    dynamic_score = report["policies"]["dynamic"]["finalFilteredSse"]
    report["dynamicVsFrozen"] = {"sseImprovementPercent": 100.0 *
            (frozen_score - dynamic_score) / max(frozen_score, 1e-30),
            "lowerSsePolicy": "dynamic" if dynamic_score < frozen_score else "frozen"}
    holdout = holdout_views(archived_positions, archived_faces, final_states,
            args.audit_size, args.audit_scale, args.sigma, args.angle)
    frozen_holdout = holdout["frozen"]["sumFilteredSse"]
    dynamic_holdout = holdout["dynamic"]["sumFilteredSse"]
    report["finalMultiViewAudit"] = {"size": args.audit_size,
            "supersample": args.audit_scale, "sigma": args.sigma,
            "views": [row["view"] for row in holdout["frozen"]["views"]],
            "policies": holdout,
            "dynamicSseImprovementPercent": 100.0 *
                    (frozen_holdout - dynamic_holdout) / max(frozen_holdout, 1e-30)}
    report_path = args.out / "dynamic-recapture-audit.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path),
            "frozenFinalSse": frozen_score, "dynamicFinalSse": dynamic_score,
            "dynamicVsFrozen": report["dynamicVsFrozen"],
            "dynamicRecaptureSeconds": report["policies"]["dynamic"]["totalRecaptureSeconds"]},
            indent=2))


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
    parser.add_argument("--candidates", type=int, default=32)
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--audit-size", type=int, default=128)
    parser.add_argument("--audit-scale", type=int, default=3)
    args = parser.parse_args()
    if min(args.steps, args.size, args.scale, args.candidates) < 1:
        parser.error("steps, size, scale, and candidates must be positive")
    run(args)


if __name__ == "__main__":
    main()
