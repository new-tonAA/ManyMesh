#!/usr/bin/env python3
"""Freeze a fresh, unscored Poly Haven geometry-confirmation candidate pool."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def asset_family(slug: str) -> str:
    """Group numeric variants sharing the same asset-series stem."""
    return re.sub(r"_\d+$", "", slug)


def read_json(path: Path) -> tuple[bytes, dict]:
    payload = path.read_bytes()
    return payload, json.loads(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, nargs="+", required=True)
    parser.add_argument("--source-screen", type=Path, nargs="+", required=True)
    parser.add_argument("--matched-face-screen", type=Path, nargs="+", required=True)
    parser.add_argument("--prior-source-record", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (len(args.selection) == len(args.source_screen)
            == len(args.matched_face_screen)):
        parser.error("Supply one source and matched-face report per selection")

    assets = []
    evidence = []
    current_source_rows = []
    for selection_path, source_path, matched_path in zip(
            args.selection, args.source_screen, args.matched_face_screen):
        selection_bytes, selection = read_json(selection_path)
        source_bytes, source = read_json(source_path)
        matched_bytes, matched = read_json(matched_path)
        if source.get("quality_scored") or source.get("image_or_render_data_used"):
            raise ValueError(f"Source screen used image/quality results: {source_path}")
        if matched.get("source_screen_quality_scored"):
            raise ValueError(f"Matched-face screen is not pre-score: {matched_path}")
        if matched.get("source_screen_sha256") != sha256(source_bytes):
            raise ValueError(f"Matched-face screen references a different source receipt: {matched_path}")
        if source.get("selection_sha256") != sha256(selection_bytes):
            raise ValueError(f"Source screen references a different selection: {source_path}")
        if not matched.get("complete"):
            raise ValueError(f"Matched-face screen is incomplete: {matched_path}")

        source_rows = {row["asset"]: row for row in source["assets"]}
        current_source_rows.extend(source["assets"])
        selection_rows = {
            row["asset"]: row
            for group in selection["selection"]["classes"]
            for row in group["selected"]
        }
        if len(selection_rows) != selection["selected_count"]:
            raise ValueError(f"Selection count mismatch: {selection_path}")

        for row in matched["assets"]:
            if row.get("status") != "matched_inputs_ready":
                continue
            slug = row["asset"]
            source_row = source_rows[slug]
            catalog_row = selection_rows[slug]
            extraction = source_row.get("extraction", {})
            eligibility = row["eligibility"]
            if (source_row.get("acquisition_status") != "pass"
                    or extraction.get("topology_status") != "pass"):
                raise ValueError(f"Matched asset lacks a source-topology pass: {slug}")
            if (not eligibility.get("matched_inputs_ready")
                    or not eligibility.get("candidate_in_band")):
                raise ValueError(f"Matched asset lacks a valid retention budget: {slug}")
            controls = eligibility["controls"]
            for control in ("qem_preserve_border", "meshoptimizer_lock_border"):
                check = controls[control]
                if (not check.get("eligible") or not check.get("boundary_preserved")
                        or check.get("faces") != eligibility.get("control_target_faces")):
                    raise ValueError(f"Matched asset failed {control} checks: {slug}")

            files = source_row["source_files"]
            assets.append({
                "asset": slug,
                "candidate_class": catalog_row["candidate_class"],
                "top_level_category": catalog_row["catalog_category"].split("/", 1)[0],
                "catalog_category": catalog_row["catalog_category"],
                "authors": catalog_row.get("authors", {}),
                "source_family": asset_family(slug),
                "license": source_row["asset_license"],
                "source_url": files["gltf"]["url"],
                "gltf_sha256": files["gltf"]["sha256"],
                "buffer_url": files["bin"]["url"],
                "buffer_sha256": files["bin"]["sha256"],
                "source_geometry_sha256": extraction["obj_sha256"],
                "source_faces": row["source_faces"],
                "target_faces": eligibility["control_target_faces"],
                "retention": eligibility["candidate_ratio"],
                "manymesh_boundary_preserved": eligibility["manymesh"]["boundary_preserved"],
                "qem_eligible": controls["qem_preserve_border"]["eligible"],
                "meshoptimizer_eligible": controls["meshoptimizer_lock_border"]["eligible"],
                "quality_scored": False,
            })

        evidence.append({
            "selection_path": str(selection_path),
            "selection_sha256": sha256(selection_bytes),
            "source_screen_path": str(source_path),
            "source_screen_sha256": sha256(source_bytes),
            "matched_face_screen_path": str(matched_path),
            "matched_face_screen_sha256": sha256(matched_bytes),
            "mmgeo_sha256": matched["mmgeo_sha256"],
        })

    source_file_hashes: dict[str, dict[str, str]] = {"gltf": {}, "bin": {}}
    source_record_count = 0
    prior_record_hashes = {}
    for path in args.prior_source_record:
        prior_bytes, prior = read_json(path)
        prior_record_hashes[str(path)] = sha256(prior_bytes)
        prior_rows = prior if isinstance(prior, list) else prior["assets"]
        for row in prior_rows:
            files = row.get("assets", row.get("source_files", {}))
            if not files or not files.get("gltf") or not files.get("bin"):
                continue
            source_record_count += 1
            for kind in ("gltf", "bin"):
                source_file_hashes[kind].setdefault(files[kind]["sha256"], row["asset"])

    for row in current_source_rows:
        files = row.get("source_files", {})
        if not files or not files.get("gltf") or not files.get("bin"):
            continue
        source_record_count += 1
        for kind in ("gltf", "bin"):
            source_file_hashes[kind].setdefault(files[kind]["sha256"], row["asset"])

    if (len(source_file_hashes["gltf"]) != source_record_count
            or len(source_file_hashes["bin"]) != source_record_count):
        raise ValueError("Duplicate source file hash across screened Poly Haven assets")

    if len({row["asset"] for row in assets}) != len(assets):
        raise ValueError("Duplicate asset slug across candidate pools")
    for field in ("gltf_sha256", "buffer_sha256", "source_geometry_sha256"):
        values = [row[field] for row in assets]
        if len(set(values)) != len(values):
            raise ValueError(f"Duplicate {field} in candidate pool")

    family_members: dict[str, list[str]] = {}
    for row in assets:
        family_members.setdefault(row["source_family"], []).append(row["asset"])
    categories = Counter(row["top_level_category"] for row in assets)
    if len(assets) < 20 or len(categories) < 5 or len(family_members) < 20:
        raise ValueError("Candidate pool does not meet the 20-model/five-category gate")

    receipt = {
        "schema": 1,
        "status": "reserved_unscored_candidate_pool",
        "purpose": (
            "Reserve a fresh Poly Haven asset pool for later confirmation; this is "
            "not the final camera/view protocol and contains no image-quality results."
        ),
        "license_basis": (
            "Poly Haven CC0 terms; per-asset API records, credits, file hashes, "
            "and source URLs are retained in the source-screen receipts."
        ),
        "selection_used_render_or_quality_data": False,
        "matched_face_preflight_scored_quality": False,
        "eligibility_rule": (
            "ManyMesh 49%-51% retention; QEM and meshoptimizer controls at the "
            "exact ManyMesh face count; all three topology checks pass and the "
            "source boundary is preserved."
        ),
        "source_family_rule": (
            "Remove a trailing underscore plus digits from the slug; all members "
            "of a resulting series are one uncertainty group."
        ),
        "source_family_group_count": len(family_members),
        "family_groups": family_members,
        "top_level_category_counts": dict(sorted(categories.items())),
        "cross_pool_source_hash_audit": {
            "source_file_records": source_record_count,
            "unique_gltf_hashes": len(source_file_hashes["gltf"]),
            "unique_bin_hashes": len(source_file_hashes["bin"]),
            "prior_source_records": prior_record_hashes,
        },
        "evidence": evidence,
        "assets": assets,
        "pending_before_any_quality_scoring": [
            "Freeze training and reserved camera views, lighting, render reference, metrics, and practical-effect margins.",
            "Confirm the final method and complete-cost protocol after the two-asset placement-control gate.",
        ],
        "limitations": [
            "A pre-score input pool is not positive method evidence.",
            "The reserved assets must be scored only after the method and view protocol are frozen.",
            "The source topology audit does not check geometric self-intersections.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({
        "assets": len(assets),
        "source_families": len(family_members),
        "top_level_categories": dict(sorted(categories.items())),
        "quality_scored": False,
    }, indent=2))


if __name__ == "__main__":
    main()
