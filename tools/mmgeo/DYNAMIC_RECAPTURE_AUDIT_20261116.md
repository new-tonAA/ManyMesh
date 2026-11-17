# Dynamic candidate recapture audit (2026-11-16)

## Question

Does recapturing legal Corner edge collapses after every accepted edit preserve a better image
than holding a small initial candidate sample fixed? This is a falsification experiment for the
frozen-pool limitation; it is not a novelty claim.

## Protocol

- Torus: 1,152 triangles, one submesh, captured by the repository's existing
  `mm_capture_candidates` utility.
- Greedy sequence length: 8 collapses, exactly 2 triangles per collapse (16/1,152 = 1.39%).
- The frozen and dynamic policies start from the same deterministic sample of 32 candidates
  whose affected triangles are visible in the fitted orthographic view. A second sample that
  allowed hidden candidates is retained separately as a negative control.
- Fitted-view score: Gaussian-filtered opaque coverage plus normalized front depth, 96 x 96
  output, 2x supersampling, sigma 0.9. Both policies greedily minimize cumulative SSE to the
  original image. The dynamic policy exports the changed mesh to OBJ and invokes the capture
  utility to regenerate candidates after each collapse; it then samples 32 visible candidates
  from the fresh legal pool.
- Every chosen patch score is checked against a full-image rerender. Each intermediate output is
  checked for Euler characteristic, connected components, closed two-manifold edge incidence,
  oriented-edge consistency, duplicate/zero-area faces, and signed-volume orientation.
- Final meshes are additionally measured at 128 x 128, 3x supersampling, over the fitted view,
  six nearby orbit views, and six evenly spaced full-orbit views. These final views do not affect
  candidate selection.

## Results

| Policy | Final faces | Fitted-view filtered SSE | 13-view final audit SSE | Selection, redraw, and recapture time |
|---|---:|---:|---:|---:|
| Frozen initial sample | 1,136 | 0.0022008961 | 1.9982251 | 2.97 s |
| Recapture after every collapse | 1,136 | 0.00000252542 | 0.0183502 | 5.80 s |

At this tiny reduction, the dynamic sequence lowers fitted-view SSE by 99.885% and the final
13-view audit sum by 99.082%. Both policies make eight legal collapses and pass the listed
topology checks at every step. Patch predictions match full redraw within 8.7e-19; OBJ recapture
matches the pre-export raw raster exactly. Candidate capture took 0.603 s across the eight dynamic
steps (about 75 ms per capture); total measured research work is about 1.96x the frozen run. The
dynamic pool contains 3,456 legal candidates initially and 3,408 after the eighth edit.

The dynamic policy keeps sampling 32 visible candidates per step. The frozen policy's remaining
non-conflicting sampled set falls from 32 to 11 by step eight. Thus the quality difference is
evidence that a small frozen sample is insufficient for a longer greedy sequence; it is not an
equal-work comparison against a full, continually updated edge-collapse queue.

### Hidden-candidate negative control

When the sampler was allowed to include candidates with no currently visible affected triangle,
all eight dynamic choices were fully hidden in the fitted view and the measured fitted-view SSE
stayed exactly zero. This is expected for view-dependent image simplification and contributes no
novel result. The archived control is `out/dynamic-recapture-20261116/dynamic-recapture-hidden-audit.json`.

## Novelty decision

Do not claim “dynamic candidate regeneration,” “image-driven collapse selection,” “local image
redraw,” or “simplify hidden geometry” as new. Lindstrom and Turk's *Image-Driven Simplification*
(ACM TOG 2000) already evaluates successive edge collapses against original multi-view rendered
images, updates local image regions, and explicitly reports aggressive simplification of hidden
surfaces. It also discusses stale costs for distant projected edges and lazy candidate reevaluation
([primary paper](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)).
The current experiment's stronger score relative to its deliberately small frozen sample remains
within that established formulation.

The other tested queue idea also lacks a result that justifies a contribution: the archived
projected-support queue audits choose the same candidates as the exact full-rescore oracle and the
topology-lazy baseline on their sampled sequences. Screen-support invalidation therefore adds
score updates without an observed quality gain; the samples do not establish a general speedup.

**Decision:** close the present filtered-image / dynamic-recapture idea as a standalone SIGGRAPH
contribution. A viable continuation needs a distinct mechanism and a held-out quality-versus-total-
work win over established image-driven simplification and current production baselines. This Torus
screen is not evidence of a SIGGRAPH-ready result.

The complete-pool follow-up replaced the 32-item baseline with all 2,218 visible legal initial
placements, then added a matched edge-frontier ablation where both methods refreshed current
placements. The full-pool fit-view gain did not survive a 13-view audit, and admitting newly
created edges overfit the fitted view. See
[`DYNAMIC_RECAPTURE_FULLPOOL_AUDIT_20261116.md`](DYNAMIC_RECAPTURE_FULLPOOL_AUDIT_20261116.md)
for the corrected controls and measurements.

## Reproduction

```powershell
python tools/mmgeo/audit_dynamic_recapture.py `
  out/filter-real-candidates/torus.json `
  --executable out/cmake-vulkan/tools/mmgeo/Release/mm_capture_candidates.exe `
  --out out/dynamic-recapture-20261116 `
  --steps 8 --size 96 --scale 2 --candidates 32
```

The machine-readable result, per-step topology and timings, camera audit, source hashes, and
fresh-capture outputs are in `out/dynamic-recapture-20261116/dynamic-recapture-audit.json`.
The capture executable was built from the existing C++ source; no C++ source was changed and no
software tests were run.
