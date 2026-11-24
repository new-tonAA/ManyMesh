"""Pre-score ManyMesh/QEM/meshoptimizer eligibility for frozen Poly Haven assets."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PIN_HEAD = "2d417cacdeb545a13e6bfb7192310191e60670d6"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def run(command, env, timeout=900):
    start = time.perf_counter()
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                            text=True, timeout=timeout)
    return result, (time.perf_counter() - start) * 1000


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology-report", type=Path, required=True)
    parser.add_argument("--mmgeo", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--asset", help="Run or resume one selected asset")
    args = parser.parse_args()

    topology = json.loads(args.topology_report.read_text(encoding="utf-8"))
    if topology.get("quality_scored") or topology.get("image_or_render_data_used"):
        raise ValueError("The source screen is not a clean pre-score receipt")
    pin = json.loads((ROOT / "out/cmake-cut-audit/source-pin.json").read_text(encoding="utf-8"))
    if pin.get("head") != EXPECTED_PIN_HEAD:
        raise ValueError("The mmgeo source pin differs from the reviewed research build")

    binary = args.mmgeo.resolve()
    deps = (ROOT / "out/geometry-refinement-pilot/deps").resolve()
    if not (deps / "fast_simplification").is_dir():
        raise FileNotFoundError("Pinned geometry-control Python dependencies are unavailable")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(deps) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    candidates = [row for row in topology["assets"]
                  if (row.get("extraction") or {}).get("topology_status") == "pass"]
    if args.asset:
        candidates = [row for row in candidates if row["asset"] == args.asset]
    if not candidates:
        parser.error("No source-topology-pass candidate selected")

    report = {
        "schema": 1,
        "source_screen_sha256": digest(args.topology_report),
        "source_screen_quality_scored": False,
        "source_revision_pin": pin,
        "mmgeo_sha256": digest(binary),
        "script_sha256": digest(Path(__file__)),
        "preflight_script_sha256": digest(ROOT / "tools/mmtrain/preflight_appearance_meshes.py"),
        "adapter_script_sha256": digest(ROOT / "tools/mmtrain/adapt_position_ply.py"),
        "python_version": platform.python_version(),
        "protocol": {
            "nominal_retention": 0.5,
            "allowed_manymesh_retention": [0.49, 0.51],
            "cluster_triangles": 128,
            "dag_group": 4,
            "levels": 8,
            "quality_gate": 1,
            "controls": ["fast-simplification QEM preserve_border", "meshoptimizer LockBorder"],
            "eligibility": "all meshes must match the ManyMesh face count and preserve source directed boundary under one float32 ULP",
            "image_or_render_scoring": False,
        },
        "assets": [],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for index, source_row in enumerate(candidates, 1):
        slug = source_row["asset"]
        source = ROOT / source_row["local_asset_directory"] / "geometry.obj"
        source_sha = source_row["extraction"]["obj_sha256"]
        if digest(source) != source_sha:
            raise ValueError(f"Source OBJ hash mismatch: {slug}")
        run_dir = args.out_dir / slug
        run_dir.mkdir(parents=True, exist_ok=True)
        output = run_dir / "selected_ratio_0.5.ply"
        row = {"asset": slug, "candidate_class": source_row["candidate_class"],
               "source_sha256": source_sha,
               "source_faces": source_row["extraction"]["triangles"],
               "runs": []}
        try:
            if not output.is_file():
                command = [str(binary), str(source), "--out", str(run_dir),
                           "--mode", "dag", "--levels", "8", "--ratio", "0.5",
                           "--target-ratio", "0.5", "--target-ratio-cut", "0.5",
                           "--quality-gate", "1", "--cluster-tris", "128",
                           "--dag-group", "4", "--dump-format", "ply",
                           "--visibility", "0", "--write-dag", "0"]
                result, elapsed = run(command, env)
                (run_dir / "mmgeo.log").write_text(result.stdout + result.stderr,
                                                    encoding="utf-8")
                row["runs"].append({"stage": "mmgeo_build", "command": command,
                                    "returncode": result.returncode, "elapsed_ms": elapsed})
                if result.returncode != 0 or not output.is_file():
                    raise RuntimeError("mmgeo failed to produce the requested cut")

            adapter = run_dir / "adapter.json"
            adapted = run_dir / "adapted_0.5.ply"
            if not adapted.is_file():
                command = [sys.executable, "tools/mmtrain/adapt_position_ply.py",
                           "--input", str(output), "--output", str(adapted),
                           "--receipt", str(adapter)]
                result, elapsed = run(command, env)
                row["runs"].append({"stage": "adapt_ply", "command": command,
                                    "returncode": result.returncode, "elapsed_ms": elapsed,
                                    "stdout": result.stdout.strip(),
                                    "stderr": result.stderr[-2000:]})
                if result.returncode != 0:
                    raise RuntimeError("PLY adapter failed")

            eligibility_path = run_dir / "eligibility.json"
            if not eligibility_path.is_file():
                command = [sys.executable, "tools/mmtrain/preflight_appearance_meshes.py",
                           "--source", str(source), "--source-sha256", source_sha,
                           "--candidate", str(adapted), "--target-ratio", "0.5",
                           "--mmgeo", str(binary), "--output", str(eligibility_path),
                           "--export-obj-dir", str(run_dir / "controls")]
                result, elapsed = run(command, env)
                row["runs"].append({"stage": "matched_face_preflight", "command": command,
                                    "returncode": result.returncode, "elapsed_ms": elapsed,
                                    "stdout": result.stdout.strip(),
                                    "stderr": result.stderr[-3000:]})
                if result.returncode != 0:
                    raise RuntimeError("matched-face preflight failed")

            eligibility = json.loads(eligibility_path.read_text(encoding="utf-8"))
            row["eligibility"] = eligibility
            row["status"] = ("matched_inputs_ready" if eligibility["matched_inputs_ready"]
                             else "ineligible")
        except Exception as error:
            row["status"] = "screen_error"
            row["error"] = f"{type(error).__name__}: {error}"
        report["assets"].append(row)
        write_json(args.report, report)
        counts = (row.get("eligibility", {}).get("controls", {}))
        print(index, slug, row["status"],
              {name: info.get("eligible", False) for name, info in counts.items()},
              flush=True)

    report["complete"] = True
    write_json(args.report, report)


if __name__ == "__main__":
    main()
