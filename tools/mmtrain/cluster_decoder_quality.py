"""Multi-asset image-quality diagnostic for frozen cluster residual controls.

Orthographic, two-sided, flat-normal shading is a geometry diagnostic, not a
Filament/PBR or perceptual-user-study result. Test geometry is deliberately refused.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

from cluster_decoder import Mesh, Model, write_sidecar, decode
from direct_cluster_control import encode_direct, decode_direct
from fit_cluster_decoder import encode_pair, load_pair
from make_refinement_pairs import raster, view_basis

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mmmetrics"))
from perceptual import ImageMetrics


def render(positions, triangles, basis, size, samples):
    points = positions[triangles]
    normal = np.cross(points[:, 1]-points[:, 0], points[:, 2]-points[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-20)
    light = np.array((.36, .80, .48))
    light /= np.linalg.norm(light)
    brightness = .15 + .85*np.maximum(0, normal @ light)
    vertices = points.reshape(-1, 3).astype(np.float32) @ basis
    resolution = size*samples
    vertices[:, :2] = (vertices[:, :2]*.45+.5)*resolution
    faces = np.arange(len(vertices), dtype=np.int32).reshape(-1, 3)
    color, depth = raster(vertices, faces, np.repeat(brightness, 3).astype(np.float32), resolution)
    coverage = np.isfinite(depth)
    color[~coverage] = .02
    color = color.reshape(size, samples, size, samples).mean(axis=(1, 3))
    coverage = coverage.reshape(size, samples, size, samples).mean(axis=(1, 3))
    srgb = np.where(color <= .0031308, color*12.92, 1.055*color**(1/2.4)-.055)
    rgb = np.repeat(np.clip(np.rint(srgb*255), 0, 255).astype(np.uint8)[..., None], 3, axis=2)
    return rgb, coverage


def validation_variants(pair, root, out, ridge, fraction, file_id):
    variants, statuses = {}, {}
    mesh = Mesh(pair["positions"], pair["triangles"], pair["face_clusters"])
    for mode in ("fixed", "refine"):
        with np.load(root / mode / "model.npz", allow_pickle=False) as archive:
            model = Model(archive["weights"], float(archive["max_offset"]))
        latent, refine, _ = encode_pair(pair, model, ridge, fraction if mode == "refine" else 0)
        path = out / f"{file_id}-{mode}.sidecar"
        write_sidecar(path, mesh, model, latent, refine)
        try:
            candidate, _ = decode(mesh, model, path, len(mesh.triangles)+2*len(refine))
            variants[mode] = (candidate.positions, candidate.triangles)
            statuses[mode] = "decoded"
        except ValueError as error:
            statuses[mode] = str(error)
        free = len(pair["free_vertices"])
        ids = np.concatenate((np.arange(free), free+refine))
        path = out / f"{file_id}-{mode}-direct.sidecar"
        encode_direct(path, mesh, pair["targets"][ids]-pair["queries"][ids], refine)
        try:
            candidate, _ = decode_direct(mesh, path, len(mesh.triangles)+2*len(refine))
            variants[mode+"_direct"] = (candidate.positions, candidate.triangles)
            statuses[mode+"_direct"] = "decoded"
        except ValueError as error:
            statuses[mode+"_direct"] = str(error)
    return variants, statuses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, action="append", required=True)
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--views", type=int, default=12)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--refinement-fraction", type=float, default=.1)
    args = parser.parse_args()
    if args.views < 2 or not 32 <= args.size <= 1024 or args.samples not in (1, 2, 4):
        parser.error("Invalid render budget")
    args.out.mkdir(parents=True, exist_ok=True)
    fit = json.loads((args.fit / "report.json").read_text())
    metric = ImageMetrics()
    report = {"scope": "Frozen-model development diagnostic; orthographic flat shading, no PBR",
              "metrics": metric.settings, "views": args.views, "size": args.size,
              "box_samples_per_pixel": args.samples**2,
              "psnr_aggregation": "-10 log10(mean per-view MSE), not mean dB",
              "encoding_refinement_fraction": args.refinement_fraction,
              "model_sha256": {m: hashlib.sha256((args.fit/m/"model.npz").read_bytes()).hexdigest()
                               for m in ("fixed", "refine")},
              "records": []}
    panels = []
    for manifest_path in args.pairs:
        manifest = json.loads(manifest_path.read_text())
        if any(r["source"]["split"] not in ("train", "validation") for r in manifest["records"]):
            raise ValueError("Test images require a separately frozen final protocol")
        for record in manifest["records"]:
            source = record["source"]
            file_id, split = source["file_id"], source["split"]
            row = {"file_id": file_id, "split": split, "input_sha256": source["sha256"],
                   "preparation_status": record["status"]}
            if record["status"] != "prepared":
                row["reason"] = record["reason"]
                report["records"].append(row)
                continue
            pair = load_pair(manifest_path.parent, record)
            variants = {"base": (pair["positions"], pair["triangles"])}
            folder = args.out / f"{split}-{file_id}"
            folder.mkdir(exist_ok=True)
            if split == "train":
                statuses = {}
                for mode in ("fixed", "refine"):
                    item = next(r for r in fit["modes"][mode]["records"] if r["file_id"] == file_id)
                    for direct in (False, True):
                        name = mode+("_direct" if direct else "")
                        state = item["direct_control"] if direct else item
                        statuses[name] = state.get("reason", state["status"])
                        if state["status"] == "decoded":
                            path = args.fit/mode/f"{file_id}{'-direct' if direct else ''}-decoded.npz"
                            with np.load(path, allow_pickle=False) as arrays:
                                variants[name] = (arrays["positions"], arrays["triangles"])
            else:
                extra, statuses = validation_variants(pair, args.fit, folder, fit["ridge"],
                                                       args.refinement_fraction, file_id)
                variants.update(extra)
            row.update({"variants": {}, "decode_status": statuses})
            for name, (_, faces) in variants.items():
                row["variants"][name] = {"triangles": len(faces), "per_view": []}
            for view in range(args.views):
                basis = view_basis(view, args.views)
                reference, coverage = render(pair["source_positions"], pair["source_triangles"],
                                              basis, args.size, args.samples)
                Image.fromarray(reference).save(folder/f"reference-v{view:02}.png")
                images = {}
                for name, (positions, faces) in variants.items():
                    image, candidate_coverage = render(positions, faces, basis, args.size, args.samples)
                    union = (coverage > 0) | (candidate_coverage > 0)
                    values = metric(reference/255., image/255., union)
                    values.update({"view": view,
                                   "silhouette_xor_pixels": int(np.count_nonzero(
                                       (coverage > 0) != (candidate_coverage > 0))),
                                   "silhouette_xor_fraction": float(np.mean(
                                       (coverage > 0) != (candidate_coverage > 0))),
                                   "coverage_mae": float(np.mean(np.abs(coverage-candidate_coverage)))})
                    row["variants"][name]["per_view"].append(values)
                    Image.fromarray(image).save(folder/f"{name}-v{view:02}.png")
                    images[name] = image
                if view == 0:
                    panel = Image.new("RGB", (args.size*4, args.size+48), "#20252b")
                    draw = ImageDraw.Draw(panel)
                    for column, name in enumerate(("reference", "base", "fixed", "refine")):
                        image = reference if name == "reference" else images.get(name)
                        draw.text((column*args.size+5, 4), f"{split} {file_id} | {name}", fill="white")
                        if image is not None:
                            panel.paste(Image.fromarray(image), (column*args.size, 38))
                        else:
                            draw.text((column*args.size+5, 60), "REJECTED", fill="orange")
                    panels.append(panel)
            for item in row["variants"].values():
                item["mean"] = {key: float(np.mean([r[key] for r in item["per_view"]]))
                                for key in ("mse", "ssim", "flip", "lpips_squeeze",
                                            "silhouette_xor_fraction", "coverage_mae")}
                mse = item["mean"]["mse"]
                item["mean"]["psnr_db"] = None if mse == 0 else float(-10*np.log10(mse))
            report["records"].append(row)
            (args.out/"report.json").write_bytes((json.dumps(report, indent=2)+"\n").encode())
            print(f"{split} {file_id}: {len(variants)} variants x {args.views} views", flush=True)
    if panels:
        sheet = Image.new("RGB", (panels[0].width, sum(p.height for p in panels)), "black")
        y = 0
        for panel in panels:
            sheet.paste(panel, (0, y))
            y += panel.height
        sheet.save(args.out/"all-assets.png")
    (args.out/"report.json").write_bytes((json.dumps(report, indent=2)+"\n").encode())


if __name__ == "__main__":
    main()
