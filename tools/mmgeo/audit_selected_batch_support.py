#!/usr/bin/env python3
"""Measure whether screen-support conflicts change a real candidate collapse batch.

This is a fixed-pool, single-view, offline audit. It compares the archived topology-only
12-collapse schedule against a deterministic greedy schedule that also requires disjoint
filter-expanded projected supports. It measures full composite rerasterization, not GPU speed.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


depth = load_module("batch_support_depth", "depth_candidate_pilot.py")
support = load_module("batch_support_index", "audit_projected_support_invalidation.py")
multi = load_module("batch_support_multicollapse", "audit_multi_collapse_interactions.py")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def topology_supports(faces, candidates, ids):
    return [set(faces[np.asarray(candidates[cid]["affected"], dtype=np.int64)].reshape(-1))
            for cid in ids]


def greedy_batch(ids, energies, topology_sets, screen_conflicts, target_count,
                 enforce_screen=True):
    selected = []
    while len(selected) < target_count:
        choices = []
        for index, cid in enumerate(ids):
            if index in selected:
                continue
            conflict = False
            for previous in selected:
                if topology_sets[index] & topology_sets[previous]:
                    conflict = True
                    break
                if enforce_screen and screen_conflicts[index, previous]:
                    conflict = True
                    break
            if not conflict:
                choices.append((float(energies[index]), int(cid), index))
        if not choices:
            break
        selected.append(min(choices)[2])
    return [int(ids[index]) for index in selected]


def exact_batch_milp(ids, energies, topology_sets, screen_conflicts,
                     enforce_screen, target_count=None):
    """Return an exact minimum-cost conflict-free batch and solver audit."""
    import scipy
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    n = len(ids)
    conflicts = []
    for i in range(n):
        for j in range(i + 1, n):
            topology_conflict = not topology_sets[i].isdisjoint(topology_sets[j])
            screen_conflict = (enforce_screen and screen_conflicts[i, j])
            if topology_conflict or screen_conflict:
                conflicts.append((i, j))

    row_indices = []
    column_indices = []
    values = []
    for row, (i, j) in enumerate(conflicts):
        row_indices.extend((row, row))
        column_indices.extend((i, j))
        values.extend((1.0, 1.0))
    conflict_matrix_sparse = coo_matrix((values, (row_indices, column_indices)),
                                        shape=(len(conflicts), n)).tocsr()
    conflict_constraint = LinearConstraint(conflict_matrix_sparse,
            np.full(len(conflicts), -np.inf), np.ones(len(conflicts)))
    bounds = Bounds(np.zeros(n), np.ones(n))
    integrality = np.ones(n, dtype=np.uint8)

    cardinality = None
    if target_count is None:
        cardinality = milp(c=-np.ones(n), integrality=integrality, bounds=bounds,
                constraints=conflict_constraint, options={"mip_rel_gap": 0.0})
        if not cardinality.success or cardinality.x is None:
            return {"solver": "scipy.optimize.milp", "scipyVersion": scipy.__version__,
                    "status": int(cardinality.status), "message": cardinality.message,
                    "optimalMaximumCardinalityProven": False}, None
        max_count = int(np.count_nonzero(cardinality.x > 0.5))
    else:
        max_count = int(target_count)

    cardinality_row = coo_matrix((np.ones(n),
            (np.zeros(n, dtype=np.int32), np.arange(n, dtype=np.int32))),
            shape=(1, n)).tocsr()
    fixed_count_constraints = [conflict_constraint,
            LinearConstraint(cardinality_row, [max_count], [max_count])]
    optimum = milp(c=np.asarray(energies, dtype=float), integrality=integrality,
            bounds=bounds, constraints=fixed_count_constraints,
            options={"mip_rel_gap": 0.0})
    if not optimum.success or optimum.x is None:
        return {"solver": "scipy.optimize.milp", "scipyVersion": scipy.__version__,
                "status": int(optimum.status), "message": optimum.message,
                "optimalMaximumCardinalityProven": cardinality is not None,
                "maximumCardinality": max_count,
                "minimumCostAtRequestedCardinalityProven": False}, None
    selected_indices = np.flatnonzero(optimum.x > 0.5).tolist()
    return ({
        "solver": "scipy.optimize.milp",
        "scipyVersion": scipy.__version__,
        "status": int(optimum.status),
        "requestedCardinality": max_count,
        "minimumCostAtRequestedCardinality": float(optimum.fun),
        "optimalMaximumCardinalityProven": cardinality is not None,
        "minimumCostAtRequestedCardinalityProven": True,
        "maximumCardinality": (max_count if cardinality is not None else None),
        "maximumCardinalityMipGap": (float(cardinality.mip_gap)
                                      if cardinality is not None else None),
        "minimumCostMipGap": float(optimum.mip_gap),
        "conflictEdgeCount": len(conflicts),
        "candidateIds": [int(ids[i]) for i in selected_indices],
    }, selected_indices)


def audit(capture_path, report_path, schedule_path, export_path, output_path, target_count=12,
          size=128, halo=6, solve_exact=False):
    capture_path = Path(capture_path)
    report_path = Path(report_path)
    schedule_path = Path(schedule_path)
    export_path = Path(export_path)
    output_path = Path(output_path)

    positions, faces, candidates = depth.load_capture(capture_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    schedule_report = json.loads(schedule_path.read_text(encoding="utf-8"))
    settings, manifest, export_hash, export_rows = support.interaction.read_export(export_path)
    width, height, scale, sigma = settings
    if width != height or width != size:
        raise ValueError("requested support size must match the square delta export")
    if len(report["frames"]) != 6 or len(schedule_report["frames"]) != 6:
        raise ValueError("expected six archived view frames")
    if digest(capture_path) != manifest["captureSha256"]:
        raise ValueError("capture hash differs from the delta export manifest")
    if digest(report_path) != manifest["reportSha256"]:
        raise ValueError("selection report hash differs from the delta export manifest")
    schedule_hashes = schedule_report.get("hashes", {})
    for source_path, actual_hash in ((capture_path, digest(capture_path)),
                                     (report_path, digest(report_path)),
                                     (export_path, export_hash)):
        recorded = [value for key, value in schedule_hashes.items()
                    if Path(key).resolve() == source_path.resolve()]
        if not recorded or actual_hash not in recorded:
            raise ValueError(f"schedule report is not bound to {source_path}")

    source_topology = multi.topology_summary(positions, faces)
    source_valid = np.ones(len(faces), dtype=bool)
    output_frames = []
    for frame in report["frames"]:
        frame_id = int(frame["frame"])
        rows = [row for row in export_rows if row["frame"] == frame_id]
        ids = [int(row["id"]) for row in rows]
        if len(ids) != len(set(ids)) or len(ids) != 48:
            raise ValueError(f"frame {frame_id} must contain 48 unique candidates")
        if set(ids) != {int(item["id"]) for item in frame["candidates"]}:
            raise ValueError(f"frame {frame_id} candidate IDs differ from the export")

        angle = float(np.linspace(2.13, 2.48, 6)[frame_id])
        transform = depth.camera(positions, angle, size)
        projected = depth.project(positions, transform)
        baseline, _ = depth.raster(projected, faces, source_valid,
                                   (0, 0, width, height), scale)
        topology_sets = topology_supports(faces, candidates, ids)
        fragments = [support.support_fragments(projected, faces, candidates[cid],
                    transform, size, halo) for cid in ids]
        energies = np.asarray([float(row["inputSSE"]) for row in rows])
        residuals = np.stack([row["residual"] for row in rows])
        residual_fields = residuals.reshape(len(ids), height, width, 2)
        residual_masks = np.any(residual_fields != 0.0, axis=-1)
        projected_box_conflicts = np.zeros((len(ids), len(ids)), dtype=bool)
        actual_delta_support_conflicts = np.zeros_like(projected_box_conflicts)
        index = {cid: i for i, cid in enumerate(ids)}

        topology_compatible_pairs = 0
        projected_box_conflicts_among_compatible = 0
        actual_delta_conflicts_among_compatible = 0
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                projected_box_conflicts[i, j] = projected_box_conflicts[j, i] = (
                    support.fragmented_overlap(fragments[i], fragments[j]))
                actual_delta_support_conflicts[i, j] = actual_delta_support_conflicts[j, i] = (
                    bool(np.any(residual_masks[i] & residual_masks[j])))
                if topology_sets[i].isdisjoint(topology_sets[j]):
                    topology_compatible_pairs += 1
                    projected_box_conflicts_among_compatible += int(
                        projected_box_conflicts[i, j])
                    actual_delta_conflicts_among_compatible += int(
                        actual_delta_support_conflicts[i, j])

        schedule_frame = next(item for item in schedule_report["frames"]
                              if int(item["frame"]) == frame_id)
        archived = next(row for row in schedule_frame["schedules"]
                        if row["selector"] == "independent"
                        and row["collapseCount"] == target_count)
        topology_only_ids = [int(cid) for cid in archived["candidateIds"]]
        screen_aware_ids = greedy_batch(ids, energies, topology_sets,
                                        projected_box_conflicts, target_count)
        matched_topology_ids = greedy_batch(ids, energies, topology_sets,
                projected_box_conflicts, len(screen_aware_ids), enforce_screen=False)
        actual_delta_support_ids = greedy_batch(ids, energies, topology_sets,
                actual_delta_support_conflicts, target_count)
        matched_topology_for_actual_delta_ids = greedy_batch(ids, energies,
                topology_sets, actual_delta_support_conflicts,
                len(actual_delta_support_ids), enforce_screen=False)
        if len(screen_aware_ids) != target_count:
            screen_aware_status = "screen constraints exhausted compatible candidates"
        else:
            screen_aware_status = "target reached"

        topology_only_indices = [index[cid] for cid in topology_only_ids]
        screen_aware_indices = [index[cid] for cid in screen_aware_ids]
        matched_topology_indices = [index[cid] for cid in matched_topology_ids]
        actual_delta_support_indices = [index[cid] for cid in actual_delta_support_ids]
        matched_topology_for_actual_delta_indices = [index[cid]
                for cid in matched_topology_for_actual_delta_ids]
        if len(screen_aware_indices) < 1:
            raise ValueError(f"no screen-compatible operation in frame {frame_id}")

        def evaluate(selected_ids, selected_indices):
            rendered = multi.render_set(positions, faces, candidates, selected_ids,
                    transform, width, scale, sigma, baseline, source_topology)
            delta = residuals[selected_indices].sum(axis=0)
            additive_sse = float(np.dot(delta, delta))
            return {
                "candidateIds": selected_ids,
                "collapseCount": len(selected_ids),
                "trianglesRemoved": rendered["removedTriangles"],
                "additiveResidualSse": additive_sse,
                "fullCompositeRerasterSse": rendered["actualFilteredSse"],
                "rerasterMinusAdditiveSse": rendered["actualFilteredSse"] - additive_sse,
                "basicTopologyValid": rendered["topology"]["sameBasicTopologyAsSource"],
                "orientationValid": rendered["topology"]["sameSignedVolumeOrientation"],
            }

        schedule_overlap_pairs = []
        actual_delta_overlap_pairs = []
        for ai, left in enumerate(topology_only_indices):
            for right in topology_only_indices[ai + 1:]:
                if projected_box_conflicts[left, right]:
                    schedule_overlap_pairs.append([ids[left], ids[right]])
                if actual_delta_support_conflicts[left, right]:
                    actual_delta_overlap_pairs.append([ids[left], ids[right]])

        exact_schedules = None
        if solve_exact:
            exact_topology, exact_topology_indices = exact_batch_milp(
                    ids, energies, topology_sets, projected_box_conflicts,
                    enforce_screen=False)
            exact_screen, exact_screen_indices = exact_batch_milp(
                    ids, energies, topology_sets, projected_box_conflicts,
                    enforce_screen=True)
            exact_residual_support, exact_residual_support_indices = exact_batch_milp(
                    ids, energies, topology_sets, actual_delta_support_conflicts,
                    enforce_screen=True)
            if (exact_topology_indices is None or exact_screen_indices is None or
                    exact_residual_support_indices is None):
                raise RuntimeError(f"MILP did not prove the batch optimum for frame {frame_id}")
            exact_screen_count = int(exact_screen["maximumCardinality"])
            exact_topology_matched, exact_topology_matched_indices = exact_batch_milp(
                    ids, energies, topology_sets, projected_box_conflicts,
                    enforce_screen=False,
                    target_count=exact_screen_count)
            exact_residual_count = int(exact_residual_support["maximumCardinality"])
            exact_topology_at_residual_count, exact_topology_at_residual_indices = exact_batch_milp(
                    ids, energies, topology_sets, actual_delta_support_conflicts,
                    enforce_screen=False, target_count=exact_residual_count)
            if (exact_topology_matched_indices is None or
                    exact_topology_at_residual_indices is None):
                raise RuntimeError(f"matched topology-only MILP failed for frame {frame_id}")
            exact_schedules = {
                "topologyOnlyMaximum": {
                    "optimization": exact_topology,
                    "actualComposite": evaluate(
                        [int(ids[i]) for i in exact_topology_indices],
                        exact_topology_indices),
                },
                "screenAwareMaximum": {
                    "optimization": exact_screen,
                    "actualComposite": evaluate(
                        [int(ids[i]) for i in exact_screen_indices],
                        exact_screen_indices),
                },
                "actualDeltaSupportMaximum": {
                    "optimization": exact_residual_support,
                    "actualComposite": evaluate(
                        [int(ids[i]) for i in exact_residual_support_indices],
                        exact_residual_support_indices),
                },
                "topologyOnlyAtScreenMaximumCardinality": {
                    "optimization": exact_topology_matched,
                    "actualComposite": evaluate(
                        [int(ids[i]) for i in exact_topology_matched_indices],
                        exact_topology_matched_indices),
                },
                "topologyOnlyAtActualDeltaMaximumCardinality": {
                    "optimization": exact_topology_at_residual_count,
                    "actualComposite": evaluate(
                        [int(ids[i]) for i in exact_topology_at_residual_indices],
                        exact_topology_at_residual_indices),
                },
            }

        frame_output = {
            "frame": frame_id,
            "cameraAngleRadians": angle,
            "candidateCount": len(ids),
            "topologyCompatiblePairCount": topology_compatible_pairs,
            "projectedBoxConflictsAmongTopologyCompatiblePairs":
                projected_box_conflicts_among_compatible,
            "projectedBoxConflictFractionAmongTopologyCompatiblePairs":
                projected_box_conflicts_among_compatible / max(topology_compatible_pairs, 1),
            "actualDeltaSupportConflictsAmongTopologyCompatiblePairs":
                actual_delta_conflicts_among_compatible,
            "actualDeltaSupportConflictFractionAmongTopologyCompatiblePairs":
                actual_delta_conflicts_among_compatible / max(topology_compatible_pairs, 1),
            "topologyOnlySchedule": evaluate(topology_only_ids, topology_only_indices),
            "matchedBudgetTopologyOnlySchedule": evaluate(
                matched_topology_ids, matched_topology_indices),
            "screenAwareScheduleStatus": screen_aware_status,
            "screenAwareSchedule": evaluate(screen_aware_ids, screen_aware_indices),
            "actualDeltaSupportScheduleStatus": (
                "target reached" if len(actual_delta_support_ids) == target_count
                else "actual delta support constraints exhausted compatible candidates"),
            "actualDeltaSupportSchedule": evaluate(
                actual_delta_support_ids, actual_delta_support_indices),
            "matchedBudgetTopologyOnlyActualDeltaSupportSchedule": evaluate(
                matched_topology_for_actual_delta_ids,
                matched_topology_for_actual_delta_indices),
            "screenConflictingPairsInTopologyOnlySchedule": schedule_overlap_pairs,
            "actualDeltaSupportConflictingPairsInTopologyOnlySchedule":
                actual_delta_overlap_pairs,
        }
        if exact_schedules is not None:
            frame_output["exactMilpSchedules"] = exact_schedules
        output_frames.append(frame_output)

    result = {
        "scope": "single-view, opaque coverage/depth, frozen 48-candidate pool; projected-box and measured-delta-support batch screen",
        "limitations": [
            "No candidate regeneration after commits; all candidates originate at the source mesh.",
            "Projected supports are conservative per-face boxes expanded by a six-pixel finite-filter halo.",
            "Measured delta supports are exact only for the archived filtered coverage/depth candidate residuals.",
            "No material shading, shadows, motion, multi-view joint support, or GPU timing is measured.",
            "This experiment tests batch availability and image additivity, not perceptual quality or production legality.",
        ],
        "settings": {"size": size, "supersample": scale, "filterSigma": sigma,
                     "supportHaloPixels": halo, "targetCollapses": target_count},
        "hashes": {
            "captureSha256": digest(capture_path),
            "selectionReportSha256": digest(report_path),
            "scheduleReportSha256": digest(schedule_path),
            "deltaExportSha256": export_hash,
            "scriptSha256": digest(__file__),
        },
        "frames": output_frames,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("candidate_report", type=Path)
    parser.add_argument("schedule_report", type=Path)
    parser.add_argument("export", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--halo", type=int, default=6)
    parser.add_argument("--exact-milp", action="store_true",
                        help="solve maximum conflict-free batch and matched-budget optima exactly")
    args = parser.parse_args()
    result = audit(args.capture, args.candidate_report, args.schedule_report,
                   args.export, args.out,
                   args.count, args.size, args.halo, args.exact_milp)
    print(json.dumps({"scope": result["scope"], "settings": result["settings"],
        "frames": [{
            "frame": frame["frame"],
            "topologyCompatiblePairCount": frame["topologyCompatiblePairCount"],
            "projectedBoxConflictFraction":
                frame["projectedBoxConflictFractionAmongTopologyCompatiblePairs"],
            "actualDeltaSupportConflictFraction":
                frame["actualDeltaSupportConflictFractionAmongTopologyCompatiblePairs"],
            "topologyOnlyCount": frame["topologyOnlySchedule"]["collapseCount"],
            "projectedBoxAwareCount": frame["screenAwareSchedule"]["collapseCount"],
            "actualDeltaSupportCount":
                frame["actualDeltaSupportSchedule"]["collapseCount"],
            "screenConflictsInTopologyOnlySchedule":
                len(frame["screenConflictingPairsInTopologyOnlySchedule"]),
            "topologyOnlyActualSse":
                frame["topologyOnlySchedule"]["fullCompositeRerasterSse"],
            "screenAwareActualSse":
                frame["screenAwareSchedule"]["fullCompositeRerasterSse"],
            "actualDeltaSupportSse":
                frame["actualDeltaSupportSchedule"]["fullCompositeRerasterSse"],
            "matchedBudgetTopologyOnlyActualSse":
                frame["matchedBudgetTopologyOnlySchedule"]["fullCompositeRerasterSse"],
            "exactMaximumScreenBatch": (frame["exactMilpSchedules"]
                ["screenAwareMaximum"]["optimization"]["maximumCardinality"]
                if "exactMilpSchedules" in frame else None),
            "exactMaximumScreenBatchSse": (frame["exactMilpSchedules"]
                ["screenAwareMaximum"]["actualComposite"]["fullCompositeRerasterSse"]
                if "exactMilpSchedules" in frame else None),
            "exactTopologyMatchedScreenSse": (frame["exactMilpSchedules"]
                ["topologyOnlyAtScreenMaximumCardinality"]["actualComposite"]
                ["fullCompositeRerasterSse"] if "exactMilpSchedules" in frame else None),
            "exactMaximumActualDeltaSupportBatch": (frame["exactMilpSchedules"]
                ["actualDeltaSupportMaximum"]["optimization"]["maximumCardinality"]
                if "exactMilpSchedules" in frame else None),
            "exactActualDeltaSupportSse": (frame["exactMilpSchedules"]
                ["actualDeltaSupportMaximum"]["actualComposite"]
                ["fullCompositeRerasterSse"] if "exactMilpSchedules" in frame else None),
            "exactTopologyMatchedActualDeltaSse": (frame["exactMilpSchedules"]
                ["topologyOnlyAtActualDeltaMaximumCardinality"]["actualComposite"]
                ["fullCompositeRerasterSse"] if "exactMilpSchedules" in frame else None),
        } for frame in result["frames"]]}, indent=2))


if __name__ == "__main__":
    main()
