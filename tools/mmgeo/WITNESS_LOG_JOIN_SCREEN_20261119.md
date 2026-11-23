# Recovered quality-gate witnesses from legacy logs (2026-11-19)

## Why this audit exists

The newer schema-2 `rejectionDetails` instrumentation compiled, but the locally linked `mmgeo.exe`
was rejected by Windows Application Control before it could emit a runtime capture. The old Cloth
debug run still has a schema-1 diagnostics ledger and verbose candidate log. A previous attempt
joined those records by array order and failed. This audit uses source index count plus exact reject
mask histograms instead, and only assigns individual records when their mask is unambiguous within
that source-size cohort.

## Join and child attribution

The log has 4,076 verbose rejection records. Of the 197 source-size cohorts present in the
trial-zero diagnostics groups, 101 have an aggregate 32-bin rejection-mask histogram that exactly
matches the log. Within those verified cohorts, a record is assigned to a group only if that mask
occurs in exactly one group. This conservatively assigns 758 records to 66 groups: 65 have a full
per-group histogram match and one has only partial attribution. Four additional unique-source
groups have no rejected candidates. The 66 groups comprise 64 rejected and 2 promoted groups.

For each matched group, child ownership is reconstructed from a source-level invariant in
`LodGraph.cpp`: the input index buffer is the concatenation of child-node index arrays in `members`
order. The graph JSON records each member's triangle count, so the index buffer can be sliced into
per-child ranges. The script checks that the slices cover the group input exactly. All 892 recorded
normal/UV witness indices in the assigned records occur in the group input; 740 map to one child and
152 lie on vertices shared by multiple child nodes.

Restricting to the 421 assigned rejects whose mask includes the attribute gate, the serialized
metrics and the implementation thresholds attribute every one to **normal error only**. The gate
checks max normal error (35 degrees), mean normal error (17.5 degrees), mean UV error (0.10), and
max UV error (0.80); none of these candidates exceeds either UV threshold. Therefore the logged
worst-UV vertex is not a causal witness for these failures. A normal/UV cross-child conflict graph
would be false evidence and was discarded. The causal worst-normal vertex maps to one child in 328
records and to a shared child-boundary vertex in 93. Across the 63 matched groups with such
witnesses, the most implicated child accounts for a mean 76.2% of unique-normal-witness counts
(median 75.0%); 62/63 groups put at least half their counts on one child. This concentration still
does not show that isolating that child produces a better simplification.

As a retrospective check, 40 matched groups have exactly one complementary pair of recorded
same-level groups covering their member set. Pairing is inferred from member sets; the ledger has
no explicit split-parent pointer. For each pair, I asked whether the half containing the dominant
normal-witness child promoted. It promoted in 14/40 cases; the other half promoted in 11/40; both
promoted in 4 and neither in 19. Thus the dominant normal witness does not predict which half
succeeds under the recorded spatial splits. This is one asset, with no held-out partition trials.

## Decision

The recovered records make future schema-2 child attribution auditable, but the single-child
isolation signal does not pass even this preliminary test. The apparent cross-child normal/UV
conflict signal disappeared after checking which gate metric actually exceeded its threshold.
Retire witness-directed partitioning on this evidence; do not implement it or claim a contribution.
Reopen only if a separately justified witness type both predicts strict-gate repair outcomes on
held-out assets and improves the complete cut frontier at matched work, time, and memory. Runtime
schema-2 output remains unverified.

The search also surfaced the arXiv record [2507.15186](https://arxiv.org/abs/2507.15186), which is a
recent repository record for Brodsky and Watson's 2000 paper *Model Simplification Through
Refinement*, not a newly proposed 2025 algorithm. That paper already describes time-bounded
interactive simplification, size control, and later refinement of intermediate outputs; these
broad anytime-simplification claims are prior art ([Graphics Interface 2000 paper](https://graphicsinterface.org/wp-content/uploads/gi2000-29.pdf)).

Reproduce the conservative join with:

```powershell
python tools/mmgeo/audit_quality_reject_log_join.py `
  out/quality-witness-current/cloth-regroup-pilot-200k-debug/diagnostics.json `
  out/quality-witness-current/cloth-regroup-pilot-200k-debug/lod_graph.json `
  out/quality-witness-current/cloth-regroup-pilot-200k-debug/quality-debug.log `
  --out out/quality-witness-log-join/cloth.json
```

The parser is [audit_quality_reject_log_join.py](audit_quality_reject_log_join.py); the JSON output
is ignored under `out/`. Provenance hashes (SHA-256): diagnostics
`f2bc5855e0b565ceebbd59717eaf52ea8614d5606f7b87c6fd8a4a9a184e34de`, graph
`f018718ba6cb166e4b056def3ee7ac2c42da6f6e7a13863e5785ba515e004607`, verbose log
`f0cc573c2ff9632ec8828e8508fb3535a3bb1c872a008ca3f32284a9ae337740`, parser
`eb8ae2227b6f786f0c6e8f802f2f51a5fedcccec3a102ca4e4d87c83e21f0d11`. The underlying debug
capture is the one bound in the parent screen to workspace HEAD
`422c7e50c4c802f88788dbf27e6d01273dc343ec` and executable SHA-256
`46b5ab1fe0cbf2ab9c2e1eb900fd94dfb7df08665eddce955118849e96774900`. No build, renderer, or
software test was run in this audit.
