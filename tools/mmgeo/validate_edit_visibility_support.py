"""Check saved support masks independently of replay, orientation, and box construction."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    if not __debug__:
        raise RuntimeError("validator requires Python assertions enabled")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    result = json.loads(args.report.read_text(encoding="utf-8"))
    assert result["scriptSha256"] == sha(Path(__file__).with_name("edit_visibility_support.py"))
    assert result["rasterSha256"] == sha(Path(__file__).with_name("depth_candidate_pilot.py"))
    assert result["helperSha256"] == sha(Path(__file__).with_name("proxy_visibility_cost_gate.py"))
    comparisons = 0
    hybrids = 0
    for asset in result["assets"]:
        for field in ("capture", "manifest", "archivedEvaluation", "maskArtifact"):
            binding = asset[field]
            assert binding["sha256"] == sha(binding["path"]), binding
        assert asset["normalizationRoundtripCoverageVerified"]
        with np.load(asset["maskArtifact"]["path"], allow_pickle=False) as archive:
            fine = archive["fine"]
            cohort = archive["source_rectangle"]
            assert fine.dtype == bool and fine.shape == (12, 384, 384)
            assert cohort.shape == fine.shape and cohort.dtype == bool
            assert not np.any(fine & ~cohort)
            for ratio, level in asset["levels"].items():
                assert level["artifact"]["sha256"] == sha(level["artifact"]["path"])
                coarse = archive["coarse_" + ratio]
                assert coarse.shape == fine.shape and coarse.dtype == bool
                mismatch = fine != coarse
                assert level["disagreements"] == int(mismatch.sum())
                assert level["fineHits"] == int(fine.sum())
                assert level["sourceRectangleSamples"] == int(cohort.sum())
                all_masks = {}
                for name in ("historyBoxes", "coneFilteredBoxes", "endpointBoxes"):
                    mask = archive[name + "_" + ratio]
                    all_masks[name] = mask
                    assert mask.shape == fine.shape and mask.dtype == bool
                    # A real exact fallback construction: select fine inside the support,
                    # otherwise use proxy. No direction or envelope functions are called.
                    corrected = np.where(mask, fine, coarse)
                    assert np.array_equal(corrected, fine), (asset["asset"], ratio, name)
                    totals = level["totals"][name]
                    assert totals["samples"] == fine.size
                    assert totals["fallbackSamples"] == int(mask.sum())
                    assert totals["fallbackInsideSourceRectangle"] == int((mask & cohort).sum())
                    assert totals["fallbackOnFineHits"] == int((mask & fine).sum())
                    assert totals["fallbackOnFineMisses"] == int((mask & ~fine).sum())
                    assert totals["missedDisagreements"] == 0
                    assert totals == {key: sum(v["masks"][name][key] for v in level["views"])
                                      for key in totals}
                    for index, view in enumerate(level["views"]):
                        assert view["masks"][name]["fallbackSamples"] == int(mask[index].sum())
                        assert view["disagreements"] == int(mismatch[index].sum())
                    hybrids += len(fine)
                assert not np.any(all_masks["coneFilteredBoxes"] & ~all_masks["historyBoxes"])
                comparisons += len(fine)
    verification = dict(reportSha256=sha(args.report), comparisons=comparisons,
        exactHybridCoverageComparisons=hybrids, masksChecked=3,
        scope="saved finite binary masks only; not robust geometry or timing verification",
        validatorSha256=sha(__file__))
    (args.report.parent / "validation.json").write_text(
        json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
