"""Summarize per-asset silhouette-XOR error shares from frozen quality receipts."""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INPUTS = (
    ROOT / "tools/mmtrain/cluster_decoder_qem_meshopt_validation_50pct_20261122.json",
    ROOT / "tools/mmtrain/cluster_decoder_qem_meshopt_train_50pct_20261122.json",
    ROOT / "tools/mmtrain/cluster_decoder_qem_meshopt_validation_70pct_20261122.json",
    ROOT / "tools/mmtrain/cluster_decoder_qem_meshopt_train_70pct_20261122.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def asset_shares(path: Path) -> dict[str, list[tuple[int, float]]]:
    report = json.loads(path.read_text(encoding="utf-8"))
    output: dict[str, list[tuple[int, float]]] = {"qem": [], "meshoptimizer": []}
    for record in report["records"]:
        for method in output:
            views = record.get("per_view", {}).get(method, [])
            shares = [
                view["silhouette_xor_mse_share"]
                for view in views
                if isinstance(view.get("silhouette_xor_mse_share"), (int, float))
            ]
            if shares:
                output[method].append((record["file_id"], statistics.mean(shares)))
    return output


def main() -> None:
    print("| Split | Retention | Method | Assets | Asset means >50% | Median share | Range |")
    print("|---|---:|---|---:|---:|---:|---:|")
    for path in INPUTS:
        report = json.loads(path.read_text(encoding="utf-8"))
        split = report["split"].capitalize()
        retention = f"{report['target_retention']:.0%}"
        for method, values in asset_shares(path).items():
            shares = [share for _, share in values]
            if not shares:
                continue
            count = sum(share > 0.5 for share in shares)
            print(
                f"| {split} | {retention} | {method} | {len(shares)} | "
                f"{count}/{len(shares)} | {statistics.median(shares):.1%} | "
                f"{min(shares):.1%}–{max(shares):.1%} |"
            )
    print(f"\nScript SHA-256: `{sha256(Path(__file__))}`")
    for path in INPUTS:
        print(f"Input SHA-256 ({path.name}): `{sha256(path)}`")


if __name__ == "__main__":
    main()
