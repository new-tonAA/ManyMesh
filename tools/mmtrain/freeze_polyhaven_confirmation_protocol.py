#!/usr/bin/env python3
"""Freeze the unscored 30-model confirmation inputs and camera protocol."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
FILES = ("reference.obj", "manymesh.obj", "qem_preserve_border.obj",
         "meshoptimizer_lock_border.obj", "neutral.mtl")
PROTOCOL_SOURCES = (
    "tools/mmtrain/fit_appearance_cuda.py",
    "tools/mmtrain/bench_appearance_controls.py",
    "tools/mmtrain/score_polyhaven_quality_cohort.py",
    "tools/mmtrain/score_polyhaven_lpips_supplement.py",
    "tools/mmtrain/audit_polyhaven_multiplicity.py",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def training_eyes():
    index = np.arange(16, dtype=np.float64)
    y = 1 - (2 * index + 1) / len(index)
    azimuth = 1.16 + index * np.pi * (3 - np.sqrt(5))
    radius = np.sqrt(1 - y * y)
    directions = np.stack((radius * np.cos(azimuth), y, radius * np.sin(azimuth)), axis=1)
    cameras = directions[[(5 * i) % len(index) for i in range(len(index))]]
    near_first = np.arange(len(index)) % 2 == 0
    near = np.where(near_first, 3.3, 5.2)
    far = np.where(near_first, 5.2, 3.3)
    return np.concatenate((cameras * near[:, None], cameras * far[:, None]))


def evaluation_views():
    views = []
    for view in range(12):
        y = 1 - (2 * view + 1) / 12
        angle = 0.37 + view * np.pi * (3 - np.sqrt(5))
        radius = np.sqrt(1 - y * y)
        direction = np.array([radius * np.cos(angle), y, radius * np.sin(angle)])
        for distance in (3.3, 5.2):
            views.append({"view": view, "distance": distance,
                          "eye": (distance * direction).tolist()})
    return views


def direction_separation(train, evaluation):
    train_directions = train / np.linalg.norm(train, axis=1, keepdims=True)
    eval_directions = np.asarray([row["eye"] for row in evaluation], dtype=np.float64)
    eval_directions /= np.linalg.norm(eval_directions, axis=1, keepdims=True)
    dots = np.clip(train_directions @ eval_directions.T, -1.0, 1.0)
    return float(np.rad2deg(np.arccos(dots.max())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=ROOT / "tools/mmtrain/polyhaven_confirmation_pool_20261125.json")
    parser.add_argument("--fresh-matches", type=Path, default=ROOT / "tools/mmtrain/polyhaven_fresh_asset_matched_face_screen_20261125.json")
    parser.add_argument("--category-matches", type=Path, default=ROOT / "tools/mmtrain/polyhaven_category_pool_matched_face_screen_20261125.json")
    parser.add_argument("--pilot-metrics", type=Path, default=ROOT / "tools/mmtrain/polyhaven_quality_metrics_20261124.json")
    parser.add_argument("--output", type=Path, default=ROOT / "tools/mmtrain/polyhaven_confirmation_protocol_20261125.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "tools/mmtrain/POLYHAVEN_CONFIRMATION_PROTOCOL_20261125.md")
    args = parser.parse_args()

    pool = json.loads(args.pool.read_text(encoding="utf-8"))
    fresh = json.loads(args.fresh_matches.read_text(encoding="utf-8"))
    broad = json.loads(args.category_matches.read_text(encoding="utf-8"))
    pilot = json.loads(args.pilot_metrics.read_text(encoding="utf-8"))
    if pool.get("status") != "reserved_unscored_candidate_pool" or pool.get("quality_scored"):
        raise ValueError("The input pool is not in its reserved, unscored state")
    if fresh.get("complete") is not True or broad.get("complete") is not True:
        raise ValueError("Both matched-face preflights must be complete")
    if fresh.get("source_screen_quality_scored") or broad.get("source_screen_quality_scored"):
        raise ValueError("A source preflight used quality data")
    if pilot.get("status") != "complete" or pilot.get("assets") != 21:
        raise ValueError("The pilot-effect receipt is incomplete")

    pool_evidence = {row["matched_face_screen_path"].replace("\\", "/"): row["matched_face_screen_sha256"]
                     for row in pool["evidence"]}
    sources = {
        args.fresh_matches.relative_to(ROOT).as_posix(): (fresh, args.fresh_matches),
        args.category_matches.relative_to(ROOT).as_posix(): (broad, args.category_matches),
    }
    matches_by_asset = {}
    for relative, expected_hash in pool_evidence.items():
        if relative not in sources or sha256(sources[relative][1]) != expected_hash:
            raise ValueError(f"Matched-face source hash mismatch: {relative}")
        report, _ = sources[relative]
        for row in report["assets"]:
            if row["status"] == "matched_inputs_ready":
                if row["asset"] in matches_by_asset:
                    raise ValueError(f"Duplicate matched asset: {row['asset']}")
                matches_by_asset[row["asset"]] = (row, relative)

    frozen_assets = {}
    for row in pool["assets"]:
        if row["quality_scored"]:
            raise ValueError(f"Pool asset was already quality scored: {row['asset']}")
        matched_pair = matches_by_asset.get(row["asset"])
        if not matched_pair:
            raise ValueError(f"Missing matched-face receipt: {row['asset']}")
        matched, matched_path = matched_pair
        eligibility = matched["eligibility"]
        if (eligibility["source_sha256"] != row["source_geometry_sha256"]
                or eligibility["source_faces"] != row["source_faces"]
                or eligibility["control_target_faces"] != row["target_faces"]
                or not eligibility["matched_inputs_ready"]
                or not eligibility["manymesh"]["boundary_preserved"]
                or not eligibility["controls"]["qem_preserve_border"]["eligible"]
                or not eligibility["controls"]["meshoptimizer_lock_border"]["eligible"]):
            raise ValueError(f"Pool geometry eligibility changed: {row['asset']}")
        run = next(x for x in matched["runs"] if x["stage"] == "matched_face_preflight")
        command = run["command"]
        export_arg = command.index("--export-obj-dir")
        geometry_dir = (ROOT / Path(command[export_arg + 1].replace("\\", "/"))).resolve()
        file_hashes = eligibility["obj_exports_sha256"]
        if set(file_hashes) != set(FILES):
            raise ValueError(f"Unexpected export set for {row['asset']}")
        for filename in FILES:
            file_path = geometry_dir / filename
            if not file_path.is_file() or sha256(file_path) != file_hashes[filename]:
                raise ValueError(f"Frozen geometry export mismatch: {file_path}")
        frozen_assets[row["asset"]] = {
            "category": row["top_level_category"],
            "source_family": row["source_family"],
            "uncertainty_group": row["source_family"],
            "license": row["license"],
            "creator_credit": row["authors"],
            "source_url": row["source_url"],
            "source_buffer_url": row["buffer_url"],
            "source_file_sha256": {"gltf": row["gltf_sha256"], "buffer": row["buffer_sha256"]},
            "source_geometry_sha256": row["source_geometry_sha256"],
            "source_faces": row["source_faces"],
            "matched_faces": row["target_faces"],
            "retention": row["retention"],
            "geometry_dir": geometry_dir.relative_to(ROOT).as_posix(),
            "matched_face_receipt": matched_path,
            "geometry_exports_sha256": file_hashes,
            "quality_scored_before_freeze": False,
        }

    if len(frozen_assets) != 30:
        raise ValueError(f"Expected all 30 reserved assets, found {len(frozen_assets)}")
    groups = {row["uncertainty_group"] for row in frozen_assets.values()}
    categories = {row["category"] for row in frozen_assets.values()}
    if len(groups) != 25 or len(categories) != 9:
        raise ValueError(f"Unexpected group/category counts: {len(groups)} / {len(categories)}")

    train_eyes = training_eyes()
    test_views = evaluation_views()
    min_separation = direction_separation(train_eyes, test_views)
    if min_separation <= 0.0:
        raise ValueError("Training and evaluation directions overlap")

    pilot_deltas = pilot["paired_group_deltas_manymesh_minus_control"]["msaa4"]
    practical_margins = {}
    for control in ("qem_preserve_border", "meshoptimizer_lock_border"):
        pilot_gap = max(0.0, pilot_deltas[control]["flip"]["group_mean_delta"])
        practical_margins[control] = {
            "primary_metric": "LDR-FLIP",
            "minimum_improvement": 0.5 * pilot_gap,
            "units": "absolute LDR-FLIP score",
            "derivation": "50% of the 21-model development-cohort ManyMesh-minus-control mean gap under 4x MSAA",
            "pilot_gap": pilot_gap,
        }

    result = {
        "schema": 1,
        "status": "frozen confirmation inputs and protocol; method pending",
        "quality_scored": False,
        "scoring_enabled": False,
        "study_role": (
            "Unseen-asset confirmation of a single method configuration after it passes the two-asset development gate. "
            "The algorithm may fit each asset using its frozen training views; no settings may be tuned from confirmation scores."
        ),
        "pool_sha256": sha256(args.pool),
        "matched_face_receipts": {
            args.fresh_matches.relative_to(ROOT).as_posix(): sha256(args.fresh_matches),
            args.category_matches.relative_to(ROOT).as_posix(): sha256(args.category_matches),
        },
        "pilot_metrics_sha256": sha256(args.pilot_metrics),
        "freeze_script_sha256": sha256(Path(__file__)),
        "protocol_source_sha256": {path: sha256(ROOT / path) for path in PROTOCOL_SOURCES},
        "assets": frozen_assets,
        "counts": {"assets": len(frozen_assets), "source_families": len(groups),
                   "categories": len(categories)},
        "camera_protocol": {
            "training_source": "fit_appearance_cuda.py training_eyes(), frozen 2026-11-24",
            "training_views": train_eyes.tolist(),
            "training_count": len(train_eyes),
            "training_resolution": [128, 128],
            "training_render_resolution": [256, 256],
            "evaluation_source": "bench_appearance_controls.py camera_eyes(), frozen 2026-11-24",
            "evaluation_views": test_views,
            "evaluation_count": len(test_views),
            "evaluation_resolution": [640, 360],
            "minimum_train_to_eval_angular_separation_degrees": min_separation,
        },
        "render_protocol": {
            "reference": "full source OBJ at 1280x720, 4x MSAA, linear 2x2 box resolve to 640x360",
            "candidate_sampling": ["native rasterization", "4x MSAA"],
            "lighting": "fixed diffuse material and camera light from the frozen placement control",
            "equal_face_budget": "ManyMesh, QEM, and meshoptimizer cuts share each asset's exact pre-screened 49%-51% face count",
        },
        "metrics": {
            "primary": ["LDR-FLIP (67 pixels/degree)"],
            "guardrails": ["pooled-MSE PSNR", "SSIM", "silhouette XOR"],
            "exploratory": ["LPIPS SqueezeNet v0.1 on replicated grayscale 8-bit sRGB", "sampled bidirectional surface distance", "sampled normal consistency"],
            "unavailable": ["coverage MAE from the current scorer", "temporal stability", "equal-frame-time cost", "mobile GPU performance", "human preference"],
        },
        "decision_rule": {
            "familywise_interval": "two-sided 95% max-|t| cluster bootstrap over 25 source-family groups, 200000 draws, seed 20261125, shared resamples over the 16 primary metric/control/mode endpoints",
            "primary_pass": "Under 4x MSAA, the simultaneous lower bound for LDR-FLIP improvement must exceed the frozen practical margin against both QEM and meshoptimizer.",
            "practical_margins": practical_margins,
            "guardrail_pass": "Under 4x MSAA, no simultaneous interval may show a PSNR, SSIM, or silhouette-XOR regression against either control; report native-mode effects as secondary.",
            "integrity_pass": "All 30 assets remain in the report; any missing render, topology failure, boundary change, or face-count mismatch is reported and cannot be silently excluded.",
            "stop": "Reject this method configuration if the primary margin is missed, a guardrail regression is supported, or any topology/boundary gate fails. Do not tune and rescore this confirmation cohort.",
        },
        "scope_limits": [
            "This is equal-face desktop image-quality evidence, not equal-time evidence.",
            "The protocol compares native and 4x MSAA; it does not establish superiority over SMAA or an upscaler.",
            "Per-asset fitting with disjoint views tests the frozen procedure across these assets; it is not cross-asset neural-model generalization.",
            "The final candidate method/configuration is not frozen yet; this manifest deliberately cannot be consumed by the current score runner.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8", newline="\n")
    markdown = [
        "# Poly Haven confirmation protocol",
        "",
        "Frozen 2026-11-25 before image-quality scoring. The method configuration is still pending, so this protocol does not authorize scoring yet.",
        "",
        "## Frozen inputs",
        "",
        f"- {len(frozen_assets)} licensed Poly Haven CC0 assets, {len(groups)} source-family uncertainty groups, and {len(categories)} categories.",
        "- ManyMesh, border-preserving QEM, and meshoptimizer inputs have the same per-asset face count (49%-51% source retention). The full source mesh is the image reference.",
        "- Source files, matched-face receipts, OBJ exports, and this manifest are hash-pinned. Geometry-only preflight retained every asset; it did not render or score images.",
        "",
        "## Frozen views and rendering",
        "",
        f"- Per-asset fitting may use the 32 frozen training cameras at 128x128 (rendered at 256x256); evaluation uses 24 reserved view-distance pairs at 640x360. Closest training/evaluation direction: {min_separation:.2f} degrees.",
        "- The full source reference is rendered at 1280x720 with 4x MSAA, then linearly box-resolved to 640x360. Candidates are evaluated with native rasterization and 4x MSAA, under identical lighting.",
        "- This is matched-face desktop image-quality evidence. It is not an equal-time, mobile, or temporal comparison.",
        "",
        "## Metrics and decision rule",
        "",
        "- Primary: LDR-FLIP at 67 pixels/degree. Guardrails: pooled-MSE PSNR, SSIM, and silhouette XOR. LPIPS and sampled surface/normal distances are exploratory.",
        "- Use paired uncertainty over the 25 source-family groups: a two-sided 95% max-|t| cluster bootstrap with 200,000 draws and seed 20261125, sharing resamples over the 16 primary metric/control/sampling endpoints.",
        f"- Under 4x MSAA, the simultaneous lower bound for LDR-FLIP improvement must exceed both frozen margins: QEM {practical_margins['qem_preserve_border']['minimum_improvement']:.9f}; meshoptimizer {practical_margins['meshoptimizer_lock_border']['minimum_improvement']:.9f}. Improvement is control error minus candidate error.",
        "- The margins equal half the corresponding mean ManyMesh deficit in the previously examined 21-model development cohort. They are project-specific challenge thresholds, not universal perceptual just-noticeable differences.",
        "- No supported simultaneous regression is allowed on the three guardrails. A confirmatory pass requires valid outputs for all 30 assets and all frozen topology, boundary, and face-count checks. Keep every failure visible; an incomplete run cannot pass. Resume only the identical frozen configuration after a tooling failure, and never tune from confirmation scores.",
        "",
        "## Current gate",
        "",
        "Scoring remains disabled until one method configuration passes the two-asset development gate and is frozen. A candidate must be specified as a single procedure before any confirmation score is observed. Per-asset fitting on disjoint views tests this frozen procedure across assets; it does not test transfer of a cross-asset learned model.",
        "",
        "This protocol does not establish superiority over SMAA or an upscaler, equal-frame-time quality, mobile performance, temporal stability, or human preference. Coverage MAE is unavailable in the current scorer.",
        "",
        "## Reproduction and hashes",
        "",
        "Run the geometry-only freeze audit (it verifies every OBJ against its source receipt and does not score images):",
        "",
        "```powershell",
        "python tools/mmtrain/freeze_polyhaven_confirmation_protocol.py",
        "```",
        "",
        f"- Protocol manifest: [JSON](polyhaven_confirmation_protocol_20261125.json) (SHA-256 `{sha256(args.output)}`).",
        f"- Candidate pool: [pool manifest](polyhaven_confirmation_pool_20261125.json) (SHA-256 `{sha256(args.pool)}`); selection details are in [the report](POLYHAVEN_CONFIRMATION_POOL_20261125.md).",
        f"- Development effect source: [21-model quality report](POLYHAVEN_QUALITY_SCREEN_20261124.md) and [metric receipt](polyhaven_quality_metrics_20261124.json) (SHA-256 `{sha256(args.pilot_metrics)}`).",
        f"- Freeze generator SHA-256: `{sha256(Path(__file__))}`. Camera, scoring, and multiplicity-analysis source hashes are listed in the JSON manifest.",
    ]
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text("\n".join(markdown) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"assets": len(frozen_assets), "groups": len(groups),
                      "categories": len(categories), "quality_scored": False,
                      "scoring_enabled": False,
                      "min_train_test_angle_degrees": min_separation,
                      "flip_margins": practical_margins,
                      "manifest": args.output.relative_to(ROOT).as_posix(),
                      "report": args.markdown.relative_to(ROOT).as_posix()}, indent=2))


if __name__ == "__main__":
    main()
