#!/usr/bin/env python3
"""Search recorded ManyMesh experiment artifacts for prior use of an asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".csv", ".cjs", ".js", ".json", ".md", ".py", ".txt", ".yaml", ".yml"}
DEFAULT_ROOTS = [
    "tools/mmgeo",
    "tools/mmmetrics",
    "tools/mmtrain",
    "tools/mmgpu",
    "tools/mmtemporal",
    "tools/mmscene",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_state() -> dict[str, object]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
            ).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return {"head_commit": None, "worktree_dirty": None}
    return {"head_commit": commit, "worktree_dirty": dirty}


def collect_files(roots: list[str], output: Path | None) -> list[Path]:
    excluded = output.resolve() if output is not None else None
    found: set[Path] = set()
    for name in roots:
        path = (ROOT / name).resolve()
        candidates = path.rglob("*") if path.is_dir() else [path]
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                relative = candidate.relative_to(ROOT)
            except ValueError:
                continue
            if any(part in {".git", "out", "build", "third_party"} for part in relative.parts):
                continue
            if "asset_reuse_audits" in relative.parts:
                continue
            if excluded is not None and candidate.resolve() == excluded:
                continue
            found.add(candidate.resolve())
    return sorted(found)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", type=Path, required=True, help="source asset to audit")
    parser.add_argument("--roots", nargs="+", default=DEFAULT_ROOTS, help="artifact roots, relative to repo")
    parser.add_argument("--output", type=Path, help="optional JSON receipt path, relative to repo")
    args = parser.parse_args()

    asset = args.asset.resolve()
    if not asset.is_file():
        parser.error(f"asset does not exist: {asset}")
    output = (ROOT / args.output).resolve() if args.output else None
    asset_hash = sha256(asset)
    needles = {"sha256": asset_hash.lower(), "filename": asset.name.casefold(), "stem": asset.stem.casefold()}

    scanned: list[dict[str, str]] = []
    matches: list[dict[str, object]] = []
    for path in collect_files(args.roots, output):
        relative = path.relative_to(ROOT).as_posix()
        try:
            content = path.read_text(encoding="utf-8").casefold()
        except (OSError, UnicodeDecodeError):
            continue
        scanned.append({"path": relative, "sha256": sha256(path)})
        kinds = [kind for kind, needle in needles.items() if needle in content]
        if kinds:
            matches.append({"path": relative, "match_kinds": kinds})

    receipt: dict[str, object] = {
        "schema": 1,
        "asset_path": asset.relative_to(ROOT).as_posix() if asset.is_relative_to(ROOT) else str(asset),
        "asset_sha256": asset_hash,
        "search_roots": args.roots,
        "search_manifest": scanned,
        "matches": matches,
        "git_state_at_audit_time": git_state(),
        "audit_script_sha256": sha256(Path(__file__).resolve()),
        "scope_note": "A text-artifact scan only. Absence of a match does not prove that an asset was never used in unarchived or non-text runs.",
    }
    serialized = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(serialized, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8", newline="\n")
        print(f"Wrote {output.relative_to(ROOT).as_posix()}")
        print(f"Asset SHA-256: {asset_hash}")
        print(f"Scanned {len(scanned)} text artifacts; found {len(matches)} matching artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
