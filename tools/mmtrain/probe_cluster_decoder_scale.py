"""Validation-only render-space scale probe for the frozen rank-8 decoder.

This is a per-asset oracle diagnostic, not a learned scale predictor or a
deployable method. It tests whether shrinking the existing residual direction
can improve rendered quality. The held-out test split is never opened.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from cluster_decoder import Mesh, Model, decode, write_sidecar
from fit_cluster_decoder import encode_pair, load_pair
from cluster_decoder_quality import render
from make_refinement_pairs import view_basis

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mmmetrics"))
from perceptual import ImageMetrics


SCALES = (0., .25, .5, .75, 1.)
METRICS = ("psnr_db", "ssim", "flip", "lpips_squeeze",
           "silhouette_xor_fraction", "coverage_mae")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def aggregate(per_view):
    mse = float(np.mean([row["mse"] for row in per_view]))
    result = {key: float(np.mean([row[key] for row in per_view]))
              for key in ("ssim", "flip", "lpips_squeeze",
                          "silhouette_xor_fraction", "coverage_mae")}
    result["mse"] = mse
    result["psnr_db"] = None if mse == 0 else float(-10*np.log10(mse))
    return result


def bootstrap(deltas):
    values = np.asarray(deltas, dtype=np.float64)
    if not len(values):
        return None
    rng = np.random.default_rng(20261122)
    samples = values[rng.integers(0, len(values), (5000, len(values)))].mean(axis=1)
    return {"assets": len(values), "mean_delta": float(values.mean()),
            "bootstrap_95_percent": np.quantile(samples, (.025, .975)).tolist(),
            "negative": int(np.count_nonzero(values < -1e-12)),
            "positive": int(np.count_nonzero(values > 1e-12))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--views", type=int, default=12)
    parser.add_argument("--size", type=int, default=256)
    parser.add_argument("--samples", type=int, default=2)
    parser.add_argument("--summary-json", type=Path)
    parser.add_argument("--summary-md", type=Path)
    args = parser.parse_args()
    if args.views < 2 or not 32 <= args.size <= 1024 or args.samples not in (1, 2, 4):
        parser.error("Invalid render budget")

    manifest = json.loads(args.pairs.read_text(encoding="utf-8"))
    if any(r["source"]["split"] != "validation" for r in manifest["records"]):
        raise ValueError("This probe accepts validation records only")
    model_path = args.fit / "fixed" / "model.npz"
    with np.load(model_path, allow_pickle=False) as archive:
        model = Model(archive["weights"], float(archive["max_offset"]))
    fit_report = json.loads((args.fit / "report.json").read_text(encoding="utf-8"))
    ridge = fit_report["ridge"]
    args.out.mkdir(parents=True, exist_ok=True)
    metric = ImageMetrics()
    report = {"scope": "Exploratory validation-only render-space oracle; no deployable scale predictor",
              "split": "validation", "scales": list(SCALES), "views": args.views,
              "size": args.size, "box_samples_per_pixel": args.samples**2,
              "psnr_aggregation": "-10 log10(mean per-view MSE), not mean dB",
              "model": "frozen rank-8 fixed-topology polynomial residual control",
              "metrics": metric.settings,
              "hashes": {"validation_manifest_sha256": sha256(args.pairs),
                         "model_sha256": sha256(model_path),
                         "fit_report_sha256": sha256(args.fit / "report.json"),
                         "quality_renderer_sha256": sha256(Path(__file__).with_name("cluster_decoder_quality.py")),
                         "probe_script_sha256": sha256(Path(__file__))},
              "records": []}
    for record in manifest["records"]:
        source = record["source"]
        row = {"file_id": source["file_id"], "input_sha256": source["sha256"],
               "preparation_status": record["status"]}
        if record["status"] != "prepared":
            row["reason"] = record.get("reason")
            report["records"].append(row)
            continue
        pair = load_pair(args.pairs.parent, record)
        mesh = Mesh(pair["positions"], pair["triangles"], pair["face_clusters"])
        latent, refine, diagnostics = encode_pair(pair, model, ridge, 0.)
        if len(refine):
            raise ValueError("Fixed-topology probe unexpectedly selected refinement faces")
        row.update({"triangles": len(mesh.triangles), "encode_diagnostics": diagnostics,
                    "scales": {}, "zero_scale_is_identity": None})
        for scale in SCALES:
            scale_key = f"{scale:g}"
            candidate_latent = latent * np.float32(scale)
            sidecar = args.out / f"{source['file_id']}-scale-{scale:g}.sidecar"
            write_sidecar(sidecar, mesh, model, candidate_latent)
            try:
                candidate, decode_stats = decode(mesh, model, sidecar, len(mesh.triangles))
                if len(candidate.triangles) != len(mesh.triangles):
                    raise ValueError("Fixed-topology decoder changed triangle count")
            except ValueError as error:
                row["scales"][scale_key] = {"status": "rejected", "reason": str(error),
                                             "sidecar_bytes": sidecar.stat().st_size}
                continue
            if scale == 0.:
                row["zero_scale_is_identity"] = bool(
                    np.array_equal(candidate.positions, mesh.positions)
                    and np.array_equal(candidate.triangles, mesh.triangles))
            per_view = []
            for view in range(args.views):
                basis = view_basis(view, args.views)
                reference, ref_coverage = render(pair["source_positions"],
                                                 pair["source_triangles"], basis,
                                                 args.size, args.samples)
                image, coverage = render(candidate.positions, candidate.triangles,
                                         basis, args.size, args.samples)
                union = (ref_coverage > 0) | (coverage > 0)
                values = metric(reference / 255., image / 255., union)
                values["silhouette_xor_fraction"] = float(np.mean(
                    (ref_coverage > 0) != (coverage > 0)))
                values["coverage_mae"] = float(np.mean(np.abs(ref_coverage-coverage)))
                per_view.append(values)
            row["scales"][scale_key] = {"status": "decoded", "triangles": len(candidate.triangles),
                                          "sidecar_bytes": sidecar.stat().st_size,
                                          "decode_seconds": decode_stats["decode_seconds"],
                                          "per_view": per_view, "mean": aggregate(per_view)}
        report["records"].append(row)
        print(f"validation {source['file_id']}: " + ", ".join(
            f"{scale:g}={row['scales'].get(f'{scale:g}', {}).get('status', 'missing')}"
            for scale in SCALES), flush=True)
        (args.out / "report.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")

    report["comparisons"] = {}
    for scale in SCALES[1:]:
        name = f"{scale:g}"
        pairs = [row for row in report["records"]
                 if row.get("scales", {}).get("0", {}).get("status") == "decoded"
                 and row.get("scales", {}).get(name, {}).get("status") == "decoded"]
        comparison = {"paired_assets": len(pairs), "metrics": {}}
        for key in METRICS:
            deltas = [row["scales"][name]["mean"][key] - row["scales"]["0"]["mean"][key]
                      for row in pairs]
            comparison["metrics"][key] = bootstrap(deltas)
        report["comparisons"][name+"_vs_zero"] = comparison
    successful = [row for row in report["records"]
                  if row.get("scales", {}).get("0", {}).get("status") == "decoded"]
    report["validation_oracle"] = {
        "assets_with_zero_scale": len(successful),
        "per_asset_best_scale_by_psnr": {
            row["file_id"]: min((float(scale) for scale, result in row["scales"].items()
                                 if result["status"] == "decoded"),
                                key=lambda scale: row["scales"][f"{scale:g}"]["mean"]["mse"])
            for row in successful},
        "warning": "Per-asset scale selection uses the same validation renders being scored; it is an oracle, not a generalization estimate."}
    out_path = args.out / "report.json"
    out_path.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    report["hashes"]["full_report_sha256"] = sha256(out_path)
    summary = {"scope": report["scope"], "split": "validation",
               "configuration": {key: report[key] for key in (
                   "scales", "views", "size", "box_samples_per_pixel", "model", "metrics")},
               "hashes": report["hashes"],
               "assets": [], "comparisons": report["comparisons"],
               "validation_oracle": report["validation_oracle"],
               "decode_failures": []}
    for row in report["records"]:
        asset = {"file_id": row["file_id"], "preparation_status": row["preparation_status"],
                 "input_sha256": row["input_sha256"],
                 "zero_scale_is_identity": row.get("zero_scale_is_identity"), "scales": {}}
        if row["preparation_status"] == "prepared":
            for key, result in row["scales"].items():
                if result["status"] == "decoded":
                    asset["scales"][key] = {"status": "decoded", "triangles": result["triangles"],
                                             "sidecar_bytes": result["sidecar_bytes"],
                                             "decode_seconds": result["decode_seconds"],
                                             "mean": result["mean"]}
                else:
                    asset["scales"][key] = {"status": "rejected", "reason": result["reason"],
                                             "sidecar_bytes": result["sidecar_bytes"]}
                    summary["decode_failures"].append({"file_id": row["file_id"], "scale": key,
                                                        "reason": result["reason"]})
        elif row.get("reason"):
            asset["reason"] = row["reason"]
        summary["assets"].append(asset)
    if args.summary_json:
        args.summary_json.write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    if args.summary_md:
        lines = ["# Cluster Decoder Latent-Scale Probe", "",
                 "Date: 2026-11-22. Validation-only exploratory diagnostic of the frozen rank-8 fixed-topology polynomial residual control. The latent scale is an oracle variable; no scale predictor is proposed.", "",
                 "## Protocol", "",
                 f"- {args.views} orthographic views per prepared asset, {args.size} x {args.size}, {args.samples**2} raster samples per pixel; grayscale flat shading.",
                 "- Metrics: PSNR, canonical SSIM, LDR-FLIP, SqueezeNet LPIPS, silhouette XOR, and coverage MAE. Confidence intervals resample assets, not views.",
                 "- Fixed mesh and face count across scales. Alpha 0 is the exact base mesh identity control. Test split was not loaded.",
                 "- Scale selection per asset uses the same validation renders being scored and is reported only as an oracle upper bound.",
                 "", "## Per-asset results", "",
                 "| Asset | Zero identity | Alpha 0 PSNR | Best alpha (oracle) | Best PSNR | Nonzero scales decoded |", "|---:|:---:|---:|---:|---:|---:|"]
        for asset in summary["assets"]:
            zero, best_alpha = asset["scales"].get("0"), report["validation_oracle"]["per_asset_best_scale_by_psnr"].get(asset["file_id"])
            best = asset["scales"].get(f"{best_alpha:g}") if best_alpha is not None else None
            count = sum(v["status"] == "decoded" for k, v in asset["scales"].items() if k != "0")
            lines.append(f"| {asset['file_id']} | {asset.get('zero_scale_is_identity')} | "
                         f"{zero['mean']['psnr_db']:.3f} dB | "
                         f"{best_alpha:g}" if best_alpha is not None else f"| {asset['file_id']} | {asset.get('zero_scale_is_identity')} | — | —")
            if best_alpha is not None:
                lines[-1] += f" | {best['mean']['psnr_db']:.3f} dB | {count}/4 |"
            else:
                lines[-1] += " | — | — |"
        lines += ["", "## Paired changes from alpha 0", "",
                  "Negative FLIP/LPIPS and positive PSNR/SSIM are favorable. The 95% intervals are asset bootstrap intervals.", "",
                  "| Alpha | Paired assets | PSNR dB | SSIM | FLIP | LPIPS | Silhouette XOR | Coverage MAE |",
                  "|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for scale in SCALES[1:]:
            result = summary["comparisons"][f"{scale:g}_vs_zero"]
            cells = []
            for key in METRICS:
                stat = result["metrics"][key]
                if stat is None:
                    cells.append("n/a")
                else:
                    cells.append(f"{stat['mean_delta']:+.5f} [{stat['bootstrap_95_percent'][0]:+.5f}, {stat['bootstrap_95_percent'][1]:+.5f}]")
            lines.append(f"| {scale:g} | {result['paired_assets']} | " + " | ".join(cells) + " |")
        lines += ["", "## Result and limits", "",
                  "The scale sweep is a diagnostic, not an independent model comparison. Decoder rejects remain counted; the 100894 asset rejected every nonzero scale under the local topology/offset checks. Per-asset oracle gains cannot support a runtime policy or a generalization claim. Even if one global scale helps this validation split, it must be frozen and evaluated once on an untouched, licensed confirmation set before further investment.", "",
                  "PSNR, SSIM, FLIP, and LPIPS are complementary image metrics, not a universal perceptual-quality score. This geometry-only grayscale probe does not assess materials, animation, temporal stability, runtime rendering, mobile hardware, or user preference.", "",
                  "## Reproduction", "",
                  "The validation manifest and frozen rank-8 model must already exist at the paths below; the manifest and model hashes are recorded in the compact receipt. The command opens validation rows only.", "",
                  "```powershell",
                  "$env:PYTHONPATH = (Resolve-Path 'out/image-quality-deps').Path + ';' + (Resolve-Path 'out/geometry-refinement-pilot/deps').Path",
                  "$env:TORCH_HOME = (Join-Path (Get-Location) 'out/quality-torch')",
                  "$env:OPENBLAS_NUM_THREADS = '1'",
                  "python tools/mmtrain/probe_cluster_decoder_scale.py `",
                  "  --pairs out/cluster-decoder-pairs/validation/manifest.json `",
                  "  --fit out/cluster-decoder-fit/rank8 `",
                  "  --out out/cluster-decoder-scale-oracle/rank8 `",
                  "  --views 12 --size 256 --samples 2 `",
                  "  --summary-json tools/mmtrain/cluster_decoder_scale_oracle_20261122.json `",
                  "  --summary-md tools/mmtrain/CLUSTER_DECODER_SCALE_PROBE_20261122.md",
                  "```", "",
                  "Full per-view data are in the ignored `out/cluster-decoder-scale-oracle/rank8/report.json`. The compact [machine-readable summary](cluster_decoder_scale_oracle_20261122.json) records model, input, and renderer hashes."]
        args.summary_md.write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
