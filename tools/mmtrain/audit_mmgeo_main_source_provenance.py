#!/usr/bin/env python3
"""Audit the mmgeo source-hash discrepancy across pinned run receipts."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
KHRONOS_RECEIPT = ROOT / "tools/mmtrain/khronos_equal_face_quality_screen_20261123.json"
POLYHAVEN_MATCHED = ROOT / "tools/mmtrain/polyhaven_matched_face_20261124.json"
POLYHAVEN_EXPANSION = ROOT / "tools/mmtrain/polyhaven_matched_face_expansion_20261124.json"
POLYHAVEN_COHORT = ROOT / "tools/mmtrain/polyhaven_quality_cohort_20261124.json"
POLYHAVEN_METRICS = ROOT / "tools/mmtrain/polyhaven_quality_metrics_20261124.json"
OUTPUT = ROOT / "tools/mmtrain/mmgeo_source_provenance_audit_20261124.json"
MAIN_PATH = "tools/mmgeo/src/main.cpp"
BUILD_DIR = ROOT / "out/cmake-cut-audit"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*args: str, cwd: Path = ROOT) -> bytes:
    return subprocess.check_output(["git", *args], cwd=cwd)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def retained_build_trace(binary_hash: str) -> dict:
    """Capture local build evidence without treating it as a clean rebuild."""
    executable = BUILD_DIR / "tools/mmgeo/Release/mmgeo.exe"
    build_log = BUILD_DIR / "out/cmake-cut-audit/msbuild.log"
    compile_tlog = BUILD_DIR / "tools/mmgeo/mmgeo.dir/Release/mmgeo.tlog/CL.command.1.tlog"
    if not (executable.is_file() and build_log.is_file() and compile_tlog.is_file()):
        return {"available": False}

    executable_hash = sha256(executable.read_bytes())
    log = build_log.read_text(encoding="utf-8", errors="replace")
    msbuild_command = None
    compile_command = None
    for line in log.splitlines():
        match = re.search(
            r'("[A-Za-z]:/[^\r\n]*?MSBuild\.exe" tools/mmgeo/mmgeo\.vcxproj[^\r\n]*)',
            line,
            re.IGNORECASE,
        )
        if match:
            msbuild_command = match.group(1)
            break
    for line in log.splitlines():
        match = re.search(
            r'([A-Za-z]:\\[^\r\n]*?CL\.exe /c [^\r\n]*?tools\\mmgeo\\src\\main\.cpp)',
            line,
            re.IGNORECASE,
        )
        if match:
            compile_command = match.group(1)
            break
    tlog = compile_tlog.read_bytes().decode("utf-16le", errors="replace")
    tlog_has_source = "TOOLS\\MMGEO\\SRC\\MAIN.CPP" in tlog.upper()
    return {
        "available": True,
        "executable": executable.relative_to(ROOT).as_posix(),
        "executable_sha256": executable_hash,
        "executable_matches_receipt": executable_hash == binary_hash,
        "msbuild_log": build_log.relative_to(ROOT).as_posix(),
        "msbuild_log_sha256": sha256(build_log.read_bytes()),
        "compile_tlog": compile_tlog.relative_to(ROOT).as_posix(),
        "compile_tlog_sha256": sha256(compile_tlog.read_bytes()),
        "tlog_names_main_cpp": tlog_has_source,
        "msbuild_invocation": msbuild_command,
        "main_cpp_compile_invocation": compile_command,
    }


def main() -> None:
    khronos = read_json(KHRONOS_RECEIPT)
    matched = read_json(POLYHAVEN_MATCHED)
    expansion = read_json(POLYHAVEN_EXPANSION)
    cohort = read_json(POLYHAVEN_COHORT)
    metrics = read_json(POLYHAVEN_METRICS)
    source_patch = khronos["mmgeo_source_patch"]
    run = khronos["run_provenance"]

    archive_path = ROOT / source_patch["archive_path"]
    archive_bytes = archive_path.read_bytes()
    if sha256(archive_bytes) != source_patch["archive_sha256"]:
        raise SystemExit("source patch archive SHA-256 mismatch")
    with zipfile.ZipFile(archive_path) as archive:
        patch_name = archive.namelist()[0]
        patch_bytes = archive.read(patch_name)
    if sha256(patch_bytes) != source_patch["patch_sha256"]:
        raise SystemExit("embedded source patch SHA-256 mismatch")

    blocks = re.split(rb"(?=^diff --git )", patch_bytes, flags=re.MULTILINE)
    main_block = next(
        (block for block in blocks if block.startswith(b"diff --git a/" + MAIN_PATH.encode() + b" ")),
        None,
    )
    if main_block is None:
        raise SystemExit("main.cpp patch section is missing")
    index = re.search(rb"^index ([0-9a-f]+)\.\.([0-9a-f]+)", main_block, re.MULTILINE)
    if index is None:
        raise SystemExit("main.cpp source blob IDs are missing from patch")
    old_blob, target_blob = (value.decode("ascii") for value in index.groups())
    parent = run["parent_revision"]
    parent_blob = git("rev-parse", f"{parent}:{MAIN_PATH}").decode().strip()
    if not parent_blob.startswith(old_blob):
        raise SystemExit("recorded parent does not match the patch base blob")

    with tempfile.TemporaryDirectory(prefix="manymesh-main-source-audit-") as directory:
        temp = Path(directory)
        source = temp / MAIN_PATH
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(git("show", f"{parent}:{MAIN_PATH}"))
        patch_file = temp / "main.cpp.diff"
        patch_file.write_bytes(main_block)
        subprocess.run(["git", "apply", "--check", str(patch_file)], cwd=temp, check=True)
        subprocess.run(["git", "apply", str(patch_file)], cwd=temp, check=True)
        reconstructed_sha256 = sha256(source.read_bytes())

    if reconstructed_sha256 != run["mmgeo_main_sha256"]:
        raise SystemExit("reconstructed main.cpp SHA-256 does not match the run receipt")

    polyhaven_build = metrics["geometry_build"]
    polyhaven_pin = polyhaven_build["source_revision_pin"]
    polyhaven_main_sha256 = polyhaven_pin["modified_source_sha256"][MAIN_PATH]

    geometry_rows = matched["rows"] + expansion["assets"]
    binary_hashes = sorted(
        {
            row.get("eligibility", {}).get("mmgeo_sha256")
            for row in geometry_rows
            if row.get("eligibility", {}).get("mmgeo_sha256")
        }
    )
    binary_hash = run["mmgeo_binary_sha256"]
    binary_hash_matches = binary_hashes == [binary_hash] == [polyhaven_build["mmgeo_sha256"]]
    if not binary_hash_matches:
        raise SystemExit("Poly Haven and Khronos binary hashes do not match")

    geometry_sources = {
        row.get("eligibility", {}).get("source_sha256")
        for row in geometry_rows
        if row.get("eligibility", {}).get("source_sha256")
    }
    cohort_sources = {
        row["source_sha256"] for row in cohort["assets"].values() if row.get("source_sha256")
    }
    cohort_sources_covered = len(geometry_sources & cohort_sources)
    if cohort_sources_covered != len(cohort_sources):
        raise SystemExit("one or more scored cohort sources are absent from the geometry receipts")

    build_trace = retained_build_trace(binary_hash)

    report = {
        "schema": 1,
        "status": "source provenance conflict: same binary hash, different main.cpp hashes",
        "khronos_binary_sha256": binary_hash,
        "polyhaven_recorded_binary_sha256": polyhaven_build["mmgeo_sha256"],
        "polyhaven_geometry_receipt_binary_sha256": binary_hashes,
        "polyhaven_geometry_receipt_rows": len(geometry_rows),
        "polyhaven_scored_assets": len(cohort_sources),
        "scored_asset_sources_found_in_geometry_receipts": cohort_sources_covered,
        "source_patch_archive": source_patch["archive_path"],
        "source_patch_archive_sha256": sha256(archive_bytes),
        "source_patch_sha256": sha256(patch_bytes),
        "source_parent_revision": parent,
        "main_cpp_patch_base_blob": parent_blob,
        "main_cpp_patch_target_blob_prefix": target_blob,
        "khronos_recorded_main_cpp_sha256": run["mmgeo_main_sha256"],
        "main_cpp_reconstructed_sha256": reconstructed_sha256,
        "polyhaven_recorded_main_cpp_sha256": polyhaven_main_sha256,
        "polyhaven_recorded_source_diff_sha256": polyhaven_pin["source_diff_sha256"],
        "polyhaven_recorded_build_environment": polyhaven_pin.get("build"),
        "patch_matches_khronos_main_hash": reconstructed_sha256 == run["mmgeo_main_sha256"],
        "patch_matches_polyhaven_main_hash": reconstructed_sha256 == polyhaven_main_sha256,
        "binary_hash_matches_across_runs": binary_hash_matches,
        "source_identity_resolved": reconstructed_sha256 == polyhaven_main_sha256,
        "clean_binary_rebuild_verified": False,
        "compiler_environment_recorded": bool(polyhaven_pin.get("build")),
        "retained_build_trace": build_trace,
        "exact_build_command_recorded": bool(
            build_trace.get("executable_matches_receipt")
            and build_trace.get("tlog_names_main_cpp")
            and build_trace.get("msbuild_invocation")
            and build_trace.get("main_cpp_compile_invocation")
        ),
        "scope": "The archived patch reconstructs the main.cpp hash recorded for the Khronos run. Poly Haven records a different main.cpp hash for the identical executable hash. A retained build trace names the matching executable and records its MSBuild and main.cpp compiler invocations, but it does not resolve which recorded source hash produced that binary or prove a clean source rebuild.",
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Khronos main.cpp hash reconstructed: {reconstructed_sha256}")
    print(f"Poly Haven recorded main.cpp hash: {polyhaven_main_sha256}")
    print(f"Matching mmgeo binary hash across runs: {binary_hash_matches}")
    print(f"Matched scored cohort source assets: {cohort_sources_covered}/{len(cohort_sources)}")
    print(f"Source identity resolved: {report['source_identity_resolved']}")
    print(f"Clean binary rebuild verified: {report['clean_binary_rebuild_verified']}")
    print(f"Receipt: {OUTPUT.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
