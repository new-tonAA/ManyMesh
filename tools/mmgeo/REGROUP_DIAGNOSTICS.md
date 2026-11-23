# Constraint-driven regrouping: first diagnostic delivery

The hypothesis remains unvalidated. Keep regrouping in the diagnostic phase.
Rejection counts alone do not establish that boundaries block simplification.
The tools provide inspectable candidates and local screens; they establish neither
cross-asset improvements nor a paper contribution.

## Implementation

- `LodGraphOptions::diagnostics` is disabled by default. When enabled it records
  each merged-parent build and every existing spatial bisection retry, including
  failures: members, complete input triangles, explicit lock masks, input/actual
  output face counts, accumulated error, and rejection counts per quality gate.
  `lockedVertices` excludes locks inferred implicitly by `lockBorder`.
- Screen adjacent groups sharing an exact welded edge, with matching material
  and submesh and at least one failed original build. Regions have at most 16 frontier
  nodes. Each group enters at most one region per level; each region has at most 16
  moves/swaps in fixed order. An input-triangle budget limits extra build work.
- Trials use existing simplifiers and gates; generated vertices/indices stay local
  and are never committed. The baseline retains successful parents, spatial retries,
  and remaining nodes; failed candidates retain their original nodes.
- Resolve generated vertices independently and deduplicate exact positions before
  counting faces. Mark `improves` only when regional boundary edges match, no edge
  is non-manifold, maximum accumulated error does not increase, and face count
  strictly decreases. Ties retain baseline. This is a local screen, not a whole-tree
  gain or a causal explanation.
- Detailed records are not serialized. Runtime selection, single-parent structure,
  and default build behavior remain unchanged.

## Reproduction

Use a freshly compiled mmgeo:

```powershell
python tools/mmgeo/regroup_diagnostics.py --mmgeo out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe
```

The script generates smooth-surface, thin-sheet, crease, and UV-seam controls, then
uses existing Pirate, Monkey, and Torus development assets. Settings are five
levels, ratio 0.7, eight nodes per group, Corner simplification and quality gates
enabled, otherwise tool defaults. Extra work is capped at 50,000 input triangles
per asset. One-thread and four-thread runs compare every ledger/trial field except
timings. Full JSON, logs, and `summary.json` go to `out/regroup-diagnostics/`.
These real assets are development data, not an unseen test set.

Record a ledger without counterfactual trials with:

```powershell
mmgeo --mode dag --dag-diagnostics ledger.json --dag-diagnostic-work 0 model.obj
```

Budget counts both groups' input triangles per candidate, excluding internal
backoff retries. Report `attempts` and measured time as well. The budget does not
guarantee a factor-of-two wall-time cap.

## Historical verification

- Header formatting ran; its existing namespace safety check skipped mmgeo.
- Visual Studio Release built `test_manymesh`, `mmgeo`, and `test_utils`, with
  existing unsupported `-fno-rtti` and `/Wl,--gc-sections` warnings.
- New isolation, budget, and repeatability tests initially passed on Windows.
  After stronger nonempty-trial assertions, Windows application control blocked
  rebuilt tests and mmgeo; utils was also blocked outside the sandbox.
- An independent WSL CMake entry reused math, meshoptimizer, gtest, and manymesh
  without CivetWeb: 82 ManyMesh tests passed, one HTTP test skipped. This included
  new tests and serial/parallel determinism, assembly, and topology tests.
- `./build.sh -ip desktop debug` was attempted. WSL had only GNU compilers, which
  default configuration rejected. Full desktop Debug and utils execution did not pass.
- Python syntax checks passed. At this stage Windows policy prevented mmgeo runs,
  so control and real-asset experiment results were unavailable.

## Missing causal evidence

1. Unit-level gates do not identify individual rejected collapses or their causes.
   Single-cluster chains retain aggregate profiles. Topology, lock, and boundary
   rejections cannot simply be labeled grouping blockage.
2. Trials reuse current locks. Equal output boundaries are only a screen; frontier
   versus original-leaf usage counts and generated-position lock coverage need audit.
3. Initially no exhaustive legal-cut or globally optimal assembled-cut comparison
   existed, so selector effects could not be excluded.
4. No verified repair opportunity on three development assets and two structure
   types had passed the algorithm entry gate.

Finish diagnostics before submitting winning groups. Equal-work random/boundary
heuristics, three quality levels, at least twelve unseen assets, a million-face
case, and multiple-light visual checks belong after that gate; no such gains exist.

## Subsequent cache and cut audit

- Multilevel Corner determinism tests exposed stale quality-gate mesh snapshots:
  group builds append attributes to `graphMesh` between levels while snapshots
  used one shared `meshCacheEpoch`. Each level now uses a new epoch. Tests assert
  at least two snapshot copies and retain serial/parallel field comparisons.
- After the fix, all seven cases (four procedural controls, Pirate, Monkey, Torus)
  produced identical single/four-thread candidates and statistics. Pirate had 48
  local trials and zero improvements; candidates had more faces than baseline.
  Monkey had one failed group and no candidate; the sheet had no failed groups.
  This correction establishes consistency, not improved grouping.
- `audit_lod_cuts.py` reads MMLG v7, counts legal cuts (a lower bound above the cap),
  and exhaustively counts deduplicated assembled faces when feasible. The 800-face
  smooth control had 974 cuts; its minimum matched the root cut. Pirate exceeded
  10,000 cuts and was not exhausted, so global optimality remains unknown.
- These audits produced no reproducible candidate gain and did not enable production
  regrouping. The small-mesh auditor changes neither building nor runtime behavior.
