"""Freeze unscored, equal-face Poly Haven assets for image-quality evaluation."""

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-topology", type=Path, required=True)
    parser.add_argument("--initial-matches", type=Path, required=True)
    parser.add_argument("--expansion-topology", type=Path, required=True)
    parser.add_argument("--expansion-matches", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    initial_source = read(args.initial_topology)
    initial_matches = read(args.initial_matches)
    expansion_source = read(args.expansion_topology)
    expansion_matches = read(args.expansion_matches)
    sources = {row["asset"]: row for row in initial_source["assets"]}
    sources.update({row["asset"]: row for row in expansion_source["assets"]})

    candidates = []
    for row in initial_matches["rows"]:
        eligibility = row["eligibility"]
        if not eligibility.get("matched_inputs_ready"):
            continue
        candidates.append((row["asset"], row["class"], eligibility,
                           row["export_sha256"],
                           ROOT / "out/polyhaven-matched-face-20261124" / row["asset"] / "exports"))
    for row in expansion_matches["assets"]:
        eligibility = row.get("eligibility")
        if row["status"] != "matched_inputs_ready" or not eligibility:
            continue
        candidates.append((row["asset"], row["candidate_class"], eligibility,
                           eligibility["obj_exports_sha256"],
                           ROOT / "out/polyhaven-matched-face-expansion-20261124" / row["asset"] / "controls"))

    assets = {}
    for slug, category, eligibility, file_hashes, geometry_dir in candidates:
        if slug in assets:
            raise ValueError(f"Duplicate asset slug in matched receipts: {slug}")
        source_row = sources[slug]
        source_sha = eligibility["source_sha256"]
        expected_source_sha = (
            source_row.get("topology", {}).get("input_sha256")
            or source_row.get("extraction", {}).get("obj_sha256"))
        if source_sha != expected_source_sha:
            raise ValueError(f"Source OBJ hash differs from frozen screen for {slug}")
        if not eligibility["matched_inputs_ready"]:
            raise ValueError(f"Ineligible asset included: {slug}")
        if eligibility["manymesh"]["faces"] != eligibility["control_target_faces"]:
            raise ValueError(f"ManyMesh face count mismatch for {slug}")
        expected_files = {"reference.obj", "manymesh.obj", "qem_preserve_border.obj",
                          "meshoptimizer_lock_border.obj", "neutral.mtl"}
        if set(file_hashes) != expected_files:
            raise ValueError(f"Unexpected frozen geometry file set for {slug}")
        for filename, expected_hash in file_hashes.items():
            path = geometry_dir / filename
            if not path.is_file() or digest(path) != expected_hash:
                raise ValueError(f"Frozen geometry hash mismatch: {path}")
        metadata = source_row
        tags = metadata.get("catalog_tags", [])
        collections = sorted(tag.split(":", 1)[1].strip()
                             for tag in tags if tag.casefold().startswith("collection:"))
        if not tags:
            collections = []
        author = metadata.get("authors", metadata.get("credit", {}))
        assets[slug] = {
            "class": category,
            "catalog_category": metadata.get("catalog_category"),
            "collection_tags": collections,
            "authors": author,
            "license": "CC0 per Poly Haven terms",
            "asset_api_url": f"https://api.polyhaven.com/files/{slug}",
            "source_sha256": source_sha,
            "source_faces": eligibility["source_faces"],
            "control_faces": eligibility["control_target_faces"],
            "retention": eligibility["control_target_faces"] / eligibility["source_faces"],
            "geometry_dir": str(geometry_dir.relative_to(ROOT)).replace("\\", "/"),
            "frozen_exports": {
                "source_sha256": source_sha,
                "source_faces": eligibility["source_faces"],
                "control_target_faces": eligibility["control_target_faces"],
                "obj_exports_sha256": file_hashes,
            },
        }

    expected_count = 3 + sum(row["status"] == "matched_inputs_ready"
                             for row in expansion_matches["assets"])
    if len(assets) != expected_count:
        raise ValueError("Matched asset count differs from the source receipts")
    source_hashes = [row["source_sha256"] for row in assets.values()]
    if len(set(source_hashes)) != len(source_hashes):
        raise ValueError("Exact duplicate source geometry hashes detected")

    parents = {slug: slug for slug in assets}

    def find(slug):
        while parents[slug] != slug:
            parents[slug] = parents[parents[slug]]
            slug = parents[slug]
        return slug

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    owner_by_collection = {}
    for slug, row in assets.items():
        for collection in row["collection_tags"]:
            if collection in owner_by_collection:
                union(slug, owner_by_collection[collection])
            else:
                owner_by_collection[collection] = slug
    group_names = {}
    for slug in assets:
        root = find(slug)
        group_names.setdefault(root, []).append(slug)
    for slugs in group_names.values():
        group_id = "collection:" + "+".join(sorted(slugs))
        for slug in slugs:
            assets[slug]["uncertainty_group"] = group_id

    result = {
        "schema": 1,
        "status": "frozen before image scoring",
        "quality_scored": False,
        "selection_rule": "Include every asset that passed the source topology screen and the predeclared 50% ManyMesh/QEM/meshoptimizer face-and-boundary gate; no image quality was used to select assets.",
        "split": "confirmation; no training or tuning on these assets",
        "source_screen_sha256": {
            str(args.initial_topology): digest(args.initial_topology),
            str(args.initial_matches): digest(args.initial_matches),
            str(args.expansion_topology): digest(args.expansion_topology),
            str(args.expansion_matches): digest(args.expansion_matches),
        },
        "protocol": {
            "views": "12 frozen perspective directions at distances 3.3 and 5.2 in the normalized source frame",
            "reference": "full source rasterized at 2x resolution with 4x MSAA and a linear box resolve",
            "candidate_modes": ["native rasterization", "4x MSAA"],
            "equal_budget": "exact matching triangle count across ManyMesh, border-preserving QEM, and meshoptimizer LockBorder; face count is fixed per asset at the pre-screened ManyMesh cut near 50% retention",
            "image_metrics": ["LDR-FLIP (67 pixels/degree)", "pooled-MSE PSNR", "SSIM", "binary silhouette XOR", "coverage MAE"],
            "geometry_metrics": ["sampled bidirectional Chamfer distance", "sampled 95th-percentile surface distance", "sampled normal consistency"],
            "uncertainty_unit": "connected source-collection group; models without a collection tag are singleton groups; report every per-asset result",
            "not_measured": ["LPIPS", "temporal stability", "GPU time", "mobile hardware", "human preference"],
        },
        "assets": assets,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"froze {len(assets)} assets across {len({row['class'] for row in assets.values()})} classes")


if __name__ == "__main__":
    main()
