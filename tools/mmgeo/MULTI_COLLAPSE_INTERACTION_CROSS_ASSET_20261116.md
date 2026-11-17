# Multi-collapse interaction screen across archived meshes (2026-11-16)

## Question

Does including pairwise filtered-residual cross terms change which compatible batch of legal
initial geometry collapses should be selected, and does the change improve actual composite image
error? This is a cancellation-aware extension of the independent single-collapse score. It is a
finite-pool feasibility screen, not a novelty claim.

## Protocol

- Torus, Monkey, and Pirate; six archived views per mesh and 48 frozen initial candidates per view.
- Every candidate removes two triangles; candidates in a batch have disjoint affected vertex sets.
- 128x128 output, 3x supersampling, Gaussian sigma 0.9, opaque coverage plus normalized depth.
- For 2 and 4 collapses, exhaustively minimize independent SSE and the pairwise residual Gram objective
  over compatible subsets. For 8 and 12, extend each objective with deterministic greedy selection.
- Apply each selected batch to the source geometry, rerasterize the full composite, and compare the
  pairwise prediction with measured composite SSE.

## Results

| Mesh | k=2 same / 6; gain | k=4 same / 6; gain | k=8 same / 6; mean gain | k=12 same / 6; gain |
|---|---|---|---|---|
| Torus | 6/6; 0% | 6/6; 0% | 6/6; 0% | 6/6; 0% |
| Monkey | 6/6; 0% | 6/6; 0% | 6/6; 0% | 6/6; 0% |
| Pirate | 6/6; 0% | 6/6; 0% | 5/6; 0.386% mean | 6/6; 0% |

All selected composites pass the audit's basic topology and signed-orientation checks. The largest
absolute difference between pairwise-predicted and fully rerasterized SSE is `2.58e-20` for Monkey
and `1.13e-22` for Pirate, so the pairwise model predicts these small, frozen-pool composites
accurately. The only different 8-collapse Pirate schedule is view 2; its actual SSE falls from
`3.6511e-9` to `3.5666e-9`, an absolute reduction of `8.45e-11`. Interaction scoring does not
change any 12-collapse schedule on any of the three meshes.

This closes pairwise filtered-residual correction as a useful selector for these frozen candidate
pools. The measured screen-support audit shows that overlapping changes can cancel, but the
cancellation-aware objective does not find a better batch here. This does not test regenerated
candidates, view-joint optimization, PBR shading, GPU execution, or full production quality gates.
The broad ingredients also have direct prior art: image-difference edge-collapse ranking and
global discrete edge-selection optimization. No SIGGRAPH mechanism is established.

## Reproduction

The Torus result is archived at
`out/multi-collapse-interactions-20261116/torus.json`. Monkey and Pirate outputs are
`out/screen-batch-support-20261116/{monkey,pirate}-interactions.json`, with per-view detail in the
matching Markdown reports. Commands:

```powershell
python -I tools/mmgeo/audit_multi_collapse_interactions.py `
  out/filter-real-candidates/monkey.json `
  out/fragment-transactions-cost-audit/monkey.json `
  out/discrete-filter-pilot/monkey.txt `
  --out out/screen-batch-support-20261116/monkey-interactions.json `
  --report-md out/screen-batch-support-20261116/monkey-interactions.md

python -I tools/mmgeo/audit_multi_collapse_interactions.py `
  out/filter-real-candidates/pirate.json `
  out/fragment-transactions-cost-audit/pirate.json `
  out/discrete-filter-pilot/pirate.txt `
  --out out/screen-batch-support-20261116/pirate-interactions.json `
  --report-md out/screen-batch-support-20261116/pirate-interactions.md
```

These runs modify only their requested outputs. The shared audit script now accepts
`--report-md` and no longer assumes a closed 1,152-face Torus; the archived Torus JSON and report
were left untouched.
