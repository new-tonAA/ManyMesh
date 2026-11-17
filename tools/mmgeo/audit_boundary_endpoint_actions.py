#!/usr/bin/env python3
"""Audit endpoint-control actions against CornerSimplifier's lockBorder prechecks.

This is a source-rule comparison on a frozen action sequence, not a production replay. It reports
which accepted Python boundary-endpoint collapses would have been refused by the current Corner
lockBorder fan checks before attribute and quality evaluation.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from audit_obj_contract_floor import read_capture


def edges(triangles):
    counts = Counter(tuple(sorted((tri[i], tri[(i + 1) % 3])))
                     for tri in triangles for i in range(3))
    return {edge for edge, uses in counts.items() if uses == 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("partition_report", type=Path)
    parser.add_argument("endpoint_report", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    frozen = json.loads(args.partition_report.read_text(encoding="utf-8"))
    endpoint = json.loads(args.endpoint_report.read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parents[2]
    all_assets = []
    totals = Counter()
    for asset, measured in zip(frozen["assets"], endpoint["assets"]):
        if asset["path"] != measured["path"]:
            raise ValueError("asset order/path mismatch")
        partition = next(item for item in asset["partitions"]
                         if item["capacity"] == endpoint["capacity"])
        capture_path = root / asset["path"]
        if hashlib.sha256(capture_path.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("frozen capture hash mismatch")
        source_faces, _, _ = read_capture(capture_path)
        if len(partition["groups"]) != len(measured["group_results"]):
            raise ValueError("group count mismatch")
        group_vertex_uses = Counter(
            vertex for group in partition["groups"] for vertex in set(group["source_vertices"]))
        result = Counter()
        checked_groups = 0
        for group, simplified in zip(partition["groups"], measured["group_results"]):
            if simplified["status"] != "checked":
                continue
            checked_groups += 1
            ids = group["source_vertices"]
            remap = {source: local for local, source in enumerate(ids)}
            locked_source = {source for source in ids if group_vertex_uses[source] > 1}
            faces = [[remap[v] for v in source_faces[face][1]]
                     for face in group["source_faces"]]
            boundary_vertices = {v for edge in edges(faces) for v in edge}
            actions = simplified["actions"]
            for action in actions:
                keep, remove = int(action["keep"]), int(action["remove"])
                incident = [face for face in faces if remove in face]
                if keep in boundary_vertices:
                    result["boundary_target_actions"] += 1
                    result["boundary_target_removed_faces"] += 2
                    result["boundary_target_fan_faces"] += len(incident)
                    nonkeep = sum(keep not in face for face in incident)
                    if nonkeep:
                        result["strict_keep_border_rejections"] += 1
                        result["strict_keep_border_affected_faces"] += nonkeep
                    keep_source = ids[keep]
                    if keep_source in locked_source:
                        result["shared_boundary_target_actions"] += 1
                        chord_faces = sum(
                            keep not in face and any(
                                ids[v] in locked_source for v in face if v not in (remove, keep))
                            for face in incident)
                        if chord_faces:
                            result["locked_chord_rejections_after_fan_relaxation"] += 1
                            result["locked_chord_affected_faces"] += chord_faces
                    else:
                        result["unshared_boundary_target_actions"] += 1
                    current_boundary = edges(faces)
                    has_boundary_face = any(
                        any(tuple(sorted((face[i], face[(i + 1) % 3]))) in current_boundary
                            for i in range(3)) for face in incident)
                    if has_boundary_face:
                        result["strict_boundary_face_rejections"] += 1
                changed = []
                for face in faces:
                    if remove in face:
                        updated = [keep if v == remove else v for v in face]
                        if len(set(updated)) < 3:
                            continue
                        changed.append(updated)
                    else:
                        changed.append(face)
                if edges(changed) != edges(faces):
                    raise ValueError("recorded endpoint action changes exact boundary edges")
                faces = changed
            if len(faces) != simplified["actual"]:
                raise ValueError("action replay triangle count mismatch")
        asset_result = dict(path=asset["path"], checked_groups=checked_groups,
                            counts=dict(result))
        all_assets.append(asset_result)
        totals.update(result)
        print(Path(asset["path"]).stem, "checked", checked_groups,
              "boundary-target-actions", result["boundary_target_actions"],
              "strict-fan-blocked", result["strict_keep_border_rejections"],
              "strict-boundary-face-blocked", result["strict_boundary_face_rejections"],
              flush=True)
    report = dict(schema=1,
                  scope="frozen action replay against source lockBorder prechecks; not production replay",
                  partition_report_sha256=hashlib.sha256(args.partition_report.read_bytes()).hexdigest(),
                  endpoint_report_sha256=hashlib.sha256(args.endpoint_report.read_bytes()).hexdigest(),
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  assets=all_assets, totals=dict(totals),
                  limitations=["does not evaluate subsequent actions after refusing a recorded action",
                               "does not reproduce production attribute, surface-error, or quality gates",
                               "cross-group source-vertex use is only a proxy for the production locked mask",
                               "counts source lockBorder precheck conflicts only"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, separators=(",", ":"))
        stream.write("\n")
    print("wrote", args.out, flush=True)


if __name__ == "__main__":
    main()
