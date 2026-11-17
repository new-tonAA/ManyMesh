# Same-Budget DAG Reallocation Screen (2026-11-16)

## Question

At a frozen Pirate 55% cut, does the current DAG expose any equal-triangle split/merge
or composite reallocation that improves its existing worst projected geometric-error
proxy? This is a bounded headroom screen for budget-conditioned repair, not an image
quality evaluation or an exhaustive cut oracle.

## Frozen input and command

- Input: `third_party/meshoptimizer/demo/pirate.obj`, SHA-256
  `cf11ea6f1fad6688123fbb80c5ca39ad5e48908cfa53d68e09a3f03f53c524a1`.
- Executable: `out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe`, SHA-256
  `46b5ab1fe0cbf2ab9c2e1eb900fd94dfb7df08665eddce955118849e96774900`.
- Output graph: `out/target-budget-oracle-20261116/pirate-g8/lod_graph.json`, SHA-256
  `e5757b9451f95bfa6da3ee0b3fe4c4979b0e873792859776744ec4171be26b66`.
- Candidate manifest: `out/target-budget-oracle-20261116/pirate-g8/oracle.csv`, SHA-256
  `1bb0be220360598f67354b0cd419318d72ababd07e82557957f2d76c36c7da6a`.
- Analysis script: `tools/mmgeo/analyze_budget_oracle_screen.py`, SHA-256
  `0a4f3d768aa1d9eaf47268fdea63c154e80438a9c37c7fa3f735b58d683c4e52`.
- Recomputed result: `out/target-budget-oracle-20261116/pirate-g8/oracle_screen_analysis.json`,
  SHA-256 `68ab72e224b212a7f789504831242f2dc5c7a6f6e51f5e12765f9ae3f79374d`.

Command:

```powershell
& '.\out\cmake-vulkan\tools\mmgeo\Release\mmgeo.exe' `
  'third_party/meshoptimizer/demo/pirate.obj' `
  --out 'out/target-budget-oracle-20261116/pirate-g8' `
  --mode dag --levels 7 --ratio 0.7 --tier balanced --target-ratio 0.55 `
  --dag-group 8 --corner-seam 1 --corner-split-uv 1 --quality-gate 1 `
  --dump-obj 1 --dump-format ply --write-dag 1 --target-ratio-cut 0.55 `
  --oracle-swaps 64 --oracle-composites 64
```

The build produced the same 184-node DAG as the earlier group-8 pilot in about 2.90 s.
The tool exported three equal-triangle single swaps and 64 composite candidates; all
exported cuts contain exactly 2,756 triangles. The composite enumeration is bounded by
the tool's top-48 change lists and the requested 64 outputs, so it is not exhaustive.

## Whole-cut proxy result

The main cut reports 2,756/5,010 triangles and a worst projected error of 12.4154 px.
For each exported candidate, the cut was reconstructed from the recorded split/merge
IDs and evaluated using the same node `accumulatedError`, sphere bounds, auto-frame
camera, and `screenSpaceErrorForSphere` formula used by the tool. The source mesh bounds
were read from the OBJ to reconstruct the camera; the recomputed baseline is 12.415384 px,
matching the report's rounded 12.4154 px.

| Exported candidate set | Count | Best worst-error proxy | Median | Worst |
|---|---:|---:|---:|---:|
| Single swaps | 3 | 17.6341 px | 17.6341 px | 17.6341 px |
| Composite reallocations | 64 | 20.2338 px | 20.9101 px | 25.9102 px |
| All exported | 67 | 17.6341 px | 20.9101 px | 25.9102 px |

None of the exported equal-face alternatives improves this proxy over the baseline. The
best is about 42% worse. The splits do reduce local projected error, but the paired merges
raise the maximum error elsewhere; the current candidate pool therefore shows no useful
same-budget trade for this metric on this asset.

## Decision and limits

Stop promoting the current group-8 Pirate repair pool. This is a negative screen of a
bounded set under a conservative geometric proxy. It does not prove that all possible
cuts are worse, does not measure shaded or filtered image error, does not compare policies
at matched total construction time, and says nothing about held-out assets. Reopen only
with a candidate-generating method that improves a frozen, quality-valid full-cut metric
against current DAG, blind group-size retry, and an offline upper bound across multiple
assets. If even the offline upper bound has negligible gain, close hierarchy repair.

The terminal reported 2.98 s total for this run, including the normal DAG build and
candidate exports. The older baseline run reported 2.91 s; this single-run difference is
not a timing conclusion. The run did not create a separate stdout log. Artifact hashes
and candidate rows are retained in `out/target-budget-oracle-20261116/pirate-g8/`. Recompute
the proxy table with:

```powershell
python -I tools/mmgeo/analyze_budget_oracle_screen.py `
  out/target-budget-oracle-20261116/pirate-g8
```

## Exact single-parent cut optimum

I independently enumerated every distinct projected node-error threshold in the frozen group-8
graph. For each threshold, the cut descends only at nodes whose error exceeds it. Because every
parent has fewer triangles than its direct children combined, this gives the minimum-triangle
legal cut at that threshold; the smallest feasible threshold is therefore the exact minimax
projected-error optimum over all cuts of this saved single-parent forest.

At the 2,756-triangle budget, the optimum is **12.4153843 px**, exactly the stored 44-node cut.
The validator checked all 184 nodes are reachable in a single-parent forest and that triangle
counts strictly increase when each parent is replaced by its children. All 99 distinct node-error
thresholds were enumerated; 8 fit the budget. The worst selected node is 183 (130 triangles,
12.4153843 px). The stored hierarchy selector therefore already attains the exact tree-cut
optimum for this geometric proxy. Equal-budget reallocation within this same tree cannot improve
that objective; improvement requires a new hierarchy candidate, a different error objective, or
rendered-image evidence.

This is still one asset and a projected sphere-error proxy, with no shading or image-distortion
measurement. It does not upper-bound a richer multi-parent hierarchy such as HPG DAG2, and it does
not prove that an image-space oracle would choose the same cut.

Reproduce the enumeration with:

```powershell
python -I tools/mmgeo/analyze_tree_cut_optimum.py
```

The machine-readable result is `out/target-budget-oracle-20261116/pirate-g8/tree_cut_optimum.json`.
Analysis script SHA-256: `c3b3fdb78ba30b07b5315706a0039a36a84fe8d09c876f71f3e414c4801b5e36`.
Result SHA-256: `614c05575276db7e2cb7d38d01439236522158799542e2f3263f32aceab3684b`.
The input graph hash matches the earlier oracle manifest; source, executable, and asset hashes are
also embedded in the result JSON.
