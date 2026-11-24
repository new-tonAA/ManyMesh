"""Freeze a category-balanced Poly Haven geometry-screen candidate batch."""

import argparse
import hashlib
import json
from pathlib import Path


PINNED_CATALOG_SHA256 = "4639038ef32946ec562b03a56086c53c8edde0179a8d7140ffd79232ea4a0c23"
CLASS_RULES = (
    ("furniture", 10, "top-level category is Furniture"),
    ("botanical", 10, "category tags include plants or flowers"),
    ("rock", 8, "category tags include rocks"),
    ("food", 8, "category tags include food"),
    ("tools", 10, "category tags include tools"),
    ("decor", 10, "top-level category is Decor & Art"),
)
FACE_COUNT_RANGE = (3_000, 100_000)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--previous-selection", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    catalog_bytes = args.catalog.read_bytes()
    catalog_sha = digest(catalog_bytes)
    if catalog_sha != PINNED_CATALOG_SHA256:
        raise SystemExit("The saved Poly Haven catalog differs from its frozen SHA-256")
    catalog = json.loads(catalog_bytes)
    previous_bytes = args.previous_selection.read_bytes()
    previous = json.loads(previous_bytes)
    excluded = {asset for group in previous.values() for asset in group}

    classes = []
    selected = set()
    for label, limit, rule in CLASS_RULES:
        matches = []
        for slug, row in sorted(catalog.items()):
            if slug in excluded or slug in selected or row.get("type") != 2:
                continue
            count = row.get("polycount", 0)
            if not FACE_COUNT_RANGE[0] <= count <= FACE_COUNT_RANGE[1]:
                continue
            tags = {str(tag).casefold() for tag in row.get("categories", [])}
            category = str(row.get("category", ""))
            top_level = category.split("/", 1)[0]
            if label == "furniture" and top_level == "Furniture":
                matches.append((slug, row))
            elif label == "botanical" and tags.intersection({"plants", "flowers"}):
                matches.append((slug, row))
            elif label == "rock" and "rocks" in tags:
                matches.append((slug, row))
            elif label == "food" and "food" in tags:
                matches.append((slug, row))
            elif label == "tools" and "tools" in tags:
                matches.append((slug, row))
            elif label == "decor" and top_level == "Decor & Art":
                matches.append((slug, row))

        if len(matches) < limit:
            raise SystemExit(f"Not enough candidates for {label}: {len(matches)} < {limit}")
        chosen = []
        for slug, row in matches[:limit]:
            selected.add(slug)
            chosen.append({
                "asset": slug,
                "candidate_class": label,
                "catalog_category": row.get("category"),
                "catalog_tags": row.get("categories", []),
                "catalog_polycount": row.get("polycount"),
                "catalog_files_hash": row.get("files_hash"),
                "authors": row.get("authors", {}),
                "description": row.get("description", ""),
            })
        classes.append({"name": label, "selection_rule": rule,
                        "selected": chosen, "catalog_pool_size": len(matches)})

    report = {
        "schema": 1,
        "purpose": "Pre-score static source and fixed 50%-retention matched-face eligibility screen; not a quality comparison or frozen confirmation set.",
        "source": "Poly Haven Public API saved catalog snapshot",
        "catalog_path_at_selection": str(args.catalog),
        "catalog_sha256": catalog_sha,
        "previous_selection_sha256": digest(previous_bytes),
        "asset_api": "https://api.polyhaven.com/files/{asset}",
        "asset_terms": "CC0 per the official Poly Haven API terms; verify current per-asset source and credits in acquisition receipts.",
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
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")
    print(f"froze {len(selected)} candidates in {args.out}")
    for group in classes:
        print(group["name"], len(group["selected"]), "from", group["catalog_pool_size"],
              ", ".join(item["asset"] for item in group["selected"]))


if __name__ == "__main__":
    main()
