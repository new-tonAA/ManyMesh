"""Paired wall/CPU timer audit for all frozen fused-patch configurations."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from benchmark_fused_patch_visibility import run_queries
from fused_patch_visibility import FusedPatchQuery, scalar_mesh_cache
from visibility_query_bvh import BVH, Ray


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(binding):
    if sha(binding["path"]) != binding["sha256"]:
        raise ValueError("bound data changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if args.repeats < 3:
        raise ValueError("at least three paired repetitions required")
    for name, digest in report["sourceHashes"].items():
        if sha(Path(__file__).with_name(name)) != digest:
            raise ValueError("benchmark source changed")
    cases = []
    for asset in report["assets"]:
        require(asset["fineTree"])
        require(asset["rays"])
        with np.load(asset["fineTree"]["path"], allow_pickle=False) as arrays:
            fine = scalar_mesh_cache(BVH.from_packed(dict(arrays)))
        with np.load(asset["rays"]["path"], allow_pickle=False) as arrays:
            rays = [Ray(tuple(o), tuple(d), float(t)) for o, d, t in zip(
                arrays["origins"], arrays["directions"], arrays["maximum"])]
            expected = arrays["fineExpected"]
        for case in asset["cuts"]:
            for field in ("patches", "proxies", "queries"):
                require(case[field])
            records = json.loads(Path(case["patches"]["path"]).read_text(encoding="utf-8"))["patches"]
            patches = {}
            with np.load(case["proxies"]["path"], allow_pickle=False) as arrays:
                for record in records:
                    if not record["active"]:
                        continue
                    prefix = f"n{record['node']}_"
                    packed = {k[len(prefix):]: arrays[k] for k in arrays.files
                              if k.startswith(prefix) and k != prefix + "cone"}
                    proxy = scalar_mesh_cache(BVH.from_packed(packed))
                    patches[record["node"]] = proxy, tuple(map(float, arrays[prefix + "cone"]))
            actual = FusedPatchQuery(fine, patches)
            with np.load(case["queries"]["path"], allow_pickle=False) as arrays:
                saved_costs = {"fine": arrays["fineCosts"], "actual": arrays["actualCosts"]}
            for query in (fine, actual):
                run_queries(query, rays[:64])
            timings = {"fine": [], "actual": []}
            for repeat in range(args.repeats):
                order = (("fine", fine), ("actual", actual))
                if repeat % 2:
                    order = order[::-1]
                for label, query in order:
                    wall_start, cpu_start = time.perf_counter(), time.process_time()
                    answer, costs, _ = run_queries(query, rays)
                    cpu_elapsed, wall_elapsed = time.process_time() - cpu_start, time.perf_counter() - wall_start
                    if not (np.array_equal(answer, expected) and np.array_equal(costs, saved_costs[label])):
                        raise ValueError("retimed query changed its result or cost")
                    timings[label].append(dict(wallSeconds=wall_elapsed, cpuSeconds=cpu_elapsed))
            wall_ratios = [a["wallSeconds"] / b["wallSeconds"] for a, b in zip(timings["fine"], timings["actual"])]
            cpu_ratios = [a["cpuSeconds"] / b["cpuSeconds"] for a, b in zip(timings["fine"], timings["actual"])]
            row = dict(asset=asset["asset"], capacity=case["capacity"], repeats=args.repeats,
                raw=timings, pairedFineOverActualWallRatios=wall_ratios,
                pairedFineOverActualCpuRatios=cpu_ratios,
                medianPairedFineOverActualWallRatio=float(np.median(wall_ratios)),
                medianPairedFineOverActualCpuRatio=float(np.median(cpu_ratios)))
            cases.append(row)
            print(asset["asset"], case["capacity"], "paired wall/cpu ratios",
                  row["medianPairedFineOverActualWallRatio"], row["medianPairedFineOverActualCpuRatio"], flush=True)
    result = dict(reportSha256=sha(args.report), scriptSha256=sha(__file__), cases=cases,
        caveats=["all nine cases rerun; not selected for positive timing",
                 "both mesh caches use Python float for triangle and node components",
                 "instrumented Python CPU/wall time, not GPU/native performance",
                 "paired medians replace ratio-of-medians interpretation of noisy first runs"])
    (args.report.parent / "timing-audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
