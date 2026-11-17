"""Full-cost instrumented Python reference; no native/GPU speedup claim.

Nine frozen levels, ordinary SAH trees, exact fallback, frozen uniform viewport
cohort, and a separate exhaustive archived-disagreement validation cohort.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

import depth_candidate_pilot as raster
import edit_visibility_support as history
from proxy_visibility_cost_gate import require_hash
from visibility_query_bvh import BVH, Hybrid, Ray, cone_safe, fit_cone


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def trace_many(query, rays):
    answers = np.empty(len(rays), dtype=bool)
    counters = np.empty((len(rays), 3), dtype=np.int64)
    for i, ray in enumerate(rays):
        cost = [0, 0, 0]
        answers[i] = query.query(ray, cost)
        counters[i] = cost
    return answers, counters


def save_tree(tree, path):
    packed = tree.packed()
    np.savez_compressed(path, **packed)
    return dict(path=str(path), sha256=sha(path), packedBytes=sum(a.nbytes for a in packed.values()),
                nodes=len(tree.nodes), primitives=len(tree.bounds))


def make_ray(x, y, angle, distance):
    forward = np.array([np.sin(angle), .37, np.cos(angle)])
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0, 1, 0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    point = ((x + .5) / 384 - .5) / .43 * right + (.5 - (y + .5) / 384) / .43 * up
    return Ray(tuple(point + distance * forward), tuple(-forward), 2 * distance)


def summarize_costs(costs, selected):
    values = costs[selected]
    return dict(rays=len(values), sums=values.sum(0).tolist(),
                means=values.mean(0).tolist() if len(values) else [0, 0, 0])


def run_asset(root, asset, previous, out, strata, repeats):
    directory = root / "out/progressive-baseline" / asset
    capture = root / "out/filter-real-candidates" / (asset + ".json")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require_hash(capture, manifest["captureSha256"])
    previous_asset = next(a for a in previous["assets"] if a["asset"] == asset)
    require_hash(capture, previous_asset["capture"]["sha256"])
    require_hash(manifest_path, previous_asset["manifest"]["sha256"])
    require_hash(previous_asset["maskArtifact"]["path"], previous_asset["maskArtifact"]["sha256"])
    start = time.perf_counter()
    meshes, edits, actions, _ = history.replay(json.loads(capture.read_text()), manifest)
    replay_seconds = time.perf_counter() - start
    world, faces, _ = raster.load_capture(capture)
    center = (world.min(0) + world.max(0)) * .5
    radius = float(np.linalg.norm(world - center, axis=1).max())
    fine_positions = (world - center) / radius
    started = time.perf_counter()
    fine = BVH.mesh(fine_positions, faces)
    fine_seconds = time.perf_counter() - started
    fine_binding = save_tree(fine, out / (asset + "-fine-tree.npz"))
    # Global query endpoints span every source/coarse/intermediate edit box.
    global_points = [fine_positions]
    for parts in edits.values():
        global_points.extend((e["hulls"].reshape(-1, 3) - center) / radius for e in parts)
    distance = 3 * max(1., max(float(np.linalg.norm(p, axis=1).max()) for p in global_points))
    del global_points
    if 384 % strata:
        raise ValueError("strata must divide the saved sample grid")
    width = 384 // strata
    rng = np.random.default_rng(20261115)
    sample_indices, rays, view_ids = [], [], []
    for vi, angle in enumerate(np.linspace(0, 2 * np.pi, 12, endpoint=False)):
        for iy in range(strata):
            for ix in range(strata):
                y, x = iy * width + int(rng.integers(width)), ix * width + int(rng.integers(width))
                sample_indices.append((vi, y, x))
                rays.append(make_ray(x, y, float(angle), distance))
                view_ids.append(vi)
    indices = np.asarray(sample_indices, dtype=int)
    with np.load(previous_asset["maskArtifact"]["path"], allow_pickle=False) as archive:
        cached_fine = archive["fine"][tuple(indices.T)]
        cached_rect = archive["source_rectangle"][tuple(indices.T)]
        expected_coarse = {ratio: archive["coarse_" + ratio][tuple(indices.T)] for ratio in meshes}
    ray_path = out / (asset + "-rays.npz")
    np.savez_compressed(ray_path, origins=[r.origin for r in rays], directions=[r.direction for r in rays],
                        maximum=[r.maximum for r in rays], sampleIndices=indices,
                        fineExpected=cached_fine, sourceRectangle=cached_rect,
                        **{"coarseExpected_" + k: v for k, v in expected_coarse.items()})
    fine_answers, fine_costs = trace_many(fine, rays)
    if not np.array_equal(fine_answers, cached_fine):
        bad = np.flatnonzero(fine_answers != cached_fine)
        raise ValueError(f"independent fine intersection differs from saved raster: {asset} {indices[bad].tolist()}")
    rows = {}
    # Check fitted leaf cones against all exact stored normals, outside timed loops.
    random_directions = rng.normal(size=(64, 3))
    random_directions /= np.linalg.norm(random_directions, axis=1)[:, None]
    for ratio, (ps, fs) in meshes.items():
        artifact = manifest["artifacts"][ratio]
        artifact_path = root / Path(artifact["path"].replace("\\", "/"))
        require_hash(artifact_path, artifact["sha256"])
        with np.load(artifact_path, allow_pickle=False) as frozen:
            if not (np.array_equal(ps, frozen["positions"]) and np.array_equal(fs, frozen["triangles"])):
                raise ValueError("snapshot replay differs")
        start = time.perf_counter()
        coarse = BVH.mesh((ps - center) / radius, fs)
        coarse_seconds = time.perf_counter() - start
        start = time.perf_counter()
        boxes, cones = [], []
        for edit in edits[ratio]:
            points = (edit["hulls"].reshape(-1, 3) - center) / radius
            boxes.append([points.min(0) - 1e-10, points.max(0) + 1e-10])
            cone = fit_cone(edit)
            cones.append(cone)
        support = BVH(boxes, cones=cones)
        support_seconds = time.perf_counter() - start
        for edit, cone in zip(edits[ratio], cones):
            for direction in random_directions:
                if cone_safe(cone, direction) and not history.direction_invariant(edit, direction):
                    raise ValueError("fitted cone incorrectly culls an edit")
        hybrid = Hybrid(fine, coarse, support)
        coarse_answers, coarse_costs = trace_many(coarse, rays)
        if not np.array_equal(coarse_answers, expected_coarse[ratio]):
            bad = np.flatnonzero(coarse_answers != expected_coarse[ratio])
            raise ValueError(f"coarse kernel differs from raster: {asset} {ratio} {indices[bad].tolist()}")
        decisions, selection_costs = [], []
        for ray in rays:
            costs = [0, 0, 0]
            decisions.append(hybrid.classify(ray, costs)[0])
            selection_costs.append(costs)
        decisions = np.array(decisions)
        selection_costs = np.asarray(selection_costs)
        expected_costs = selection_costs.copy()
        use_fine = (decisions == "fine") | (decisions == "clipped")
        use_coarse = decisions == "coarse"
        expected_costs[use_fine] += fine_costs[use_fine] - [1, 0, 0]  # Reuse tested fine root.
        expected_costs[use_coarse] += coarse_costs[use_coarse]
        hybrid_answers, hybrid_costs = trace_many(hybrid, rays)
        if not (np.array_equal(hybrid_answers, fine_answers) and np.array_equal(hybrid_costs, expected_costs)):
            raise ValueError("hybrid correctness or complete cost decomposition failed")
        # Every known mismatching atom is a separate stress cohort, never part of timing statistics.
        checked_mismatches = 0
        with np.load(previous_asset["maskArtifact"]["path"], allow_pickle=False) as archive:
            old, new = archive["fine"], archive["coarse_" + ratio]
            for vi, y, x in np.argwhere(old != new):
                angle = 2 * np.pi * int(vi) / 12
                ray = make_ray(int(x), int(y), angle, distance)
                decision, _ = hybrid.classify(ray, [0, 0, 0])
                if decision == "coarse" or (decision == "miss" and old[vi, y, x]):
                    raise ValueError(f"compact support lost a known mismatch: {asset} {ratio} {(vi,y,x)}")
                checked_mismatches += 1
        print(asset, ratio, "correctness + complete costs checked", flush=True)
        # Alternating order, shared kernels and instrumentation. Setup is reported separately.
        for query in (fine, hybrid):
            trace_many(query, rays[:64])
        timings = {"fine": [], "hybrid": []}
        for repeat in range(repeats):
            order = (("fine", fine), ("hybrid", hybrid))
            if repeat % 2:
                order = order[::-1]
            for name, query in order:
                start = time.perf_counter()
                answers, costs = trace_many(query, rays)
                timings[name].append(time.perf_counter() - start)
                reference = fine_costs if name == "fine" else hybrid_costs
                if not (np.array_equal(answers, fine_answers) and np.array_equal(costs, reference)):
                    raise ValueError("timed query results changed")
        cohorts = dict(viewport=np.ones(len(rays), bool), sourceRectangle=cached_rect,
                       fineHits=cached_fine, fineMisses=~cached_fine)
        statistics = {name: {label: summarize_costs(cost, mask) for label, cost in (
            ("fine", fine_costs), ("hybrid", hybrid_costs), ("selector", selection_costs),
            ("coarseBiased", coarse_costs))} for name, mask in cohorts.items()}
        case_path = out / (asset + "-" + ratio + "-costs.npz")
        np.savez_compressed(case_path, fineCosts=fine_costs, hybridCosts=hybrid_costs,
            selectorCosts=selection_costs, coarseCosts=coarse_costs, decisions=decisions,
            fineAnswers=fine_answers, coarseAnswers=coarse_answers, hybridAnswers=hybrid_answers)
        bindings = {"fine": fine_binding,
            "coarse": save_tree(coarse, out / (asset + "-" + ratio + "-coarse-tree.npz")),
            "support": save_tree(support, out / (asset + "-" + ratio + "-support-tree.npz"))}
        rows[ratio] = dict(actualTriangles=len(fs), edits=len(edits[ratio]),
            uniformDisagreements=int(np.count_nonzero(coarse_answers != fine_answers)),
            exhaustiveArchivedMismatchAtomsChecked=checked_mismatches,
            decisions={name: int(np.count_nonzero(decisions == name)) for name in ("miss", "fine", "coarse", "clipped")},
            buildPythonSeconds=dict(fine=fine_seconds, coarse=coarse_seconds, support=support_seconds),
            timingsInstrumentedPythonSeconds=timings,
            medianFineOverHybridPythonTime=float(np.median(timings["fine"]) / np.median(timings["hybrid"])),
            cohorts=statistics, trees=bindings,
            costArtifact=dict(path=str(case_path), sha256=sha(case_path)))
        print(asset, ratio, "Python fine/hybrid median", rows[ratio]["medianFineOverHybridPythonTime"], flush=True)
    return dict(asset=asset, sourceTriangles=len(faces), replayedActions=actions,
                replayPythonSeconds=replay_seconds, capture=dict(path=str(capture), sha256=sha(capture)),
                manifest=dict(path=str(manifest_path), sha256=sha(manifest_path)),
                rayArtifact=dict(path=str(ray_path), sha256=sha(ray_path)), levels=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--support-report", type=Path,
                        default=Path("out/edit-visibility-support-20261115/report.json"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--strata", type=int, default=32)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1 or args.strata < 1:
        raise ValueError("positive repeats and strata required")
    args.out.mkdir(parents=True, exist_ok=True)
    previous = json.loads(args.support_report.read_text())
    require_hash(Path(history.__file__), previous["scriptSha256"])
    require_hash(Path(raster.__file__), previous["rasterSha256"])
    assets = [run_asset(args.root, asset, previous, args.out, args.strata, args.repeats)
              for asset in ("torus", "monkey", "pirate")]
    result = dict(schema=1, scope="instrumented scalar Python any-hit reference; no GPU/native claim",
        workload=dict(strataPerAxis=args.strata, views=12, seed=20261115, repeats=args.repeats,
                      distribution="one random saved subpixel per equal screen-space stratum"),
        build=dict(split="12-bin spatial SAH; forced split above 4 primitives", leafSize=4),
        costUnits=["AABB tests", "triangle tests", "cone tests"],
        scriptSha256=sha(__file__), kernelSha256=sha(Path(__file__).with_name("visibility_query_bvh.py")),
        historySha256=sha(history.__file__), rasterSha256=sha(raster.__file__),
        priorSupportReport=dict(path=str(args.support_report), sha256=sha(args.support_report)),
        caveats=["spatialized normal cone hierarchies are established prior art",
            "counters have no assigned relative hardware cost; Python timing includes instrumentation",
            "packedBytes are uncompressed numerical array payloads, not process RSS or GPU memory",
            "global segment-span guard falls back when endpoints clip the full history box",
            "normal cones and padding are numerical prototype tolerances, not formal float guarantees",
            "uniform orthographic coverage cohort; archived mismatch stress samples excluded from timings",
            "no shadows/BSDF/shading, authored attributes, unseen assets, or production quality gates"], assets=assets)
    (args.out / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("wrote", args.out / "report.json", flush=True)


if __name__ == "__main__":
    main()
