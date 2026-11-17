# Screen-support conflict graph audit (2026-11-16)

## Question

Can projected image-support conflicts be added to the topology conflict graph to form useful
parallel batches of image-driven edge collapses? The test asks whether conservative projected
boxes are simply too pessimistic, and whether measured filtered-residual support gives a better
batch without losing the additivity property.

## Protocol

- Torus, 1,152 source triangles; six archived orthographic views.
- 48 legal initial Corner candidates per view; each removes two triangles; candidate state is
  frozen at the source mesh.
- 128x128 output, 3x supersampling, finite Gaussian filter with sigma 0.9, coverage plus normalized
  depth error.
- Topology conflicts are candidates whose affected face one-rings share a vertex.
- Projected-support conflicts are intersections between per-affected-face old/new projected boxes,
  expanded by the existing six-output-pixel filter halo.
- Measured-delta-support conflicts are any shared output pixel where either candidate's archived
  filtered residual is nonzero. These supports are exact only for the single-collapse residuals in
  the archived renderer/export.
- A SciPy MILP solves maximum conflict-free cardinality, then minimum sum of individual candidate
  SSE at that cardinality. A second MILP finds the minimum-cost topology-only batch at the same
  cardinality. Every selected batch is applied to the source mesh and fully rerasterized.

## Results

| View | Projected-box conflict fraction | Max box-disjoint batch | Max residual-disjoint batch | Residual-disjoint batch SSE | Topology-only SSE at same count | Ratio |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 30.5% | 7 | 11 | 0.54578 | 0.0017284 | 316x |
| 1 | 28.3% | 7 | 11 | 0.64816 | 0.0003405 | 1,904x |
| 2 | 31.3% | 7 | 12 | 0.76048 | 0.0040910 | 186x |
| 3 | 27.5% | 8 | 12 | 0.55959 | 0.0024016 | 233x |
| 4 | 30.9% | 7 | 13 | 0.75215 | 0.0073186 | 103x |
| 5 | 32.1% | 7 | 12 | 1.64805 | 0.0035988 | 458x |

The exact residual supports remove some box false conflicts: among topology-compatible pairs, their
conflict fraction is 12.2–14.6%, versus 27.5–32.1% for projected boxes. The selected residual-
disjoint batches reproduce the full-composite SSE additively to at most `1.11e-16`, and all six
preserve the basic torus topology and signed orientation. Despite that, the best additive-cost
residual-disjoint schedule has 103–1,904 times the actual error of the topology-only schedule at
the same number of collapses. Residual-disjoint scheduling removes useful overlapping changes,
including cancellations; it does not improve the image-quality frontier in this pool.

The projected-box graph is still more restrictive: exact maximum batches contain only 7–8 of the
requested 12 collapses. At those counts, the best box-disjoint batches also have 875–24,973 times
the actual SSE of the topology-only minimum-cost batches at the same count.

All MILP runs returned optimal status with zero reported MIP gap. The environment emitted a version
warning: SciPy 1.15.3 requests NumPy below 2.5, while this workspace has NumPy 2.5.4. Treat the exact
optimization as a development result until it is reproduced in a supported SciPy/NumPy environment.

## Decision and limits

Close the strict screen-disjoint batch graph as the image-quality selector for the three frozen
Torus, Monkey, and Pirate pools. The box graph suppresses too much batch capacity; the measured-
residual graph preserves additivity but chooses much worse image-error batches at equal reduction.
There is no GPU timing or production simplifier result. This does not rule out regenerated
sequences, multi-view controls, or a graph used only for edit-safety bookkeeping, but none
currently supports a SIGGRAPH contribution claim.

These results are geometry-only and single-view-at-a-time. They say nothing about PBR shading,
shadows, motion, non-orthographic views, global self-intersections, or a full dynamic
simplification queue.

Reproduction:

```powershell
python -I tools/mmgeo/audit_selected_batch_support.py `
  out/filter-real-candidates/torus.json `
  out/fragment-transactions-cost-audit/torus.json `
  out/multi-collapse-interactions-20261116/torus.json `
  out/discrete-filter-pilot/torus.txt `
  --out out/screen-batch-support-20261116/torus-exact-support.json --exact-milp
```

Machine report: `out/screen-batch-support-20261116/torus-exact-support.json`.

## Cross-asset extension: Monkey and Pirate

The same frozen-pool experiment was run on Monkey and Pirate: six archived views per asset,
48 legal initial candidates per view, 12 requested collapses, 128x128 output, 3x supersampling,
the same finite Gaussian filter, and coverage plus normalized depth. Each schedule and output is
bound to the original capture, candidate-cost report, and residual export hashes. A hash-bound
topology-only greedy schedule was generated for each asset before the support audit.

| Asset | Projected-box conflicts | Exact box batch | Residual-support conflicts | Exact residual batch | Box SSE increase at matched count | Residual-support SSE increase at matched count |
|---|---:|---:|---:|---:|---:|---:|
| Torus | 27.5–32.1% | 7–8 | 12.2–14.5% | 11–13 | 0.111–2.143 | 0.544–1.644 |
| Monkey | 20.8–25.9% | 9–10 | 10.1–14.7% | 14–17 | 1.24e-5–1.78e-2 | 1.27e-3–4.50e-2 |
| Pirate | 23.2–29.1% | 7–8 | 10.6–20.7% | 11–14 | 5.12e-5–6.28e-2 | 4.53e-3–3.18e-1 |

The SSE increases compare the exact minimum-individual-cost disjoint batch with an exact
topology-only minimum-cost batch at the same count. Ratios range from 107x to 2.64 million x for
projected boxes, and 103x to 7.86 million x for measured residual supports. Some denominators are
near zero, so both ratios and absolute increases are reported; every per-view value is in the
machine reports. Residual-disjoint composites remain additive to at most `1.11e-16` and pass the
same basic topology/orientation checks across all three assets. Their quality loss therefore comes
from forbidding overlapping edits that can cancel, not from an inaccurate additivity calculation.

The exact MILPs all reported zero gaps, but all runs used SciPy 1.15.3 with NumPy 2.5.4 and emitted
the same unsupported-version warning. Reproduce with a supported dependency pair before treating
the optimizer output as a final exact result. Machine reports and generated topology-only schedule
manifests are `out/screen-batch-support-20261116/{monkey,pirate}-exact-support.json` and
`out/screen-batch-support-20261116/{monkey,pirate}-schedule.json`; summary command:

```powershell
python -I tools/mmgeo/summarize_batch_support_audit.py `
  out/screen-batch-support-20261116/torus-exact-support.json `
  out/screen-batch-support-20261116/monkey-exact-support.json `
  out/screen-batch-support-20261116/pirate-exact-support.json
```

This cross-asset result closes strict screen-disjoint batching as an image-quality selector for
these three archived geometry-only pools. All remain frozen initial candidates and single-view
screens; none measures regenerated queues, PBR appearance, or GPU throughput.
