# Quality-gate witness partitioning: novelty screen (2026-11-17)

## Question

Can a failed DAG parent merge be repartitioned using the local witnesses that caused its strict topology, geometry, or attribute gate to fail, instead of bisecting every rejected group along its longest spatial axis?

This is a bounded hypothesis screen. It is not a novelty claim or a SIGGRAPH result.

## Repository evidence

- `libs/manymesh/src/LodGraph.cpp` currently splits a rejected multi-child group at the median of the longest spatial axis and retries both halves, up to two split levels. The retry is triggered by rejection of the whole group; the split rule does not use the rejection category.
- The diagnostic ledger stores group-level counts for topology, geometry, attributes, boundary, and locked failures. The existing diagnostics do not identify the particular collapse, triangle, corner, or child patch that witnessed each failed gate.
- Archived diagnostics under `out/regroup-diagnostics-cache-fix/` are bound to executable SHA-256 `13df2f63bfab914493840f45a7c55a2e51d27c4f80a5047c152178e3144c03ea` and source commit `edb6ecc7a16e3a68b7b0be80a1317e8e21dd6f16`, not the current workspace source. In the archived Pirate trial-0 rows, 114 of 152 groups were not promoted. Their overlapping rejection counters include topology on 35 groups, geometry on 25, attributes on 49, and locked constraints on 4. These are descriptive old-build counts: categories overlap, and they do not localize a witness or measure the current split policy.
- The archived Pirate regroup diagnostic has 48 local trials and 0 qualifying improvements. The other archived assets have no repartition trials in this diagnostic set; synthetic controls are not whole-cut evidence. None establishes a whole-build, held-out frontier gain from witness-directed splitting.

## Prior-art boundary

- The public [meshoptimizer `clusterlod.h`](https://github.com/zeux/meshoptimizer/blob/master/demo/clusterlod.h) already provides permissive and sloppy simplification fallback when a cluster does not reach its target. This is not the same as preserving ManyMesh's strict gates, but it occupies the broad idea of responding to a stuck cluster with an alternate simplification path.
- [Construction of clustered HLOD with As-Simplified-As-Possible boundaries](https://doi.org/10.1111/cgf.70380) builds crack-free clustered hierarchies with progressive internal and boundary portions. Boundary relaxation and generic cluster repair are therefore not safe novelty claims.
- [Simplifying Triangle Meshes in the Wild](https://doi.org/10.1145/3763277) addresses non-manifold, multi-component textured inputs using a simplicial-complex formulation and texture transfer. A contribution cannot be framed as generic robustness or attribute-aware simplification.
- Multi-Triangulation and DAG2 already cover valid mesh fragments/cuts and shared-child alternatives. Repartitioning or storing more parent choices alone is not a distinction.

The search used combinations of `mesh simplification`, `cluster partition`, `quality-gate failure`, `topology constraint`, `failure-driven`, and `counterexample-guided refinement`, prioritizing papers and public source. It did not surface a direct source for the exact combination “per-collapse gate witnesses choose a balanced parent repartition under a fixed total construction budget.” This is a narrow search result, not evidence that no such work exists. Patent, dissertation, and implementation searches are not complete.

## Candidate mechanism and decisive gate

A possible mechanism is a **gate-witness conflict graph**: map failed collapse witnesses back to child patches and their shared boundary, then choose a balanced split that separates incompatible witnesses while minimizing new boundary/locked cost. The split must be evaluated by rebuilding both children through the same strict gates. Its output is useful only if it expands the complete valid cut frontier, not merely if an individual half simplifies further.

Before changing production code, compare on frozen groups:

1. Current longest-axis median split.
2. Deterministic balanced random and connectivity-based splits.
3. Witness-graph split, with all witness extraction and search work charged.

Match total simplifier input-triangle work, wall time, and peak memory. Validate exact leaf coverage, triangle budgets, boundary signatures, topology and attribute gates, then measure complete-cut quality over held-out views and assets. Include the current hierarchy and a finite-pool offline upper bound. Stop this candidate if witness splits do not beat the median and simple baselines at matched total cost, or if any gain requires relaxing a gate.

No production C++ changed and no software tests were run in this screen. A fresh current-head diagnostic capture was not available: the configured WSL distro could not mount its `ext4.vhdx` (`ERROR_PATH_NOT_FOUND`), and the existing Windows binary is subject to the previously recorded application-control rejection. The candidate is not SIGGRAPH-ready; novelty and benefit remain unproven.

## Current-build correction and follow-up (2026-11-17)

The preceding availability statement is superseded. The Windows executable at `out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe` runs successfully. Its SHA-256 is `46B5AB1FE0CBF2AB9C2E1EB900FD94DFB7DF08665EDDCE955118849E96774900`; workspace `HEAD` is `6836c6e484b19010cfce7d413429141020f169bc`, with local edits in the relevant C++ files, so the binary is recorded by hash rather than claimed to be a clean commit build.

On Shapes (73,728 input triangles, target ratio 0.55), group sizes 8 and 16 both reached 40,550 triangles. The g8 build produced 1,690 nodes, 9 levels and 4 roots; 115 of its 126 initial groups were promoted before recursive retries. The g16 build produced 1,642 nodes, 9 levels and 4 roots; 67 of 69 initial groups were promoted. Rejection counters overlap, so they are not independent causes.

The read-only regroup screen on g8 used 198,064 of its 200,000 input-triangle work budget, took 55.84 seconds in recorded trials, and evaluated 136 adjacent-group member moves/swaps. Seven passed its joint predicate: manifold output, exactly preserved assembled boundary, non-increasing accumulated error, and fewer assembled triangles. Their individual reductions were 10, 12, 6, 24, 16, 6 and 20 triangles. These are mutually separate local trials, not a composable 94-triangle whole-cut gain. The full diagnostic build took about 69.3 seconds versus 10.35 seconds for the no-trial g8 build. This is weak evidence of occasional local partition headroom at roughly 6.7x build time; it does not evaluate witness-directed splits or held-out cut quality.

A `--quality-debug 1` Torus DAG run (1,152 input triangles, group size 4, target ratio 0.5) confirms that existing logs can report rejection masks, gate metrics, worst normal/UV vertex and triangle indices, plus world positions for locked-edge failures. They do not identify the offending collapse or boundary edge for ordinary topology/boundary rejection, nor connect a worst attribute sample to a parent-child partition decision. This is not a ready-made witness extractor.

The current-build evidence lowers priority for this candidate. Generic “retry failed merges by splitting” is already occupied by DAG2; adaptive boundary simplification is covered by HLOD ASAP; and the current public meshoptimizer `clusterlod.h` config enables permissive and sloppy fallback. A defensible next experiment would need to show, against these matched baselines and simple partition controls, that a specific extracted witness expands the **complete** strict-gate-valid cut frontier at equal total build work, wall time and memory on held-out assets. The current regroup result does not meet that gate. Do not implement a production witness partitioner on this evidence alone.

No production C++ changed and no software tests were run. This candidate remains an unproven, low-priority research question; it is neither a novelty claim nor a SIGGRAPH-level result.

## Cloth diagnostic extension (2026-11-18)

Ran one additional asset with the same strict-gate regroup screen: Cloth, DAG mode, 5 levels, ratio
0.7, group size 8, corner seam enabled, quality gate enabled, one build thread, and a 200,000
input-triangle trial budget. The input OBJ has 41,643 polygon records and Assimp loads it as 74,976
triangles. The run built 2,054 nodes / 10 levels in 112.09 seconds; 278 baseline groups included 150
rejections. The diagnostic considered 75 local alternatives spanning baseline regions of 818 to
5,572 triangles, consumed 197,588 input triangles and 32.54 trial seconds, and found **zero** that
simultaneously preserved the exact boundary, avoided non-manifold edges, did not increase maximum
accumulated error, and reduced triangle count. This is a real negative screen with eligible trials,
unlike the zero-trial Sphere and Monkey outcomes; it further weakens the witness-partition hypothesis
outside Shapes. It still does not evaluate the complete-cut frontier or prove that no alternative
split policy can help.

The ledger's failure counters also show why a gate-name-only split rule is not yet justified. Across
the 278 baseline groups, topology was rejected in 230 groups and attributes in 227; locked rejection
occurred in 79 and geometry rejection in 7. These categories overlap, and the summed per-attempt
counts (935 topology, 1,332 attributes, 92 locked, 7 geometry) are not independent causes or local
elements to split on. The diagnostic therefore does not tell us which child patch or boundary
conflict a new partition should separate.

An additional `--quality-debug 1` pass does expose the exact failed gate mask and worst sampled
normal/UV vertex/triangle for each rejected simplifier candidate. The matched ledger separates
2,366 rejected attempts in production groups from 1,214 in the diagnostic trial groups (the latter
spent 32.67 seconds, close to the non-debug run's 32.54 seconds). Production-group masks were:
attribute-only 1,315; topology-only 556; topology+geometry 320; locked-only 92; and other combined
masks 83. Trial-group masks were: attribute-only 625; topology-only 278; topology+geometry 213;
topology+boundary 52; locked-only 46. These sums reconcile to 3,580 parent-group rejects; the full
debug log has 4,076 rejected-candidate records because it also includes 496 cluster-stage rejects.
This sharpens gate attribution, but the log still omits parent/group and child-region identifiers, and
its worst-attribute indices are candidate-local. It cannot yet tell which spatial split separates
the failed witness. The UTF-16 PowerShell capture is ignored under `out/` at
`out/quality-witness-current/cloth-regroup-pilot-200k-debug/quality-debug.log`; the corresponding
ledger is `diagnostics.json`. No production code was modified.

Tried a read-only join by dropping the 496 cluster-stage records, then consuming each group's
expected rejection-mask histogram from the remaining debug records in ledger array order. Only
65/428 observations matched their complete mask histogram. Although the total number of records
reconciles, the ordering assumption is false (or the logs aggregate candidates differently), so this
does not provide a safe group join. A trustworthy attribution needs an explicit group/region ID
carried through the simplifier call and written beside each rejection record.

Reproduction command:

```powershell
$env:MANYMESH_BUILD_THREADS='1'
& out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe --mode dag --levels 5 --ratio 0.7 --dag-group 8 --corner-seam 1 --quality-gate 1 --dump-obj 0 --write-dag 0 --out out/quality-witness-current/cloth-regroup-pilot-200k --dag-diagnostics out/quality-witness-current/cloth-regroup-pilot-200k/diagnostics.json --dag-diagnostic-work 200000 assets/models/cloth/cloth.obj
```

The ledger is `out/quality-witness-current/cloth-regroup-pilot-200k/diagnostics.json` (SHA256
`5f0d31c64f1cbb400a93d404d89cc7664dd7a9e30162c9063fe9c820ebfa3326`); input OBJ SHA256 is
`3dbcb96aaf5142ee16922c6138e23fa8dd8471e847c58978fd09df596168c24f`, and executable SHA256 is
`46b5ab1fe0cbf2ab9c2e1eb900fd94dfb7df08665eddce955118849e96774900`. Workspace HEAD at capture
was `422c7e50c4c802f88788dbf27e6d01273dc343ec`; no C++ source changed and no software tests were
run. The existing in-process working set was about 54 MiB and system available memory stayed near
5.9 GiB; no build was started.

**Decision update:** close the current fixed adjacent-group move/swap witness screen as a candidate
generator: Shapes has seven non-composable local wins, while Cloth has zero across 75 trials and
Material Sphere / Monkey had no eligible trials. Reopening requires a different, explicitly
specified split-generation mechanism and a complete strict-gate-valid cut comparison at matched
work; merely collecting more local counters is not enough. SIGGRAPH contribution remains
unestablished.

## Group-bound rejection record instrumentation (2026-11-18)

Added diagnostic-only `SimplifyRejectObservation` records. The simplifier captures source/target/
candidate index counts, retry number, five-bit rejection mask, worst normal/UV vertex and triangle
indices, and maximum normal/UV errors for each rejected *simplified* candidate. The record vector is
merged through the existing per-worker profile reduction, then serialized as `rejectionDetails`
nested in the same group object that carries the child node IDs and level. The vector is populated
only when the existing DAG diagnostic mask histogram is enabled, so ordinary simplification does
not allocate per-rejection records or change acceptance decisions. Diagnostics JSON schema is now 2.

The `mmgeo` Release target compiled successfully from current source in `out/cmake-vulkan` (0
errors; 2 existing MSVC warnings for ignored `-fno-rtti` and `-Wl,--gc-sections`; build about 6 s).
Executable SHA256: `b70ef5872f5bee1c303fd47d16394507e5998799fff5606eecd3adb6ad95ffc6`. Available RAM
was about 5.4 GiB after compilation. Runtime validation could not run: Windows Application Control
blocked the newly linked `mmgeo.exe` before process start, so no schema-2 ledger was emitted. No
software test suite was run. This is compile-verified instrumentation, **not yet runtime-verified**;
the next evidence gate is executing it in an allowed environment and checking that each group's
rejection-detail count equals its mask histogram and that the saved vertex IDs occur in the group's
children/input index set. No witness-guided partition result or SIGGRAPH contribution is established.

The execution-policy failure was confirmed from the local Code Integrity event log: event IDs 3033
and 3077 report that the image did not meet the enterprise signing-level policy, and
`Get-AuthenticodeSignature` reports `NotSigned` for this locally linked executable. WSL fallback
also failed before launch: both `wsl --list --verbose` and the `ubuntu-bmc` probe returned
`Wsl/Service/E_ACCESSDENIED`. No policy, signing, or execution-control changes were attempted. The
instrumentation therefore remains compile-verified only until an administrator-approved signed or
otherwise allowed build environment is available.

## Matched cross-asset regroup screen (2026-11-17)

To check whether the local headroom repeats, I matched the graph and gate parameters used by `regroup_diagnostics.py` on Shapes, Material Sphere, and Monkey, with one build thread and a 200,000 input-triangle diagnostic budget (the helper's default budget is 50,000; 200,000 matches the preceding Shapes screen): DAG mode, 5 levels, ratio 0.7, group size 8, corner seam simplification and the strict quality gate enabled. The current `mmgeo.exe` hash is recorded above. This is a read-only diagnostic; no trial parent is committed to the hierarchy.

| Asset | Input triangles | Baseline groups | Failed groups | Eligible trials | Qualifying improvements |
|---|---:|---:|---:|---:|---:|
| Shapes | 73,728 | 147 | 32 | 136 | 7 |
| Material Sphere | 9,428 | 35 | 16 | 0 | 0 |
| Monkey | 15,744 | 41 | 1 | 0 | 0 |

Shapes consumed 198,064 input triangles in 20.79 seconds of trial work (42.95 seconds for the full build). All seven qualifying trials were at level 4 and mapped to only three distinct unions of adjacent child groups; five were alternate swaps within one same pair. The per-trial triangle reductions were 10, 12, 6, 24, 16, 6 and 20. They remain isolated counterfactuals and cannot be added into a cut-level gain.

Material Sphere and Monkey had zero eligible trials and consumed zero trial triangles. They are **no-sample outcomes**, not evidence of zero gain: this diagnostic's adjacency/material/submesh/size filters found no pair to probe on either run. The only positive local signal still comes from three group pairs on one development asset. It does not generalize yet and does not justify implementing witness-directed partitioning.

Reproduction outputs are under `out/quality-witness-current/{shapes,material-sphere,monkey}-regroup-pilot-200k/` (each contains the ledger and run log). The exact configuration is in `tools/mmgeo/regroup_diagnostics.py`; the single-asset commands use the same flags and a 200,000 budget. No production C++ changed and no software tests were run.
