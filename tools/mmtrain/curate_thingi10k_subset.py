#!/usr/bin/env python3
"""Select a small, license-audited Thingi10K mesh benchmark from metadata CSVs."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import quote, urlparse


LICENSES = {
    "Creative Commons - Attribution - Share Alike",
    "Creative Commons - Attribution",
    "Creative Commons - Public Domain Dedication",
    "Public Domain",
    "GNU - GPL",
    "GNU - LGPL",
    "BSD License",
}
FACE_BINS = ((300, 999), (1_000, 4_999), (5_000, 14_999), (15_000, 50_000))
HF_RAW_ROOT = (
    "https://huggingface.co/datasets/Thingi10K/Thingi10K/resolve/"
    "1e52df627995ba43b7b91143af4bed86f570037a/raw_meshes"
)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def eligible(g: dict[str, str], s: dict[str, str]) -> bool:
    faces = int(g["num_faces"])
    vertices = int(g["num_vertices"])
    return (
        s["License"] in LICENSES
        and any(lo <= faces <= hi for lo, hi in FACE_BINS)
        and 100 <= vertices <= 60_000
        and int(g["num_geometrical_degenerated_faces"]) == 0
        and int(g["num_combinatorial_degenerated_faces"]) == 0
        and int(g["num_duplicated_faces"]) == 0
        and int(g["num_self_intersections"]) == 0
        and g["vertex_manifold"] == "1"
        and g["edge_manifold"] == "1"
        and g["oriented"] == "1"
        and int(g["num_connected_components"]) == 1
    )


def select(geometry: list[dict[str, str]], summary: list[dict[str, str]],
           per_bin: int, seed: str) -> list[dict[str, object]]:
    summaries = {int(row["ID"]): row for row in summary}
    candidates = []
    seen_things = set()
    for g in geometry:
        s = summaries.get(int(g["file_id"]))
        if s is None or not eligible(g, s):
            continue
        thing_id = int(s["Thing ID"])
        if thing_id in seen_things:
            continue
        path = urlparse(s["Link"]).path
        extension = Path(path).suffix.lower()
        if not extension:
            continue
        candidates.append({
            "file_id": int(g["file_id"]),
            "thing_id": thing_id,
            "vertices": int(g["num_vertices"]),
            "faces": int(g["num_faces"]),
            "license": s["License"],
            "source_url": s["Link"],
            "mirror_url": f"{HF_RAW_ROOT}/{int(g['file_id'])}{quote(extension)}",
            "extension": extension,
        })
        seen_things.add(thing_id)

    selected = []
    for lo, hi in FACE_BINS:
        band = [r for r in candidates if lo <= int(r["faces"]) <= hi]
        band.sort(key=lambda r: hashlib.sha256(
            f"{seed}:{r['thing_id']}".encode("utf-8")).hexdigest())
        for index, row in enumerate(band[:per_bin]):
            row["split"] = "train" if index < per_bin // 2 else (
                "validation" if index < 3 * per_bin // 4 else "test")
            row["face_bin"] = f"{lo}-{hi}"
            selected.append(row)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("geometry_csv", type=Path)
    parser.add_argument("summary_csv", type=Path)
    parser.add_argument("--per-bin", type=int, default=8)
    parser.add_argument("--seed", default="ManyMesh-2027")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.per_bin < 4:
        parser.error("per-bin must be at least 4 to populate all three splits")

    rows = select(read_rows(args.geometry_csv), read_rows(args.summary_csv),
                  args.per_bin, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": "Thingi10K metadata v1.5.0",
        "selectionRule": (
            "CC BY/BY-SA, public-domain, GPL, LGPL or BSD; one file per Thing; "
            "one connected component; oriented vertex/edge-manifold; no degenerate, "
            "duplicate or self-intersecting faces; stratified by face count; "
            "stable hash split by Thing ID"
        ),
        "geometryDownloaded": False,
        "items": rows,
    }
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    splits = {name: sum(row["split"] == name for row in rows)
              for name in ("train", "validation", "test")}
    print(f"selected={len(rows)} splits={splits} output={args.out}")


if __name__ == "__main__":
    main()
