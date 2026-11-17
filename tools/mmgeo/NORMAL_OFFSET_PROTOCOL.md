# Signed coverage and fixed-budget normal-offset control

2026-11-15. Screening a shrinkage hypothesis; not an original-method claim.

Existing QEM at 25% retention has Torus missing/extra counts 5554/5107 and Pirate 7143/3450
across twelve measured views. Both signs matter; calling all silhouette loss shrinkage is wrong.
Monkey has 350/246, also small absolute sample counts. These observed development results motivate
a NEW fixed control; they are not an independent test set.

Fix topology and face count at the saved QEM 25% checkpoint (Pirate actually 26.23%). Compute
area-weighted vertex normals and multiply each by its mean incident edge length. Freeze the
direction field; boundary/nonmanifold-edge vertices remain fixed. Try scalar offsets
0, +/-1/64, +/-1/32, +/-1/16. Each position must retain local orientation/quality and nonzero areas.
Choose only on eight construction azimuths 0.13+2*pi*k/8 at elevation component .37, with the same
128px, scale3, sigma.9 coverage+depth SSE objective. Zero is first for ties and remains fallback.
The twelve existing measurement azimuths starting at zero never select or revert a position.
No test-view-specific correction is allowed. All alphas, failures and fit scores are saved.

Compare the selected result to QEM, all source contours and visible source contours at the same
actual face count. Report individual view regressions as well as aggregate. A scalar offset is
a deliberately low-dimensional classical control, not a geometry-update runtime algorithm.
Success could set a higher baseline bar; it would not establish novel curvature reconstruction.
Failure would reject only this direction field/discrete offset set, not all curvature correction.

Volume/boundary area preservation are already established geometric simplification concepts;
automatic appearance/geometry optimization is also established. No novelty follows from normal
offsets or optimizing against rendered references. Closest-work search includes:
- Lindstrom & Turk, Evaluation of Memoryless Simplification (1999):
  https://sites.cc.gatech.edu/gvu/people/faculty/greg.turk/my_papers/memless_tvcg99.pdf
- Appearance-Driven Automatic 3D Model Simplification: https://arxiv.org/abs/2104.03989
The narrow mathematical search here does not establish a gap from the full literature.

No UV/material, distance bound, new intersection detection, time coherence or GPU cost claims.
The normal direction inherits source winding; testing both signs avoids assuming an outward
orientation. This is a new geometry-only artifact, never a production or publication readiness result.

## Frozen-grid outcome

All three assets choose zero offset using only the eight fitting views. Fit SSE:

| Asset | Zero offset | Best admissible nonzero offset | Selected alpha |
|---|---:|---:|---:|
| Torus | 127.82314 | 223.03978 (+1/64) | 0 |
| Monkey | 1.02868 | 4.33716 (+1/64) | 0 |
| Pirate | 168.64041 | 169.39776 (+1/64) | 0 |

Geometry checks reject -1/16 for Monkey and all three negative offsets for Pirate. These failures
are retained, not silently removed from the report. Torus admits every tested offset. No new
sample was selected after seeing test outcomes. Smaller continuous offsets, per-vertex signed
corrections and other curvature fields were NOT tested: this finite-grid result does not rule
them out. The observed net coverage imbalance alone is insufficient evidence for this correction.

The final output arrays are verified BIT-IDENTICAL to the original QEM at the same triangle
count. Therefore the existing full-orbit QEM evaluations apply unchanged; we do not claim to
have performed another test-orbit rerender for identical geometry. The summary binds hashes of
the original meshes/manifests/evaluations and the new meshes/fit reports. This distinguishes a
proved unchanged fallback from a new geometry quality gain. No source-contour win is claimed.

Final runs are `out/normal-offset-control-v2/`. An initial run was superseded to ensure the zero
fallback copies input positions exactly rather than normalizing/de-normalizing them. The initial
Monkey run was interrupted; it is not counted as a completed experiment. Final v2 fitting wall
times were 9.24/61.15/13.08 seconds in Python, with assets launched concurrently, including
reference rendering, all admissible variants and file writes. No runtime speed claim follows.

Four added regression tests check boundary displacement locks, local flip/degeneracy rejection,
missing-vs-extra coverage signs and zero bias of equal coverage. Total Python suite: 52 passed;
`git diff --check` passes. No new C++ build or material/temporal validation is implied.

```sh
python -I tools/mmgeo/audit_silhouette_bias.py out/filter-real-candidates/torus.json out/progressive-baseline/torus
python -I tools/mmgeo/normal_offset_control.py out/filter-real-candidates/torus.json out/progressive-baseline/torus --out out/normal-offset-control-v2/torus
python -I tools/mmgeo/summarize_normal_offset.py
```

Run the first two commands for all three assets before aggregation. Keep the zero-offset
fallback as evidence of failure for this control, not as evidence of a successful repair.
