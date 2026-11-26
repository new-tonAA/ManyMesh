# Multi-cut cluster-DAG projective-fit preflight protocol

Status: frozen one-asset development screen. It tests whether one shared set
of MMLG vertex positions can be optimized jointly across three legal cuts and
improve their source-relative images over separately fitted exact-face
meshoptimizer controls. This is a feasibility experiment, not an asset-held-out
result, novelty claim, or final-AA/upscaler evaluation.

## Question and rejection rule

Can a single shared position field for three cuts of one triangle-mesh cluster
DAG, optimized jointly across their screen scales with the existing CPU
projective-RGB fitter, improve each cut against a separately fitted
meshoptimizer control at the exact same face count, while preserving every
cluster boundary and topology constraint?

Advance only if all three cuts accept at least one fit step, retain exact face
counts and source boundaries, preserve all locked boundary positions, remain
within 0.012 normalized displacement and the 0.20 face-normal dot-ratio floor,
and each cut's held-out mean LDR-FLIP is lower than both the raw and fitted
strongest eligible control. Each cut must also remain within 0.10 dB pooled
PSNR and 0.001 mean SSIM of its fitted control. Meshoptimizer LockBorder is the
primary control. If it fails the strict topology/boundary audit, record the
failure before scoring and use exact-face boundary-preserving QEM as the
predeclared fallback for that budget only. Do not score an ineligible control.
If neither control is eligible at a cut, stop before image scoring and close
the three-cut screen as infeasible. Any failed quality/fit condition closes
this shared-position, three-cut configuration.

### Eligibility amendment, 2026-11-27 (before image scoring)

The 7,934-face meshoptimizer output contained duplicate geometric triangles
and failed the topology audit. No image metrics had been computed. A
topology-only exact-face QEM check at 7,934 faces preserved the source boundary
and passed the same audit. Therefore the protocol's already-specified
pre-scoring eligibility rule is instantiated as follows: use meshoptimizer at
2,286 and 5,290 faces if it passes its audit; use QEM at 7,934 faces because
meshoptimizer is ineligible there. Preserve the rejected meshoptimizer audit
in the receipt. No baseline is selected by image quality.

## Asset, split, and cuts

- Thingi10K file 84736 (Thingiverse item 28675), 10,580-face source OBJ,
  train split, Creative Commons Attribution. This is the reused development
  asset in the single-cut preflight, not confirmation data.
- Source OBJ SHA-256:
  `b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`.
- Use the D-drive WSL `mmgeo` built from source revision
  `21cef5a92739edd6d1d751417a2c20efe4ec2a2d`, binary SHA-256
  `a4b4fd300237ea43787f1c7c04fca82e308e0fd7c0963546840a4e03a52e7a22`.
  Keep DAG construction options fixed: ratio 0.7, cluster vertices/triangles
  128/128, DAG group 8, attribute QEM and corner seam/split enabled, MMLG v7.
- Requested ratios are 0.25, 0.50 and 0.75. The prior output headers show
  2,286, 5,290 and 7,934 actual faces respectively. These actual cuts, not the
  requested ratios, define the exact meshoptimizer face budgets. A candidate
  must pass the strict source-boundary and topology audit before rendering.
- Reconstruct the selected node labels from each ratio-specific graph JSON and
  MMLG v7. Map source positions only through the validated full-detail PLY and
  generated positions through their MMLG records. Score against the original
  OBJ, never against the DAG full-detail cut.

## Optimization and controls

- Extend the existing CPU Mitsuba `llvm_ad_rgb` projective-RGB path. Fit one
  position array indexed by the union of MMLG global vertex IDs in the three
  cuts, so any position shared between cuts is represented by one variable.
  The training objective is the equal mean of the existing 16 view/scale
  losses over all three cuts. For each cut, lock all vertices shared by
  different selected nodes, plus any open-boundary vertices. Use the existing
  Laplacian preconditioner, eight-iteration cap, 0.002 maximum step and 0.012
  displacement cap. Reject a step if it violates the minimum face-normal dot
  ratio of 0.20 in any of the three cuts.
- For each actual face budget, construct an exact-face meshoptimizer LockBorder
  control from the original source and fit it independently with the same CPU
  optimizer, training views, iteration cap, step cap, normal floor and
  displacement cap. Raw ManyMesh and raw meshoptimizer geometries are controls.
  Meshoptimizer is the primary baseline because it was the strongest
  deterministic geometry control in the existing 21-model screen. This screen
  does not include QEM and is not an exhaustive geometry comparison.
- Render the original source OBJ as the reference. Use the existing fixed
  camera, neutral material, light, background, transfer function and random
  seeds. Training uses 96 x 96 renders at 4 spp; scoring uses 24 reserved
  direction/scale pairs at 16 spp. The sample pattern is an offline
  antialiasing proxy only, not hardware MSAA, SMAA, temporal accumulation or an
  upscaler.
- Report per-cut and pooled PSNR, SSIM and LDR-FLIP, every per-view score,
  sampled surface distance and normal agreement, topology/boundary failures,
  lock counts, face counts, optimizer time, total joint time, peak RSS, and
  output geometry bytes. Views are correlated; do not treat them as independent
  assets or report asset-level confidence intervals.

## Prior-art scope and limitations

Differentiable mesh fitting and image-guided simplification are established
work. The only scoped question here is whether sharing optimization variables
across legal cuts of an existing authored triangle-mesh DAG changes the
quality-cost tradeoff against separately fitted fixed-LOD controls. This
single-asset preflight cannot establish novelty or generalization. It does not
test temporal transitions, final hardware reconstruction, mobile performance,
user preference, complete compressed payloads, or self-intersections. Relevant
overlap and papers are tracked in
[`SIGGRAPH_2027_DIRECTION.md`](../../SIGGRAPH_2027_DIRECTION.md) and the
[prior-art screen](../../docs/manymesh/siggraph-prior-art-screen-20261123.md).

## Reproduction

Use the existing D-drive WSL CPU environment; do not install packages or
change Windows security policy. Save raw JSON, generated DAG inputs and fitted
geometry under an ignored output directory. Record commands, all input/output
hashes, package versions, hardware, selected node IDs, exact fit traces, per-cut
results and the frozen decision. The prior single-cut result is closed and is
not reused as a score for this experiment.
