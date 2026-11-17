"""Finite coverage-image/integral cost gate for an established proxy estimator.

This is not a renderer, a timing benchmark, or a novel estimator. The measured
distribution is uniform over the frozen orthographic sample grid and orbit.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

import depth_candidate_pilot as raster


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gain_limit(variance, mismatch):
    if variance == 0 or mismatch >= variance:
        return 0.0
    root = math.sqrt(mismatch / variance)
    return (1 - root) / (1 + root)


def moments(counts):
    """Counts are [fine=0/coarse=0, 01, 10, 11]; occupancy or visibility works."""
    if len(counts) != 4 or any(int(n) != n or n < 0 for n in counts):
        raise ValueError("four nonnegative integer joint counts required")
    total = sum(counts)
    if total <= 0:
        raise ValueError("nonempty finite ray population required")
    mean = (counts[2] + counts[3]) / total
    variance = mean * (1 - mean)
    mismatch = (counts[1] + counts[2]) / total
    # No strict gain is possible if q >= V, or if direct fine variance is zero.
    return dict(samples=int(total), jointCounts=list(map(int, counts)),
                fineOccupancyMean=mean, fineVariance=variance,
                disagreement=mismatch,
                strictGainRequiresCostRatioBelow=gain_limit(variance, mismatch))


def optimum(variance, mismatch, cost_ratio):
    """Oracle constant correction probability, fine cost=1 and proxy cost=r.

    Y=G+B/p*(F-G); variance=V+q*(1/p-1), cost=r+p. Costs
    are additive expected query costs, with no build/probe/selection overhead.
    """
    if not all(math.isfinite(x) for x in (variance, mismatch, cost_ratio)):
        raise ValueError("finite parameters required")
    if variance < 0 or not 0 <= mismatch <= 1 or cost_ratio <= 0:
        raise ValueError("invalid variance, disagreement, or positive query cost")
    if mismatch == 0:
        probability = 0.0  # Exact only on the fully enumerated finite population.
        corrected_variance = variance
    else:
        probability = (min(1.0, math.sqrt(cost_ratio * mismatch / (variance - mismatch)))
                       if variance > mismatch else 1.0)
        corrected_variance = variance + mismatch * (1 / probability - 1)
    normalized_cost = cost_ratio + probability
    relative = (normalized_cost * corrected_variance / variance if variance else None)
    return dict(proxyToFineCostRatio=cost_ratio, oracleCorrectionProbability=probability,
                correctedVariance=corrected_variance, normalizedCost=normalized_cost,
                relativeCostVariance=relative,
                withDirectFineFallback=min(1.0, relative) if relative is not None else None)


def analyze(counts):
    result = moments(counts)
    result["hypotheticalCosts"] = [optimum(result["fineVariance"], result["disagreement"], r)
                                   for r in (.05, .1, .25, .5, .75, 1.0)]
    return result


def image_gate(numerator, denominator, samples, mismatches, constant_pixel_mismatches):
    variance = numerator / denominator
    disagreement = mismatches / samples
    return dict(finePixelVarianceNumerator=int(numerator),
                finePixelVarianceDenominator=int(denominator),
                meanWithinPixelFineVariance=variance, disagreement=disagreement,
                mismatchesInsideConstantFinePixels=int(constant_pixel_mismatches),
                strictGainRequiresCostRatioBelow=gain_limit(variance, disagreement),
                hypotheticalCosts=[optimum(variance, disagreement, r)
                                   for r in (.05, .1, .25, .5, .75, 1.0)])


def coverage_image_gate(fine, coarse, scale):
    """Mean per-pixel variance, not variance of the image-wide mean occupancy.

    Each pixel integrates a uniform finite scale*scale subpixel distribution.
    Different pixels have different fixed means; between-pixel variance is excluded.
    """
    if (fine.ndim != 2 or coarse.shape != fine.shape or scale < 1 or int(scale) != scale
            or any(d % scale for d in fine.shape)):
        raise ValueError("matching 2D arrays of complete pixels required")
    if not (np.isin(fine, (0, 1)).all() and np.isin(coarse, (0, 1)).all()):
        raise ValueError("binary coverage required")
    height, width = fine.shape
    hits = fine.reshape(height // scale, scale, width // scale, scale).sum(axis=(1, 3))
    per_pixel = scale * scale
    numerator = int((hits * (per_pixel - hits)).sum())
    denominator = per_pixel * per_pixel * hits.size
    constant = np.repeat(np.repeat((hits == 0) | (hits == per_pixel), scale, axis=0),
                         scale, axis=1)
    difference = fine != coarse
    return image_gate(numerator, denominator, fine.size, int(difference.sum()),
                      int(np.count_nonzero(difference & constant)))


def require_hash(path, expected):
    actual = digest(path)
    if actual != expected:
        raise ValueError(f"hash mismatch: {path}")
    return dict(path=str(path), sha256=actual)


def run_asset(root, asset):
    directory = root / "out/progressive-baseline" / asset
    capture = root / "out/filter-real-candidates" / (asset + ".json")
    manifest_path = directory / "manifest.json"
    evaluation_path = directory / "evaluation.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    require_hash(capture, manifest["captureSha256"])
    require_hash(capture, evaluation["captureSha256"])
    require_hash(manifest_path, evaluation["manifestSha256"])
    require_hash(Path(raster.__file__), evaluation["rasterSha256"])
    require_hash(Path(__file__).with_name("evaluate_progressive_baseline.py"),
                 evaluation["scriptSha256"])
    positions, faces, _ = raster.load_capture(capture)
    meshes = {}
    rows = {}
    for ratio, artifact in manifest["artifacts"].items():
        # Archived manifests use Windows separators, also resolve on other OSes.
        path = root / Path(artifact["path"].replace("\\", "/"))
        require_hash(path, artifact["sha256"])
        with np.load(path, allow_pickle=False) as data:
            ps, fs = data["positions"], data["triangles"]
        if len(fs) != artifact["triangles"]:
            raise ValueError("artifact face count mismatch")
        meshes[ratio] = ps, fs
        rows[ratio] = dict(actualTriangleRatio=len(fs) / len(faces),
                           artifact=dict(path=str(path), sha256=digest(path)), views=[])
    for index, angle in enumerate(np.linspace(0, 2 * np.pi, 12, endpoint=False)):
        transform = raster.camera(positions, float(angle), 128)
        raw, _ = raster.raster(raster.project(positions, transform), faces,
                               np.ones(len(faces), bool), (0, 0, 128, 128), 3)
        fine = raw[..., 0].astype(np.int64)
        for ratio, (ps, fs) in meshes.items():
            coarse, _ = raster.raster(raster.project(ps, transform), fs,
                                      np.ones(len(fs), bool), (0, 0, 128, 128), 3)
            coarse_cover = coarse[..., 0].astype(np.int64)
            counts = np.bincount((2 * fine + coarse_cover).ravel(),
                                 minlength=4).tolist()
            previous = evaluation["levels"][ratio]["views"][index]
            if abs(previous["angle"] - float(angle)) > 1e-14:
                raise ValueError("archived view angle differs")
            if counts[1] + counts[2] != previous["rawCoverageChanged"]:
                raise ValueError("fresh raster disagrees with archived coverage count")
            rows[ratio]["views"].append(dict(index=index, angle=float(angle), **analyze(counts),
                boxFilteredCoverageImage=coverage_image_gate(fine, coarse_cover, 3)))
        print(asset, "view", index, "fresh coverage counts verified", flush=True)
    for row in rows.values():
        counts = [sum(view["jointCounts"][i] for view in row["views"]) for i in range(4)]
        row["pooledOrbit"] = analyze(counts)
        limits = [view["strictGainRequiresCostRatioBelow"] for view in row["views"]]
        row["perViewCostLimitRange"] = [min(limits), max(limits)]
        images = [view["boxFilteredCoverageImage"] for view in row["views"]]
        row["orbitCoverageImage"] = image_gate(
            sum(im["finePixelVarianceNumerator"] for im in images),
            sum(im["finePixelVarianceDenominator"] for im in images),
            sum(counts), counts[1] + counts[2],
            sum(im["mismatchesInsideConstantFinePixels"] for im in images))
        limits = [im["strictGainRequiresCostRatioBelow"] for im in images]
        row["perViewImageCostLimitRange"] = [min(limits), max(limits)]
    return dict(asset=asset, sourceTriangles=len(faces),
                capture=dict(path=str(capture), sha256=digest(capture)),
                manifest=dict(path=str(manifest_path), sha256=digest(manifest_path)),
                archivedEvaluation=dict(path=str(evaluation_path), sha256=digest(evaluation_path)),
                levels=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assets = [run_asset(args.root, name) for name in ("torus", "monkey", "pirate")]
    result = dict(schema=2,
        scope="finite orthographic box-filtered binary coverage image and separate area integral",
        estimator="Y=G+Bernoulli(p)/p*(F-G), constant p, direct fine fallback allowed",
        costAssumptions="r=c_proxy/E[c_fine]; additive query cost; no overhead; no hardware timing",
        target="fine coverage per pixel; independently uniform over its 3x3 subpixel atoms",
        grid=dict(pixels=128, samplesPerAxisPerPixel=3, views=12, elevationParameter=.37),
        caveats=["three reused development assets; no independent generalization set",
                 "oracle p from full enumeration; no online probe or build cost charged",
                 "triangle ratio is not ray query cost ratio",
                 "no BSDF, illumination, finite shadow segments, self-shadowing, or light transport",
                 "coverage-image MSE only; no inference of lighting MSE, native speed, or novelty"],
        scriptSha256=digest(__file__), rasterSha256=digest(raster.__file__), assets=assets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("wrote", args.output, flush=True)


if __name__ == "__main__":
    main()
