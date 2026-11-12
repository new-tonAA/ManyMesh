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

"""Measure how many image-oracle candidates a cheap LOD predictor retains."""

import argparse
import json
from pathlib import Path

import numpy as np

from lod_predictor import scores_for_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score", type=Path, required=True)
    parser.add_argument("--predictor", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    capture = json.loads(args.score.read_text(encoding="utf-8"))
    folds = json.loads(args.predictor.read_text(encoding="utf-8"))["folds"]
    models = {fold["test_sha256"]: fold["model"] for fold in folds}
    frames = []
    for meta, view in zip(capture["capture"]["views"], capture["views"], strict=True):
        rows = view["candidates"]
        model = models[meta["asset_sha256"]]
        geometric, ridge, mlp = scores_for_frame(rows, capture["capture"], model, {})
        measured = np.array([row["raw_mse"] for row in rows])
        if not np.all(np.isfinite(measured)) or np.any(measured <= 0):
            raise ValueError(f"Invalid image errors: {view['directory']}")
        full = float(measured.min())
        result = {"asset": meta["asset"], "directory": view["directory"],
                  "candidates": len(rows) - 1, "full_oracle_mse": full, "policies": {}}
        for name, values in (("geometric", geometric), ("ridge", ridge), ("mlp", mlp)):
            order = np.argsort(-values[1:], kind="stable") + 1
            curves = {}
            for budget in (0, 1, 2, 4, 8, 12):
                selected = np.r_[0, order[:budget]]
                best = int(selected[np.argmin(measured[selected])])
                curves[str(budget)] = {
                    "selected": rows[best]["stem"],
                    "best_mse": float(measured[best]),
                    "recovers_full_oracle": bool(np.isclose(measured[best], full,
                                                              rtol=1e-12, atol=0)),
                    "gain_db": float(10 * np.log10(measured[0] / measured[best])),
                }
            result["policies"][name] = curves
        frames.append(result)
    args.out.write_text(json.dumps(frames, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8")
    print(f"Screened {len(frames)} frames, {sum(frame['candidates'] for frame in frames)} swaps")


if __name__ == "__main__":
    main()
