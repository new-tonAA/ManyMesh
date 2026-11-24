#!/usr/bin/env python3
"""Select a broad fresh Poly Haven pool from a pinned catalog snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PINNED_CATALOG_SHA256 = "4639038ef32946ec562b03a56086c53c8edde0179a8d7140ffd79232ea4a0c23"
TOP_LEVEL_CATEGORIES = (
    "Furniture",
    "Containers & Storage",
    "Tools & Equipment",
    "Lighting",
    "Electronics & Appliances",
    "Industrial & Infrastructure",
    "Apparel & Personal Items",
    "Nature",
    "Food & Kitchen",
    "Decor & Art",
    "Architecture",
    "Vehicles & Transport",
    "Office & Stationery",
    "Weapons",
    "Leisure",
)
ASSETS_PER_CATEGORY = 6
FACE_COUNT_RANGE = (250, 250_000)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def selected_assets(path: Path) -> set[str]:
    data = json.loads(path.read_bytes())
    if "selection" in data:
        groups = data["selection"]["classes"]
        return {row["asset"] for group in groups for row in group["selected"]}
    if "classes" in data:
        return {row["asset"] for group in data["classes"] for row in group["selected"]}
    return {
        slug for values in data.values() if isinstance(values, list)
        for slug in values if isinstance(slug, str)
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--previous-selection", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    catalog_bytes = args.catalog.read_bytes()
    catalog_sha = digest(catalog_bytes)
    if catalog_sha != PINNED_CATALOG_SHA256:
        raise SystemExit("Saved catalog does not match the pinned SHA-256")
    catalog = json.loads(catalog_bytes)
    exclusion_hashes = {
        str(path): digest(path.read_bytes()) for path in args.previous_selection
    }
    excluded = set().union(*(selected_assets(path) for path in args.previous_selection))

    selected: set[str] = set()
    groups = []
    for category in TOP_LEVEL_CATEGORIES:
        matches = [
            (slug, row) for slug, row in sorted(catalog.items())
            if slug not in excluded and slug not in selected
            and row.get("type") == 2
            and FACE_COUNT_RANGE[0] <= row.get("polycount", 0) <= FACE_COUNT_RANGE[1]
            and str(row.get("category", "")).split("/", 1)[0] == category
        ]
        if len(matches) < ASSETS_PER_CATEGORY:
            raise SystemExit(
                f"Not enough {category} candidates: {len(matches)} < {ASSETS_PER_CATEGORY}"
            )
        rows = []
        for slug, row in matches[:ASSETS_PER_CATEGORY]:
            selected.add(slug)
            rows.append({
                "asset": slug,
                "candidate_class": category,
                "catalog_category": row.get("category"),
                "catalog_tags": row.get("categories", []),
                "catalog_polycount": row.get("polycount"),
                "catalog_files_hash": row.get("files_hash"),
                "authors": row.get("authors", {}),
                "description": row.get("description", ""),
            })
        groups.append({
            "name": category,
            "selection_rule": "top-level catalog category match",
            "catalog_pool_size": len(matches),
            "selected": rows,
        })

    report = {
        "schema": 1,
        "purpose": (
            "Broad pre-score candidate pool for independent geometry confirmation; "
            "not a frozen test set or quality result."
        ),
        "source": "Poly Haven Public API pinned catalog snapshot",
        "catalog_sha256": catalog_sha,
        "selector_sha256": digest(Path(__file__).read_bytes()),
        "previous_selection_sha256": exclusion_hashes,
        "asset_api": "https://api.polyhaven.com/files/{asset}",
        "asset_terms": (
            "CC0 under the pinned catalog source; acquisition records must verify "
            "current per-asset API metadata and credits."
        ),
        "selection": {
            "previously_selected_slugs_excluded": sorted(excluded),
            "candidate_type": 2,
            "catalog_polycount_inclusive_range": list(FACE_COUNT_RANGE),
            "assets_per_top_level_category": ASSETS_PER_CATEGORY,
            "ordering": "ascending asset slug within category",
            "quality_or_render_data_used": False,
            "classes": groups,
        },
        "selected_count": len(selected),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"selected {len(selected)} fresh assets in {args.output}")
    for group in groups:
        print(group["name"], len(group["selected"]), "of", group["catalog_pool_size"])


if __name__ == "__main__":
    main()
