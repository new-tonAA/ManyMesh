#!/usr/bin/env python3
"""Screen contour-risk cut budget matching on the repository's development meshes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path


FACE_RE = re.compile(r"loaded: [\d,]+ vertices, ([\d,]+) triangles")
UNIFORM_RE = re.compile(r"uniform cut ([\d.]+): ([\d,]+) triangles")
CONTOUR_RE = re.compile(
    r"contour cut ratio ([\d.]+), k ([\d.]+), margin ([\d.]+) deg: "
    r"([\d,]+) vs uniform ([\d,]+) triangles \(delta ([+-]\d+)\)"
)


def number(value: str) -> int:
    return int(value.replace(",", ""))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ply_face_count(path: Path) -> int | None:
    face_count = None
    with path.open("rb") as stream:
        while True:
            line = stream.readline()
            if not line:
                return None
            if line.startswith(b"element face "):
                try:
                    face_count = int(line.split()[2])
                except (ValueError, IndexError):
                    return None
            if line.strip() == b"end_header":
                return face_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--assets", type=Path, default=Path("assets/models"))
    parser.add_argument("--out", type=Path, default=Path("tmp/contour-budget-screen"))
    parser.add_argument("--ratios", default="0.3,0.5,0.7")
    parser.add_argument("--interior", default="3,4,5")
    parser.add_argument("--margin", type=float, default=5.0)
    args = parser.parse_args()

    args.exe = args.exe.resolve()
    args.assets = args.assets.resolve()
    args.out = args.out.resolve()
    ratios = [float(value) for value in args.ratios.split(",")]
    args.out.mkdir(parents=True, exist_ok=True)
    records = []
    meshes = sorted(args.assets.glob("*/*.obj"))
    for mesh in meshes:
        asset = mesh.parent.name
        output = args.out / asset
        command = [
            str(args.exe), str(mesh), "--mode", "dag", "--out", str(output),
            "--target-ratio-cut", args.ratios, "--contour-ratio-cut", args.ratios,
            "--contour-interior", args.interior, "--contour-margin", str(args.margin),
            "--write-dag", "0", "--dump-format", "ply",
        ]
        start = time.perf_counter()
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        elapsed = time.perf_counter() - start
        stdout = result.stdout
        loaded = FACE_RE.search(stdout)
        candidates = []
        for match in CONTOUR_RE.finditer(stdout):
            ratio = float(match.group(1))
            multiplier = float(match.group(2))
            geometry_path = output / (
                f"selected_contour_r{ratio:g}_k{multiplier:g}_m{args.margin:g}.ply"
            )
            candidates.append({
                "ratio": ratio,
                "interiorMultiplier": multiplier,
                "triangles": number(match.group(4)),
                "uniformTriangles": number(match.group(5)),
                "triangleDelta": int(match.group(6)),
                "geometrySha256": sha256(geometry_path) if geometry_path.exists() else None,
                "plyHeaderTriangles": ply_face_count(geometry_path) if geometry_path.exists() else None,
            })
        uniform_cuts = [
            {
                "ratio": float(match.group(1)),
                "triangles": number(match.group(2)),
                "geometrySha256": sha256(
                    output / f"selected_ratio_{float(match.group(1)):g}.ply"
                ) if (output / f"selected_ratio_{float(match.group(1)):g}.ply").exists() else None,
            }
            for match in UNIFORM_RE.finditer(stdout)
        ]
        uniform_hashes = {cut["ratio"]: cut["geometrySha256"] for cut in uniform_cuts}
        for candidate in candidates:
            candidate["equalsUniformGeometry"] = (
                candidate["geometrySha256"] == uniform_hashes.get(candidate["ratio"])
            )
        geometry_identical_by_budget = {}
        for ratio in ratios:
            hashes = {
                candidate["geometrySha256"] for candidate in candidates
                if candidate["ratio"] == ratio
            }
            geometry_identical_by_budget[str(ratio)] = bool(hashes) and len(hashes) == 1
        records.append({
            "asset": asset,
            "mesh": str(mesh.relative_to(args.assets.parent)),
            "sourceTriangles": number(loaded.group(1)) if loaded else None,
            "assetSha256": sha256(mesh),
            "uniformCuts": uniform_cuts,
            "candidateCuts": candidates,
            "candidateGeometryFilesIdenticalByBudget": geometry_identical_by_budget,
            "returnCode": result.returncode,
            "elapsedSeconds": round(elapsed, 4),
            "stdout": stdout if result.returncode else None,
            "stderr": result.stderr[-4000:] or None,
        })
        print(
            f"{asset}: rc={result.returncode} source={records[-1]['sourceTriangles']} "
            f"uniform={[(c['ratio'],c['triangles']) for c in uniform_cuts]} "
            f"deltas={[(c['ratio'],c['interiorMultiplier'],c['triangleDelta']) for c in candidates]} "
            f"elapsed={elapsed:.2f}s",
            flush=True,
        )

    candidate_cuts = [candidate for record in records for candidate in record["candidateCuts"]]
    payload = {
        "schema": 2,
        "purpose": "development-only contour selector budget-match feasibility screen",
        "ratios": ratios,
        "interiorMultipliers": args.interior,
        "marginDegrees": args.margin,
        "executable": str(args.exe),
        "executableSha256": sha256(args.exe),
        "benchmarkScriptSha256": sha256(Path(__file__).resolve()),
        "sourceRevision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "mmgeoSourceSha256": sha256(Path("tools/mmgeo/src/main.cpp").resolve()),
        "assetsRoot": str(args.assets),
        "assetsAreHeldOut": False,
        "imageQualityEvaluated": False,
        "candidatePlyCount": len(candidate_cuts),
        "candidatePlyHeaderMismatches": sum(
            candidate["plyHeaderTriangles"] != candidate["triangles"]
            for candidate in candidate_cuts
        ),
        "records": records,
    }
    result_path = args.out / "budget_screen.json"
    result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {result_path}")
    return 1 if (
        any(record["returnCode"] != 0 for record in records) or
        payload["candidatePlyHeaderMismatches"] != 0 or
        payload["candidatePlyCount"] != len(records) * len(ratios) * len(args.interior.split(","))
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
