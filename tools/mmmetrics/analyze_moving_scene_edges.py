"""Replay moving-scene captures for contour error attribution and frame LPIPS."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import cv2
import numpy as np

from perceptual import ImageMetrics


BAND_RADIUS = 2
STRIDE = 4
REGIONS = ("silhouette_xor", "same_coverage_edge_band", "remaining")
BACKBONE = "squeezenet1_1-b8a52dc0.pth"
BACKBONE_SHA256 = "b8a52dc049b60e4b6ab68ad0df457362afab8b6304b2febdc1650a5dab4d7e7b"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(path, media):
    if sha256(path) != media["sha256"]:
        raise ValueError(f"Video digest changed: {path}")
    reader = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    if not reader.isOpened():
        raise ValueError(f"FFmpeg could not open {path}")
    frames = []
    try:
        while True:
            ok, image = reader.read()
            if not ok:
                break
            gray, green, red = cv2.split(image)
            if (gray.shape != (media["height"], media["width"])
                    or not np.array_equal(gray, green) or not np.array_equal(gray, red)):
                raise ValueError(f"Unexpected decoded shape or color in {path}")
            frames.append(gray)
    finally:
        reader.release()
    if len(frames) != media["frameCount"]:
        raise ValueError(f"Unexpected decoded frame count in {path}")
    return frames


def attribute(reference, candidate):
    reference_mask = reference > 0
    candidate_mask = candidate > 0
    xor = reference_mask != candidate_mask
    kernel = np.ones((2 * BAND_RADIUS + 1,) * 2, dtype=np.uint8)
    reference_band, candidate_band = (
        cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_GRADIENT, kernel,
                         borderType=cv2.BORDER_REPLICATE).astype(bool)
        for mask in (reference_mask, candidate_mask))
    edge = (reference_band | candidate_band) & ~xor
    rest = ~(xor | edge)
    squared = (reference.astype(np.int32) - candidate.astype(np.int32)) ** 2
    return {name: [int(mask.sum()), int(squared[mask].sum(dtype=np.int64))]
            for name, mask in zip(REGIONS, (xor, edge, rest), strict=True)}


def validate_capture(reference, candidate, regions, original):
    mse = sum(entry[1] for entry in regions.values()) / (reference.size * 255**2)
    psnr = -10 * np.log10(mse) if mse else None
    expected_psnr = original["psnr_db"]
    valid_psnr = (psnr is None and expected_psnr is None or
                  psnr is not None and expected_psnr is not None and
                  np.isclose(psnr, expected_psnr, atol=1e-10, rtol=0.0))
    if not valid_psnr or regions["silhouette_xor"][0] / candidate.size != original["silhouette_xor_fraction"]:
        raise ValueError("Decoded candidate disagrees with its original PSNR or silhouette record")


def pooled_attribution(rows, key):
    totals = np.array([[r[key][area] for area in REGIONS] for r in rows], dtype=np.int64).sum(axis=0)
    count, error = totals.sum(axis=0)
    return {area: {"pixel_fraction": float(n / count),
                   "squared_error_share": float(sse / error) if error else None}
            for area, (n, sse) in zip(REGIONS, totals, strict=True)}


def evaluate(references, same_sampling, images, originals, metrics, cached_lpips):
    rows = []
    paired = zip(references, same_sampling, images, originals, strict=True)
    for frame, (reference, source, candidate, original) in enumerate(paired):
        regions = attribute(reference, candidate)
        validate_capture(reference, candidate, regions, original)
        row = {"frame": frame, "region_pixel_count_and_sse": regions,
               "same_sampling_region_pixel_count_and_sse": attribute(source, candidate)}
        if frame % STRIDE == 0:
            if frame not in cached_lpips:
                ref_rgb, img_rgb = (np.repeat(gray[..., None], 3, axis=2).astype(np.float32) / 255.
                                    for gray in (reference, candidate))
                cached_lpips[frame] = metrics(ref_rgb, img_rgb)["lpips_squeeze"]
            row["lpips_squeeze"] = cached_lpips[frame]
        rows.append(row)

    scores = list(cached_lpips.values())
    return {"pooled_attribution": pooled_attribution(rows, "region_pixel_count_and_sse"),
            "same_sampling_pooled_attribution": pooled_attribution(rows, "same_sampling_region_pixel_count_and_sse"),
            "lpips_mean": float(np.mean(scores)), "lpips_max": max(scores), "frames": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--captures", required=True, type=Path)
    parser.add_argument("--torch-hub", required=True, type=Path,
                        help="Torch Hub directory containing the official SqueezeNet checkpoint")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    import lpips
    import torch

    backbone = args.torch_hub / "checkpoints" / BACKBONE
    backbone_digest = sha256(backbone)
    if backbone_digest != BACKBONE_SHA256:
        parser.error("SqueezeNet checkpoint does not match the pinned digest")
    torch.hub.set_dir(str(args.torch_hub.resolve()))
    metrics = ImageMetrics()
    weights = Path(lpips.__file__).parent / "weights" / "v0.1" / "squeeze.pth"
    benchmark = json.loads(args.benchmark.read_bytes())
    results = {}
    for name, scene in benchmark["scenes"].items():
        runs = {key: row["quality_sequence"] for key, row in scene["views"].items()}
        source = runs["source"]
        reference_media = source["reference_sequence"]
        path = args.captures / name / Path(reference_media["path"]).name
        refs = decode(path, reference_media)
        source_sha = hashlib.sha256(b"".join(frame.tobytes() for frame in refs)).hexdigest()
        if source_sha != source["reference_rgb_sha256"] or len(refs) != benchmark["frames"]:
            raise ValueError(f"Decoded reference does not match the past run in {name}")
        source_media = source["candidate_sequence"]
        source_frames = decode(args.captures / name / Path(source_media["path"]).name, source_media)
        cache = {}
        policies = {}
        for policy, run in runs.items():
            if (run["reference_rgb_sha256"] != source_sha or
                    run["reference_sequence"]["sha256"] != reference_media["sha256"]):
                raise ValueError(f"The prior arms do not share the decoded reference in {name}")
            media = run["candidate_sequence"]
            images = source_frames if policy == "source" else decode(
                args.captures / name / Path(media["path"]).name, media)
            scores = evaluate(refs, source_frames, images, run["per_frame_metrics"], metrics,
                              cache.setdefault(media["sha256"], {}))
            policies[policy] = {"capture_sha256": media["sha256"], **scores}
            print(name, policy, f"LPIPS {scores['lpips_mean']:.8g}", flush=True)
        results[name] = {"source_faces": scene["high_faces"], "reference_sha256": reference_media["sha256"],
                         "reference_gray_sha256": source_sha, "policies": policies}

    paired = {}
    rng = np.random.default_rng(20261124)
    resamples = rng.integers(len(results), size=(20000, len(results)))
    for policy in ("instance-area", "instance-matched"):
        delta = {scene: row["policies"][policy]["lpips_mean"] - row["policies"]["group-area"]["lpips_mean"]
                 for scene, row in results.items()}
        values = np.array(list(delta.values()))
        paired[policy] = {"scene_deltas": delta, "mean": float(values.mean()),
                          "scene_bootstrap_ci95": np.quantile(values[resamples].mean(axis=1),
                                                              (0.025, 0.975)).tolist()}
    result = {"benchmark_sha256": sha256(args.benchmark), "script_sha256": sha256(Path(__file__)),
              "perceptual_module_sha256": sha256(Path(__file__).with_name("perceptual.py")),
              "resolution": benchmark["resolution"], "render_adapter": benchmark["adapter"],
              "decoder": "OpenCV FFmpeg, verified byte hash and original per-frame PSNR and XOR",
              "package_versions": {**metrics.settings["packages"],
                                   "numpy": np.__version__, "opencv-python": cv2.__version__},
              "band_radius_chebyshev_pixels": BAND_RADIUS,
              "lpips_frame_indices": list(range(0, benchmark["frames"], STRIDE)),
              "lpips_backbone_sha256": backbone_digest, "lpips_calibration_sha256": sha256(weights),
              "scenes": results, "scene_paired_lpips_minus_group_area": paired}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n",
                        encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
