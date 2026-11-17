"""Standard winding argument and structural eligibility; not a runtime result."""
import argparse
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path

import numpy as np

import depth_candidate_pilot as raster
from edit_visibility_support import boundary_chain
from visibility_query_bvh import cone_safe, fit_cone


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def exact_footprint(points, faces, point):
    winding, covered = 0, False
    for face in faces:
        tri = [points[i] for i in face]
        sides = []
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            sides.append((b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0]))
        if any(s == 0 for s in sides):
            return None  # Exclude projected edge/supporting-line cases in this exact control.
        area = (tri[1][0] - tri[0][0]) * (tri[2][1] - tri[0][1]) - (tri[1][1] - tri[0][1]) * (tri[2][0] - tri[0][0])
        if all(s > 0 for s in sides) or all(s < 0 for s in sides):
            winding += 1 if area > 0 else -1
            covered = True
    return covered, winding


def exact_control():
    # An embedded folded fan has a mixed-sign projection; a flat square cap does not.
    points = [(F(-1), F(-1), F(0)), (F(1), F(-1), F(0)),
              (F(1), F(1), F(0)), (F(-1), F(1), F(0)), (F(2), F(0), F(1, 3))]
    folded = [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    flat = [(0, 1, 2), (0, 2, 3)]
    if boundary_chain(np.asarray(folded)) != boundary_chain(np.asarray(flat)):
        raise ValueError("toy boundaries differ")
    counts = dict(checked=0, excludedBoundaryLines=0, proxyHits=0,
                  proxyMissesWithFineHit=0, proxyHitFineMiss=0)
    for x in range(-15, 24):
        for y in range(-15, 16):
            point = F(x, 8), F(y, 8)
            old, new = exact_footprint(points, folded, point), exact_footprint(points, flat, point)
            if old is None or new is None:
                counts["excludedBoundaryLines"] += 1
                continue
            if old[1] != new[1]:
                raise ValueError("equal boundary chains have different winding")
            counts["checked"] += 1
            counts["proxyHits"] += new[0]
            counts["proxyMissesWithFineHit"] += not new[0] and old[0]
            counts["proxyHitFineMiss"] += new[0] and not old[0]
    if counts["proxyHitFineMiss"] != 0 or counts["proxyMissesWithFineHit"] == 0:
        raise ValueError("asymmetric counterexample failed")
    signs = []
    for faces in (folded, flat):
        signs.append([])
        for a, b, c in ([points[i] for i in face] for face in faces):
            area = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            signs[-1].append(1 if area > 0 else -1)
    # Swapping source/proxy gives the corresponding invalid hit / valid miss control.
    return dict(**counts, sourceProjectedSigns=signs[0], proxyProjectedSigns=signs[1],
                reverseCaseProxyHitsWithFineMiss=counts["proxyMissesWithFineHit"],
                conclusion="same boundary + one-signed proxy: hit implies source hit; miss does not imply source miss")


def normal_cone(positions, faces):
    xyz = positions[faces]
    normals = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    return fit_cone(dict(normals=normals, chainValid=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    for name, expected in report["sourceHashes"].items():
        if sha(Path(__file__).with_name(name)) != expected:
            raise ValueError("bound experiment source changed: " + name)
    cases = []
    directions = np.array([[np.sin(a), .37, np.cos(a)] for a in np.linspace(0, 2 * np.pi, 12, endpoint=False)])
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    for asset in report["assets"]:
        if sha(asset["source"]["path"]) != asset["source"]["sha256"]:
            raise ValueError("source capture changed")
        world, _, _ = raster.load_capture(Path(asset["source"]["path"]))
        center = (world.min(0) + world.max(0)) * .5
        radius = np.linalg.norm(world - center, axis=1).max()
        positions = (world - center) / radius
        for row in asset["cuts"]:
            if sha(row["patches"]["path"]) != row["patches"]["sha256"]:
                raise ValueError("patch geometry changed")
            patches = json.loads(Path(row["patches"]["path"]).read_text(encoding="utf-8"))["patches"]
            counts = dict(reducedPatches=0, patchViewPairs=0, combinedPassPairs=0,
                          proxyOnlyPassPairs=0, sourceOnlyPassPairs=0,
                          additionalProxyPassPairs=0, additionalSourcePassPairs=0)
            for patch in patches:
                if "outputPositions" not in patch:
                    continue
                counts["reducedPatches"] += 1
                source = positions[np.asarray(patch["sourceVertices"])]
                old_cone = normal_cone(source, np.asarray(patch["sourceOrientedFaces"]))
                new_cone = normal_cone(np.asarray(patch["outputPositions"]), np.asarray(patch["outputFaces"]))
                combined = tuple(patch["cone"])
                for d in directions:
                    old, new, both = map(bool, (cone_safe(old_cone, d), cone_safe(new_cone, d), cone_safe(combined, d)))
                    counts["patchViewPairs"] += 1
                    counts["combinedPassPairs"] += both
                    counts["proxyOnlyPassPairs"] += new
                    counts["sourceOnlyPassPairs"] += old
                    counts["additionalProxyPassPairs"] += new and not both
                    counts["additionalSourcePassPairs"] += old and not both
            cases.append(dict(asset=asset["asset"], capacity=row["capacity"], **counts))
    result = dict(reportSha256=sha(args.report), scriptSha256=sha(__file__), exactToy=exact_control(), cases=cases,
        caveats=["standard oriented-chain winding implication; no new theorem claim",
                 "proxy same-facing certifies a hit; source same-facing certifies a proxy miss",
                 "full-span ray condition remains necessary; no finite endpoint/shading claim",
                 "patch-view pair counts are not weighted by actual visited rays or outcomes",
                 "no asymmetric query implemented or runtime gain demonstrated"])
    (args.report.parent / "asymmetric-eligibility.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
