#!/usr/bin/env python3
#
# Copyright (C) 2026 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Paired, alternating CPU measurements of full-resolution depth reuse.

Samples the first frame of each asset in each capture; does not measure renderer
or device frame time. Validation / OBJ loading are outside prototype_ms.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from lod_oracle import digest
from lod_proxy import Graph, frame_scores


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", nargs="+", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    results = []
    for root in args.captures:
        manifest = root / "geometry.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        seen = set()
        for view in data["views"]:
            if view["asset_sha256"] in seen:
                continue
            seen.add(view["asset_sha256"])
            path = root / view["directory"]
            graph_bytes = (path / "lod_graph.mmb").read_bytes()
            if digest(path / "lod_graph.mmb") != view["graph_sha256"]:
                raise ValueError("Graph differs from capture")
            graph = Graph(graph_bytes)
            times = {"independent": [], "shared": []}
            reference = None
            # Warm each implementation once, then alternate order per repetition.
            for repeat in range(args.repeats + 1):
                for shared in ((False, True) if repeat % 2 == 0 else (True, False)):
                    scores, work = frame_scores(path, view, data["width"], data["height"],
                                                graph, shared_depth=shared)
                    if reference is None:
                        reference = scores
                    if any(not np.array_equal(reference[key], value) for key, value in scores.items()):
                        raise AssertionError(f"Score changed: {path}")
                    if repeat:
                        times["shared" if shared else "independent"].append(work["prototype_ms"])
            result = {"capture_sha256": digest(manifest), "frame": str(path),
                      "asset_sha256": view["asset_sha256"], "scores_identical": True,
                      "samples_ms": times,
                      "median_ms": {key: float(np.median(value)) for key, value in times.items()}}
            results.append(result)
            print(path, result["median_ms"], flush=True)
    args.out.write_text(json.dumps(results, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
