"""Asset-paired summaries of decoder image metrics, retaining failure counts."""

import argparse
import json
from pathlib import Path

import numpy as np


KEYS = ("psnr_db", "ssim", "flip", "lpips_squeeze", "silhouette_xor_fraction", "coverage_mae")


def paired_interval(deltas):
    if not deltas:
        return None
    values = np.array(deltas, dtype=np.float64)
    random = np.random.default_rng(20261121)
    means = values[random.integers(0, len(values), size=(2000, len(values)))].mean(axis=1)
    return {"assets": len(values), "mean_delta": float(values.mean()),
            "bootstrap_95_percent": np.quantile(means, (.025, .975)).tolist(),
            "negative": int(np.count_nonzero(values < -1e-12)),
            "positive": int(np.count_nonzero(values > 1e-12))}


def summarize(report):
    result = {"scope": report["scope"], "interval_unit": "asset, not view",
              "delta_convention": "candidate minus comparator; lower FLIP/LPIPS is better",
              "splits": {}}
    for split in ("train", "validation"):
        rows = [r for r in report["records"] if r["split"] == split]
        entry = {"attempted_assets": len(rows),
                 "prepared_assets": sum(r["preparation_status"] == "prepared" for r in rows),
                 "preparation_failures": [{"file_id": r["file_id"], "reason": r["reason"]}
                                          for r in rows if r["preparation_status"] != "prepared"],
                 "comparisons": {}}
        for candidate, comparator in (("fixed", "base"), ("fixed_direct", "base"),
                                      ("fixed", "fixed_direct"), ("refine", "base"),
                                      ("refine_direct", "base"), ("refine", "refine_direct")):
            pairs = [r for r in rows if candidate in r.get("variants", {})
                     and comparator in r["variants"]]
            stats = {"paired_assets": len(pairs),
                     "same_triangle_count": all(r["variants"][candidate]["triangles"] ==
                                                r["variants"][comparator]["triangles"] for r in pairs),
                     "metrics": {}}
            for key in KEYS:
                deltas, before, after = [], [], []
                for row in pairs:
                    a = row["variants"][candidate]["mean"][key]
                    b = row["variants"][comparator]["mean"][key]
                    if a is not None and b is not None:
                        deltas.append(a-b)
                        before.append(b)
                        after.append(a)
                stats["metrics"][key] = {"paired_delta": paired_interval(deltas),
                                           "comparator_mean": float(np.mean(before)) if before else None,
                                           "candidate_mean": float(np.mean(after)) if after else None}
            entry["comparisons"][candidate+"_vs_"+comparator] = stats
        entry["decode_failures"] = [{"file_id": r["file_id"], "variant": variant, "reason": state}
                                    for r in rows for variant, state in r.get("decode_status", {}).items()
                                    if state != "decoded"]
        result["splits"][split] = entry
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(json.loads(args.report.read_text()))
    args.out.write_bytes((json.dumps(summary, indent=2)+"\n").encode())
    for split, item in summary["splits"].items():
        print(split, item["prepared_assets"], "/", item["attempted_assets"], "prepared")
        for name, stats in item["comparisons"].items():
            flip = stats["metrics"]["flip"]["paired_delta"]
            print(name, "assets", stats["paired_assets"], "FLIP delta", flip)


if __name__ == "__main__":
    main()
