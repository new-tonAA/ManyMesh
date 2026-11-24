#!/usr/bin/env python3
"""Select a new licensed candidate pool using catalog metadata only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PINNED_CATALOG_SHA256 = "4639038ef32946ec562b03a56086c53c8edde0179a8d7140ffd79232ea4a0c23"
CLASS_RULES = (
    ("furniture", 10, "top-level category is Furniture"),
    ("botanical", 10, "category tags include plants or flowers"),
    ("rock", 10, "category tags include rocks"),
    ("food", 7, "category tags include food"),
    ("tools", 10, "category tags include tools"),
    ("decor", 10, "top-level category is Decor & Art"),
)
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


def matches(label: str, row: dict) -> bool:
    tags = {str(tag).casefold() for tag in row.get("categories", [])}
    top_level = str(row.get("category", "")).split("/", 1)[0]
    return (
        (label == "furniture" and top_level == "Furniture")
        or (label == "botanical" and bool(tags & {"plants", "flowers"}))
        or (label == "rock" and "rocks" in tags)
        or (label == "food" and "food" in tags)
        or (label == "tools" and "tools" in tags)
        or (label == "decor" and top_level == "Decor & Art")
    )


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
    classes = []
    for label, limit, rule in CLASS_RULES:
        rows = []
        for slug, row in sorted(catalog.items()):
            count = row.get("polycount", 0)
            if (slug in excluded or slug in selected or row.get("type") != 2
                    or not FACE_COUNT_RANGE[0] <= count <= FACE_COUNT_RANGE[1]
                    or not matches(label, row)):
                continue
            rows.append((slug, row))
        if len(rows) < limit:
            raise SystemExit(f"Not enough {label} candidates: {len(rows)} < {limit}")

        candidates = []
        for slug, row in rows[:limit]:
            selected.add(slug)
            candidates.append({
                "asset": slug,
                "candidate_class": label,
                "catalog_category": row.get("category"),
                "catalog_tags": row.get("categories", []),
                "catalog_polycount": row.get("polycount"),
                "catalog_files_hash": row.get("files_hash"),
                "authors": row.get("authors", {}),
                "description": row.get("description", ""),
            })
        classes.append({
            "name": label,
            "selection_rule": rule,
            "catalog_pool_size": len(rows),
            "selected": candidates,
        })

    report = {
        "schema": 1,
        "purpose": (
            "Fresh pre-score source pool for licensing, topology, and matched-face "
            "eligibility only; not a frozen held-out test set."
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
            "ordering": "ascending asset slug within each class",
            "quality_or_render_data_used": False,
            "classes": classes,
        },
        "selected_count": len(selected),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"selected {len(selected)} fresh candidates in {args.output}")
    for group in classes:
        print(group["name"], len(group["selected"]), "of", group["catalog_pool_size"])


if __name__ == "__main__":
    main()
