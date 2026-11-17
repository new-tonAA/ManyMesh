#!/usr/bin/env python3
"""Screen multi-collapse image-interaction ranking on a frozen real-candidate pool.

This is an offline, single-view, geometry-only experiment. It exhaustively compares
independent and pairwise-filtered objectives for k=2 and k=4, then extends the same
objectives with deterministic greedy selection to k=8 and k=12. Selected composites are
actually rerasterized; pairwise residual addition is never treated as ground truth.
"""

import argparse
from itertools import combinations
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
REPORT_MD = ROOT / "tools/mmgeo/MULTI_COLLAPSE_INTERACTION_AUDIT_20261116.md"


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


depth = load_module("multi_collapse_depth", "depth_candidate_pilot.py")
interaction = load_module("multi_collapse_interaction", "audit_real_candidate_interactions.py")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def candidate_supports(faces, candidates, ids):
    supports = []
    for cid in ids:
        affected = np.asarray(candidates[cid]["affected"], dtype=np.int64)
        supports.append(set(faces[affected].reshape(-1).tolist()))
    return supports


def conflict_matrix(supports):
    n = len(supports)
    conflicts = np.zeros((n, n), dtype=bool)
    for i in range(n):
        for j in range(i + 1, n):
            conflicts[i, j] = conflicts[j, i] = bool(supports[i] & supports[j])
    return conflicts


def predicted_sse(indices, gram):
    value = sum(float(gram[i, i]) for i in indices)
    value += 2.0 * sum(float(gram[i, j]) for i, j in combinations(indices, 2))
    return max(0.0, value)


def exact_best_both(ids, gram, conflicts, count):
    best_independent = None
    best_interaction = None
    feasible = 0
    for subset in combinations(range(len(ids)), count):
        if any(conflicts[i, j] for i, j in combinations(subset, 2)):
            continue
        feasible += 1
        diagonal = sum(float(gram[i, i]) for i in subset)
        joint = diagonal + 2.0 * sum(float(gram[i, j])
                for i, j in combinations(subset, 2))
        tie = tuple(ids[i] for i in subset)
        independent_key = (diagonal, tie)
        interaction_key = (joint, tie)
        if best_independent is None or independent_key < best_independent[0]:
            best_independent = (independent_key, subset)
        if best_interaction is None or interaction_key < best_interaction[0]:
            best_interaction = (interaction_key, subset)
    if best_independent is None:
        raise ValueError(f"no feasible {count}-collapse set")
    return (list(best_independent[1]), float(best_independent[0][0]),
            list(best_interaction[1]), max(0.0, float(best_interaction[0][0])), feasible)


def greedy_prefixes(ids, gram, conflicts, max_count, include_interactions):
    selected = []
    result = {}
    for _ in range(max_count):
        choices = []
        for candidate in range(len(ids)):
            if candidate in selected or any(conflicts[candidate, prior] for prior in selected):
                continue
            subset = selected + [candidate]
            if include_interactions:
                value = predicted_sse(subset, gram)
            else:
                value = sum(float(gram[i, i]) for i in subset)
            choices.append((value, ids[candidate], candidate))
        if not choices:
            raise ValueError(f"greedy stopped after {len(selected)} compatible collapses")
        selected.append(min(choices)[2])
        result[len(selected)] = list(selected)
    return result


def topology_summary(positions, faces):
    used = np.unique(faces)
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    edge_signs = np.where(edges[:, 0] < edges[:, 1], 1, -1)
    edges.sort(axis=1)
    unique_edges, edge_inverse, edge_counts = np.unique(edges, axis=0,
            return_inverse=True, return_counts=True)
    orientation_sums = np.bincount(edge_inverse, weights=edge_signs)
    canonical_faces = np.sort(faces, axis=1)
    _, face_counts = np.unique(canonical_faces, axis=0, return_counts=True)
    triangles = positions[faces]
    twice_area = np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
            triangles[:, 2] - triangles[:, 0]), axis=1)

    parent = {int(v): int(v) for v in used}

    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    for a, b in unique_edges:
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[ra] = rb
    components = len({find(int(v)) for v in used})
    incidence_histogram = {str(int(k)): int(v) for k, v in zip(*np.unique(
            edge_counts, return_counts=True))}
    signed_volume = float(np.einsum("ij,ij->i", triangles[:, 0],
            np.cross(triangles[:, 1], triangles[:, 2])).sum() / 6.0)
    return {
        "vertices": int(len(used)),
        "edges": int(len(unique_edges)),
        "faces": int(len(faces)),
        "eulerCharacteristic": int(len(used) - len(unique_edges) + len(faces)),
        "connectedComponents": int(components),
        "edgeIncidenceHistogram": incidence_histogram,
        "closedTwoManifold": bool(all(count == 2 for count in edge_counts)),
        "orientationConsistent": bool(np.all(orientation_sums == 0)),
        "duplicateFaces": int(np.count_nonzero(face_counts > 1)),
        "zeroAreaFaces": int(np.count_nonzero(twice_area <= 1e-12)),
        "signedVolume": signed_volume,
    }


def render_set(world_positions, faces, candidates, subset_ids, transform, size, scale, sigma,
               baseline, source_topology):
    changed_world_positions = world_positions.copy()
    changed_faces = faces.copy()
    for cid in subset_ids:
        candidate = candidates[cid]
        changed_world_positions[candidate["keep"]] = candidate["target"]
        changed_faces[changed_faces == candidate["remove"]] = candidate["keep"]

    valid = ((changed_faces[:, 0] != changed_faces[:, 1]) &
             (changed_faces[:, 1] != changed_faces[:, 2]) &
             (changed_faces[:, 2] != changed_faces[:, 0]))
    removed = int(np.count_nonzero(~valid))
    active_faces = changed_faces[valid]
    if removed != 2 * len(subset_ids):
        raise ValueError(f"non-additive face reduction: expected {2 * len(subset_ids)}, got {removed}")
    topology = topology_summary(changed_world_positions, active_faces)
    topology["sameBasicTopologyAsSource"] = all(
            topology[key] == source_topology[key] for key in (
                "eulerCharacteristic", "connectedComponents", "closedTwoManifold",
                "orientationConsistent",
                "duplicateFaces", "zeroAreaFaces"))
    topology["sameSignedVolumeOrientation"] = bool(
            np.sign(topology["signedVolume"]) == np.sign(source_topology["signedVolume"]))

    changed_projected = depth.project(changed_world_positions, transform)
    raw, _ = depth.raster(changed_projected, changed_faces, valid,
            (0, 0, size, size), scale)
    filtered = depth.filtered(raw - baseline, sigma, scale)
    actual_sse = float(np.square(filtered).sum())
    return {"removedTriangles": removed, "actualFilteredSse": actual_sse,
            "actualVsPairwisePredictionAbsolute": None,
            "topology": topology}


def analyze(capture_path, selection_report_path, export_path, output_path,
            report_md_path=None):
    capture_path = Path(capture_path).resolve()
    selection_report_path = Path(selection_report_path).resolve()
    export_path = Path(export_path).resolve()
    output_path = output_path.resolve()
    report_md_path = (Path(report_md_path).resolve() if report_md_path is not None
                      else REPORT_MD)
    capture_sha = digest(capture_path)
    selection_sha = digest(selection_report_path)
    export_manifest_path = export_path.with_suffix(".manifest.json")
    manifest = json.loads(export_manifest_path.read_text(encoding="utf-8"))
    if capture_sha != manifest["captureSha256"]:
        raise ValueError("capture hash differs from exported candidate deltas")
    if selection_sha != manifest["reportSha256"]:
        raise ValueError("selection report hash differs from exported candidate deltas")

    positions, faces, candidates = depth.load_capture(capture_path)
    selection_report = json.loads(selection_report_path.read_text(encoding="utf-8"))
    settings, export_manifest, export_sha, export_rows = interaction.read_export(export_path)
    width, height, scale, sigma = settings
    if width != height:
        raise ValueError("this audit expects square captured views")
    if len(selection_report["frames"]) != 6:
        raise ValueError("expected the six archived camera frames")

    removed_count = {}
    for row in export_rows:
        cid = row["id"]
        if cid not in removed_count:
            candidate = candidates[cid]
            changed_faces = faces.copy()
            changed_faces[changed_faces == candidate["remove"]] = candidate["keep"]
            valid = ((changed_faces[:, 0] != changed_faces[:, 1]) &
                     (changed_faces[:, 1] != changed_faces[:, 2]) &
                     (changed_faces[:, 2] != changed_faces[:, 0]))
            removed_count[cid] = int(np.count_nonzero(~valid))
        if removed_count[cid] != 2:
            raise ValueError(f"candidate {cid} does not remove exactly two triangles")

    frame_results = []
    total_raster_seconds = 0.0
    start_time = time.perf_counter()
    source_valid = np.ones(len(faces), dtype=bool)
    source_topology = topology_summary(positions, faces)

    for frame in selection_report["frames"]:
        frame_id = int(frame["frame"])
        rows = [row for row in export_rows if row["frame"] == frame_id]
        ids = [row["id"] for row in rows]
        if len(ids) != 48 or len(set(ids)) != len(ids):
            raise ValueError(f"frame {frame_id} must contain 48 unique candidates")
        if set(ids) != {int(item["id"]) for item in frame["candidates"]}:
            raise ValueError(f"frame {frame_id} candidate IDs differ across manifests")

        residuals = np.stack([row["residual"] for row in rows])
        gram = residuals @ residuals.T
        supports = candidate_supports(faces, candidates, ids)
        conflicts = conflict_matrix(supports)
        frame_angle = float(np.linspace(2.13, 2.48, 6)[frame_id])
        transform = depth.camera(positions, frame_angle, width)
        projected = depth.project(positions, transform)
        baseline, _ = depth.raster(projected, faces, source_valid,
                (0, 0, width, height), scale)
        source_summary = source_topology

        exact = {}
        feasible_counts = {}
        for count in (2, 4):
            ind, _, joint, _, feasible = exact_best_both(ids, gram, conflicts, count)
            exact[("independent", count)] = ind
            exact[("interaction", count)] = joint
            feasible_counts[str(count)] = feasible
        max_greedy = max(8, 12)
        greedy_ind = greedy_prefixes(ids, gram, conflicts, max_greedy, False)
        greedy_joint = greedy_prefixes(ids, gram, conflicts, max_greedy, True)

        schedules = []
        for count in (2, 4):
            for mode in ("independent", "interaction"):
                indices = exact[(mode, count)]
                schedules.append((mode, "exact", count, indices))
        for count in (8, 12):
            schedules.append(("independent", "greedy", count, greedy_ind[count]))
            schedules.append(("interaction", "greedy", count, greedy_joint[count]))

        rendered = {}
        rows_out = []
        for mode, selector, count, indices in schedules:
            key_ids = tuple(sorted(ids[i] for i in indices))
            if key_ids not in rendered:
                render_start = time.perf_counter()
                rendered[key_ids] = render_set(positions, faces, candidates, key_ids,
                        transform, width, scale, sigma, baseline, source_summary)
                total_raster_seconds += time.perf_counter() - render_start
            model_sse = predicted_sse(indices, gram)
            if mode == "independent":
                model_sse = sum(float(gram[i, i]) for i in indices)
            actual = dict(rendered[key_ids])
            actual["actualVsPairwisePredictionAbsolute"] = abs(
                    actual["actualFilteredSse"] - predicted_sse(indices, gram))
            rows_out.append({"selector": mode, "search": selector, "collapseCount": count,
                    "triangleBudgetReduction": 2 * count,
                    "candidateIds": list(key_ids), "independentPredictionSse": model_sse,
                    "pairwisePredictionSse": predicted_sse(indices, gram), **actual})

        frame_results.append({"frame": frame_id, "cameraAngleRadians": frame_angle,
                "candidateCount": len(ids), "compatiblePairCount": int(
                        np.count_nonzero(np.triu(~conflicts, 1))),
                "feasibleSubsetsByCollapseCount": feasible_counts,
                "sourceTopology": source_summary, "schedules": rows_out})

    elapsed = time.perf_counter() - start_time
    comparisons = []
    for count, search in ((2, "exact"), (4, "exact"), (8, "greedy"), (12, "greedy")):
        gains = []
        same_schedules = 0
        better_views = 0
        topology_passes = 0
        max_model_error = 0.0
        independent_scores = []
        interaction_scores = []
        for frame in frame_results:
            independent = next(row for row in frame["schedules"]
                    if row["selector"] == "independent" and row["search"] == search
                    and row["collapseCount"] == count)
            joint = next(row for row in frame["schedules"]
                    if row["selector"] == "interaction" and row["search"] == search
                    and row["collapseCount"] == count)
            improvement = 100.0 * (independent["actualFilteredSse"] - joint["actualFilteredSse"]
                    ) / max(independent["actualFilteredSse"], 1e-30)
            gains.append(improvement)
            independent_scores.append(independent["actualFilteredSse"])
            interaction_scores.append(joint["actualFilteredSse"])
            same_schedules += int(independent["candidateIds"] == joint["candidateIds"])
            better_views += int(joint["actualFilteredSse"] < independent["actualFilteredSse"] - 1e-15)
            topology_passes += int(independent["topology"]["sameBasicTopologyAsSource"]
                    and independent["topology"]["sameSignedVolumeOrientation"])
            topology_passes += int(joint["topology"]["sameBasicTopologyAsSource"]
                    and joint["topology"]["sameSignedVolumeOrientation"])
            max_model_error = max(max_model_error,
                    independent["actualVsPairwisePredictionAbsolute"],
                    joint["actualVsPairwisePredictionAbsolute"])
        comparisons.append({
            "collapseCount": count,
            "search": search,
            "sameSchedulesOutOfSix": same_schedules,
            "meanActualSseImprovementPercent": float(np.mean(gains)),
            "viewsWithInteractionImprovement": better_views,
            "topologyPassesOutOfTwelve": topology_passes,
            "meanIndependentActualSse": float(np.mean(independent_scores)),
            "meanInteractionActualSse": float(np.mean(interaction_scores)),
            "maxAbsoluteActualVsPairwisePrediction": max_model_error,
        })
    result = {
        "scope": f"single-view opaque {capture_path.stem}; frozen 48 initial legal geometry candidates per frame; exact finite-pool selectors at k=2,4 and greedy prefixes at k=8,12; full composite rerasterization",
        "limitations": [
            "Candidate sets are frozen at the initial mesh; no candidate regeneration after collapse.",
            "One orthographic view at a time; no color, material, authored attributes or user perception.",
            "Pairwise compatibility requires disjoint affected vertex sets and does not certify global self-intersection or all production quality gates.",
            "This is an offline Python CPU diagnostic, not a production simplifier or runtime claim.",
        ],
        "settings": {"width": width, "height": height, "supersample": scale,
                "gaussianSigma": sigma, "candidatesPerView": 48,
                "exactSearchCollapseCounts": [2, 4], "greedyCollapseCounts": [8, 12]},
        "hashes": {str(path): digest(path) for path in (
                capture_path, selection_report_path, export_path, export_manifest_path,
                Path(__file__), Path(depth.__file__), Path(interaction.__file__))},
        "elapsedSeconds": elapsed,
        "actualCompositeRerasterSeconds": total_raster_seconds,
        "selectorComparisonByBudget": comparisons,
        "frames": frame_results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Multi-Collapse Filtered-Error Interaction Audit (2026-11-16)",
        "",
        "## Protocol",
        "",
        f"This extends the archived same-view interaction screen from two collapses to 4, 8 and 12 collapses. Each view uses its frozen 48-candidate initial-state pool on {capture_path.stem}. Every candidate removes exactly two triangles. Candidate sets must have disjoint affected vertex sets, so all schedules at one row reduce the same number of triangles.",
        "",
        "For k=2 and k=4, the finite-pool selector is exhaustive over compatible subsets. The independent objective sums each candidate's exact filtered single-collapse SSE. The interaction objective adds all pairwise filtered residual cross terms. For k=8 and k=12, both objectives use deterministic greedy prefixes. Every selected composite is applied to the original mesh and fully rerasterized in the same camera; the pairwise model is compared against this actual composite result.",
        "",
        "The score is geometry-only, opaque, coverage plus normalized depth, one orthographic view at a time. It is not an appearance metric or a production legality proof. Frozen candidates do not regenerate after edits, and pairwise one-ring disjointness does not guarantee global self-intersection safety.",
        "",
        "## Selected output results",
        "",
        "| k | Search | Same schedules / 6 | Mean actual SSE improvement | Views improved | Topology checks / 12 | Max absolute model error |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for row in comparisons:
        lines.append(f"| {row['collapseCount']} | {row['search']} | {row['sameSchedulesOutOfSix']} | "
                f"{row['meanActualSseImprovementPercent']:.6f}% | "
                f"{row['viewsWithInteractionImprovement']} | {row['topologyPassesOutOfTwelve']} | "
                f"{row['maxAbsoluteActualVsPairwisePrediction']:.3g} |")
    lines += [
        "",
        f"At k=12 the schedules remove 24 of the asset's {len(faces)} source triangles ({100.0 * 24 / max(len(faces), 1):.2f}%). This is a larger budget than the earlier two-collapse screen; its fraction is asset-dependent.",
        "",
        "| View | k | Selector/search | Triangles removed | Pairwise predicted SSE | Actual composite SSE | Topology check | Candidate IDs |",
        "|---:|---:|---|---:|---:|---:|---|---|",
    ]
    for frame in frame_results:
        for row in frame["schedules"]:
            topology_ok = "pass" if (row["topology"]["sameBasicTopologyAsSource"]
                    and row["topology"]["sameSignedVolumeOrientation"]) else "FAIL"
            ids_text = ",".join(map(str, row["candidateIds"]))
            lines.append(f"| {frame['frame']} | {row['collapseCount']} | {row['selector']} / {row['search']} | "
                    f"{row['removedTriangles']} | {row['pairwisePredictionSse']:.8g} | "
                    f"{row['actualFilteredSse']:.8g} | {topology_ok} | `{ids_text}` |")
    lines += [
        "",
        f"Composite rasterization took {total_raster_seconds:.3f}s total in this Python CPU diagnostic; complete analysis took {elapsed:.3f}s. These times only show experiment cost and are not comparable to a production simplifier.",
        "",
        "## Decision",
        "",
        "A multi-collapse result is useful only if the interaction-aware selector changes actual output quality at the same triangle budget, the gain is stable across views, and the work to obtain the scores is cheaper than exact local redraw. Read the table together with the limitations and machine-readable schedules; exact k=2/4 selectors are finite-pool offline oracles, while k=8/12 are greedy controls. No general mesh, attribute, runtime, or SIGGRAPH claim follows from this single-asset experiment.",
        "",
        f"Machine-readable results and hashes: `{output_path.relative_to(ROOT)}`.",
        "",
    ]
    report_md_path.parent.mkdir(parents=True, exist_ok=True)
    report_md_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "report": str(report_md_path),
            "frames": len(frame_results), "elapsedSeconds": elapsed,
            "actualCompositeRerasterSeconds": total_raster_seconds}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("selection_report", type=Path)
    parser.add_argument("export", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--report-md", type=Path)
    args = parser.parse_args()
    analyze(args.capture, args.selection_report, args.export, args.out, args.report_md)


if __name__ == "__main__":
    main()
