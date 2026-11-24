#!/usr/bin/env python3
"""Read source SHA-256 checksums from retained MSVC CodeView object files."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "out/cmake-cut-audit"
OUTPUT = ROOT / "tools/mmtrain/mmgeo_compiled_source_audit_20261125.json"
POLYHAVEN_METRICS = ROOT / "tools/mmtrain/polyhaven_quality_metrics_20261124.json"
KHRONOS_RECEIPT = ROOT / "tools/mmtrain/khronos_equal_face_quality_screen_20261123.json"
OLD_AUDIT = ROOT / "tools/mmtrain/mmgeo_source_provenance_audit_20261124.json"
GEOMETRY_REPLAY = ROOT / "tools/mmtrain/polyhaven_geometry_replay_20261125.json"
DEFAULT_LLVM = Path(
    "D:/visual studio 2022/VC/Tools/Llvm/bin/llvm-readobj.exe"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def codeview_checksums(llvm: Path, obj: Path) -> dict[str, str]:
    result = subprocess.run([str(llvm), "--codeview", str(obj)],
                            capture_output=True, text=True, check=True)
    checksums: dict[str, str] = {}
    for match in re.finditer(r"FileChecksum\s*\{(.*?)\n\s*\}", result.stdout,
                             re.DOTALL):
        block = match.group(1)
        name = re.search(r"Filename:\s+(.+?)\s+\(0x[0-9A-Fa-f]+\)", block)
        kind = re.search(r"ChecksumKind:\s+SHA256", block)
        payload = re.search(r"ChecksumBytes\s*\((.*?)\)", block, re.DOTALL)
        if not (name and kind and payload):
            continue
        words = []
        for line in payload.group(1).splitlines():
            line_match = re.match(r"\s*[0-9A-Fa-f]{4}:\s+(.*?)\s+\|", line)
            if line_match:
                words.extend(re.findall(r"[0-9A-Fa-f]{2}", line_match.group(1)))
        checksum = "".join(words).lower()
        if len(checksum) == 64:
            checksums[name.group(1).replace("/", "\\").lower()] = checksum
    if not checksums:
        raise RuntimeError(f"No SHA-256 CodeView checksums found in {obj}")
    return checksums


def tlog_text(path: Path) -> str:
    return path.read_bytes().decode("utf-16le", errors="replace").upper()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llvm-readobj", type=Path, default=DEFAULT_LLVM)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    llvm = args.llvm_readobj.resolve()
    if not llvm.is_file():
        raise SystemExit(f"llvm-readobj not found: {llvm}")

    main_obj = BUILD / "tools/mmgeo/mmgeo.dir/Release/main.obj"
    simplifier_obj = BUILD / "libs/manymesh/manymesh.dir/Release/Simplifier.obj"
    executable = BUILD / "tools/mmgeo/Release/mmgeo.exe"
    link_command = BUILD / "tools/mmgeo/mmgeo.dir/Release/mmgeo.tlog/link.command.1.tlog"
    link_read = BUILD / "tools/mmgeo/mmgeo.dir/Release/mmgeo.tlog/link.read.1.tlog"
    compile_command = BUILD / "tools/mmgeo/mmgeo.dir/Release/mmgeo.tlog/CL.command.1.tlog"
    build_log = BUILD / "out/cmake-cut-audit/msbuild.log"
    lib_command = BUILD / "libs/manymesh/manymesh.dir/Release/manymesh.tlog/Lib.command.1.tlog"
    lib_read = BUILD / "libs/manymesh/manymesh.dir/Release/manymesh.tlog/Lib-link.read.1.tlog"
    source_pin = read_json(BUILD / "source-pin.json")
    polyhaven = read_json(POLYHAVEN_METRICS)["geometry_build"]
    polyhaven_sources = polyhaven["source_revision_pin"]["modified_source_sha256"]
    khronos = read_json(KHRONOS_RECEIPT)["run_provenance"]
    old_audit = read_json(OLD_AUDIT)

    main_checksums = codeview_checksums(llvm, main_obj)
    simplifier_checksums = codeview_checksums(llvm, simplifier_obj)
    main_cpp = r"e:\manymesh\tools\mmgeo\src\main.cpp"
    simplifier_cpp = r"e:\manymesh\libs\manymesh\src\simplifier.cpp"
    simplifier_h = r"e:\manymesh\libs\manymesh\include\manymesh\simplifier.h"
    compiled = {
        "tools/mmgeo/src/main.cpp": main_checksums.get(main_cpp),
        "libs/manymesh/src/Simplifier.cpp": simplifier_checksums.get(simplifier_cpp),
        "libs/manymesh/include/manymesh/Simplifier.h": simplifier_checksums.get(simplifier_h),
    }
    recorded = source_pin["modified_source_sha256"]
    link_command_text = tlog_text(link_command)
    link_read_text = tlog_text(link_read)
    compile_command_text = tlog_text(compile_command)
    lib_command_text = tlog_text(lib_command)
    lib_read_text = tlog_text(lib_read)
    binary_hash = digest(executable)
    replay = read_json(GEOMETRY_REPLAY)
    binary_matches_receipts = (
        binary_hash == polyhaven["mmgeo_sha256"] == khronos["mmgeo_binary_sha256"]
    )
    linked_inputs = {
        "main_obj": "MAIN.OBJ" in link_command_text and "MAIN.OBJ" in link_read_text,
        "manymesh_library": "MANYMESH.LIB" in link_command_text and "MANYMESH.LIB" in link_read_text,
        "simplifier_obj": "SIMPLIFIER.OBJ" in lib_command_text and "SIMPLIFIER.OBJ" in lib_read_text,
        "main_cpp_compile_tlog": "TOOLS\\MMGEO\\SRC\\MAIN.CPP" in compile_command_text,
    }
    matches = {
        "binary_matches_receipts": binary_matches_receipts,
        "compiled_main_matches_reconstructed_khronos_source": (
            compiled["tools/mmgeo/src/main.cpp"]
            == old_audit["main_cpp_reconstructed_sha256"]
            == khronos["mmgeo_main_sha256"]
        ),
        "compiled_simplifier_cpp_matches_polyhaven_pin": (
            compiled["libs/manymesh/src/Simplifier.cpp"]
            == polyhaven_sources["libs/manymesh/src/Simplifier.cpp"]
        ),
        "compiled_simplifier_h_matches_polyhaven_pin": (
            compiled["libs/manymesh/include/manymesh/Simplifier.h"]
            == polyhaven_sources["libs/manymesh/include/manymesh/Simplifier.h"]
        ),
        "all_link_inputs_verified": all(linked_inputs.values()),
        "expanded_geometry_replay_complete": (
            replay["status"] == "all_archived_candidates_reproduced_byte_for_byte"
            and replay["summary"]["byte_for_byte_matches"] == 18
            and replay["summary"]["face_count_matches"] == 18
        ),
    }
    if not all(matches.values()):
        raise SystemExit(f"compiled-source audit checks failed: {matches}")

    report = {
        "schema": 1,
        "status": "compiled source checksums identify the recorded main.cpp pin mismatch",
        "script_sha256": digest(Path(__file__)),
        "tool": {
            "path": str(llvm),
            "sha256": digest(llvm),
            "version": subprocess.run([str(llvm), "--version"], capture_output=True,
                                      text=True, check=True).stdout.strip()
        },
        "retained_build": {
            "binary": executable.relative_to(ROOT).as_posix(),
            "binary_sha256": binary_hash,
            "binary_matches_polyhaven_and_khronos_receipts": binary_matches_receipts,
            "main_obj": main_obj.relative_to(ROOT).as_posix(),
            "main_obj_sha256": digest(main_obj),
            "simplifier_obj": simplifier_obj.relative_to(ROOT).as_posix(),
            "simplifier_obj_sha256": digest(simplifier_obj),
            "build_log": build_log.relative_to(ROOT).as_posix(),
            "build_log_sha256": digest(build_log),
            "main_cpp_compile_tlog_sha256": digest(compile_command),
            "recorded_compile_invocation": old_audit["retained_build_trace"]["main_cpp_compile_invocation"],
            "main_obj_last_write_local": datetime.fromtimestamp(
                main_obj.stat().st_mtime
            ).astimezone().isoformat(),
            "executable_last_write_local": datetime.fromtimestamp(
                executable.stat().st_mtime
            ).astimezone().isoformat(),
            "link_command_tlog_sha256": digest(link_command),
            "link_read_tlog_sha256": digest(link_read),
            "manymesh_lib_command_tlog_sha256": digest(lib_command),
            "manymesh_lib_read_tlog_sha256": digest(lib_read),
            "link_tlog_names_main_obj": linked_inputs["main_obj"],
            "link_tlog_names_manymesh_library": linked_inputs["manymesh_library"],
            "manymesh_library_tlog_names_simplifier_obj": linked_inputs["simplifier_obj"],
            "compile_tlog_names_main_cpp": linked_inputs["main_cpp_compile_tlog"],
        },
        "compiled_source_sha256": compiled,
        "recorded_source_sha256": {
            "polyhaven_pin": polyhaven_sources,
            "polyhaven_source_pin_file": recorded,
            "khronos_main_cpp": khronos["mmgeo_main_sha256"],
        },
        "comparisons": {
            **matches,
            "compiled_main_matches_khronos_receipt": compiled["tools/mmgeo/src/main.cpp"] == khronos["mmgeo_main_sha256"],
            "compiled_main_matches_polyhaven_receipt": compiled["tools/mmgeo/src/main.cpp"] == polyhaven_sources["tools/mmgeo/src/main.cpp"],
            "compiled_main_matches_build_source_pin": compiled["tools/mmgeo/src/main.cpp"] == recorded["tools/mmgeo/src/main.cpp"],
            "compiled_simplifier_cpp_matches_polyhaven_pin": compiled["libs/manymesh/src/Simplifier.cpp"] == polyhaven_sources["libs/manymesh/src/Simplifier.cpp"],
            "compiled_simplifier_h_matches_polyhaven_pin": compiled["libs/manymesh/include/manymesh/Simplifier.h"] == polyhaven_sources["libs/manymesh/include/manymesh/Simplifier.h"],
            "compiled_main_matches_khronos_and_polyhaven_simplifier_source_set": (
                compiled["tools/mmgeo/src/main.cpp"] == khronos["mmgeo_main_sha256"]
                and compiled["libs/manymesh/src/Simplifier.cpp"] == polyhaven_sources["libs/manymesh/src/Simplifier.cpp"]
                and compiled["libs/manymesh/include/manymesh/Simplifier.h"] == polyhaven_sources["libs/manymesh/include/manymesh/Simplifier.h"]
            ),
            "expanded_cohort_binary_geometry_replay_status": replay["status"],
            "expanded_cohort_byte_identical_assets": replay["summary"]["byte_for_byte_matches"],
        },
        "clean_source_rebuild_verified": False,
        "conclusion": (
            "The retained MSVC object checksums show the archived executable was linked from a main.obj compiled with the Khronos main.cpp SHA-256, while Simplifier.cpp and Simplifier.h match the Poly Haven pin. This identifies the Poly Haven main.cpp source pin as inconsistent with the retained compiler input. The archived binary hash matches both experiment receipts and its 18-asset expansion geometry replay is byte-identical. A clean source rebuild was not verified."
        ),
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8",
                      newline="\n")
    print("Compiled main.cpp:", compiled["tools/mmgeo/src/main.cpp"])
    print("Compiled Simplifier.cpp:", compiled["libs/manymesh/src/Simplifier.cpp"])
    print("Compiled Simplifier.h:", compiled["libs/manymesh/include/manymesh/Simplifier.h"])
    print("Binary source mismatch identified:", report["comparisons"]["compiled_main_matches_polyhaven_receipt"] is False)
    print("Receipt:", output.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
