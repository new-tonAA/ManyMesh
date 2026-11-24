#!/usr/bin/env python3
"""Verify the archived mmgeo binary against the clean commit-489 rebuild."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess


ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "tools/mmtrain/mmgeo_clean_rebuild_489_20261125.json"
SOURCE_TREE = ROOT / "out/mmgeo-worktree-489-20261125"
BUILD = SOURCE_TREE / "build-mmgeo-release-20261125"
ARCHIVED = ROOT / "out/cmake-cut-audit/tools/mmgeo/Release/mmgeo.exe"
REBUILT = BUILD / "tools/mmgeo/Release/mmgeo.exe"
EXPECTED_COMMIT = "489b275dd472117ae5cc528de0443cf04bd31aa9"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def section_ranges(pe: bytes) -> dict[str, tuple[int, int]]:
    pe_offset = struct.unpack_from("<I", pe, 0x3C)[0]
    section_count = struct.unpack_from("<H", pe, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", pe, pe_offset + 20)[0]
    table = pe_offset + 24 + optional_size
    result = {}
    for index in range(section_count):
        offset = table + index * 40
        name = pe[offset:offset + 8].split(b"\0", 1)[0].decode("ascii")
        size, raw_offset = struct.unpack_from("<II", pe, offset + 16)
        result[name] = (raw_offset, size)
    return result


def main() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert digest(Path(__file__).read_bytes()) == receipt[
        "verification_script_sha256"
    ]
    commit = subprocess.run(
        ["git", "-C", str(SOURCE_TREE), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert commit == EXPECTED_COMMIT, commit
    archived = ARCHIVED.read_bytes()
    rebuilt = REBUILT.read_bytes()
    assert len(archived) == len(rebuilt)
    assert digest(archived) == receipt["binary_comparison"]["archived_sha256"]
    assert digest(rebuilt) == receipt["binary_comparison"]["rebuilt_sha256"]

    differences = [
        index for index, (left, right) in enumerate(zip(archived, rebuilt))
        if left != right
    ]
    pe_offset = struct.unpack_from("<I", archived, 0x3C)[0]
    coff_timestamp = pe_offset + 8
    sections = section_ranges(archived)
    rdata_offset, _ = sections[".rdata"]
    duplicate_timestamp = rdata_offset + 0x279A4
    allowed = set(range(coff_timestamp, coff_timestamp + 4))
    allowed.update(range(duplicate_timestamp, duplicate_timestamp + 4))
    assert set(differences) <= allowed
    assert len(differences) == 6
    assert archived[coff_timestamp:coff_timestamp + 4] == archived[
        duplicate_timestamp:duplicate_timestamp + 4
    ]
    assert rebuilt[coff_timestamp:coff_timestamp + 4] == rebuilt[
        duplicate_timestamp:duplicate_timestamp + 4
    ]

    old_sections = section_ranges(archived)
    new_sections = section_ranges(rebuilt)
    for name in old_sections:
        old_offset, old_size = old_sections[name]
        new_offset, new_size = new_sections[name]
        assert old_size == new_size
        if name == ".rdata":
            old_data = bytearray(archived[old_offset:old_offset + old_size])
            new_data = bytearray(rebuilt[new_offset:new_offset + new_size])
            for absolute in (duplicate_timestamp,):
                relative = absolute - old_offset
                old_data[relative:relative + 4] = new_data[relative:relative + 4]
            assert old_data == new_data
        else:
            assert archived[old_offset:old_offset + old_size] == rebuilt[
                new_offset:new_offset + new_size
            ], name

    for relative, expected in receipt["source_sha256"].items():
        assert digest((SOURCE_TREE / relative).read_bytes()) == expected, relative

    print("Source commit:", commit)
    print("Archived binary SHA-256:", digest(archived))
    print("Rebuilt binary SHA-256:", digest(rebuilt))
    print("Different bytes: 6, all in the duplicated PE timestamp fields")
    print("All other bytes, including .text, match.")


if __name__ == "__main__":
    main()
