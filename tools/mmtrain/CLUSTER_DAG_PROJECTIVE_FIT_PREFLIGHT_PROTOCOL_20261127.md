# Cluster DAG projective fitting preflight protocol

Status: frozen single-asset development screen. It tests whether a 50% ManyMesh
cut can be reconstructed with its MMLG node labels and fitted while shared
cluster boundaries remain fixed. It is not an asset-held-out result, a final
MSAA/upscaler experiment, or a novelty claim.

## Question and rejection rule

At an exact 5,290-face budget, does CPU projective RGB fitting of a ManyMesh cut
with every shared cluster-boundary vertex locked improve held-out-view image
quality over (a) the same cut without cluster-boundary locks and (b) an exact
face-count meshoptimizer cut fitted with the same optimizer? The fitted
meshoptimizer cut is the primary comparator in this screen. The inputs are
matched by face count; CPU fit time and peak RSS are reported separately. Also
record raw float32-position/uint32-index buffer bytes (excluding attributes and
container headers) and the compressed experiment-archive size. These are not
network or `.mmb` payload measurements. A QEM arm is not included, so this is
not an exhaustive geometry-baseline comparison.

Advance only to a separately frozen multi-asset study if the cluster-locked fit
accepts at least one step, preserves exact face count and topology, leaves all
locked vertices unchanged, stays within the 0.012 normalized displacement cap,
and has lower mean held-out LDR-FLIP than both raw and fitted meshoptimizer
controls. It must also remain within 0.10 dB pooled PSNR and 0.001 mean SSIM of
the fitted meshoptimizer control. Otherwise close this exact configuration.
The unclustered ManyMesh fit is an ablation and is reported regardless of the
gate.

## Asset, split, and frozen inputs

- Thingi10K file 84736 (Thingiverse item 28675), 10,580 source faces, train
  split, Creative Commons Attribution. This is a reused development asset, not
  confirmation data. Source STL SHA-256:
  `4de846fb7c6ae5259655d89f2cf9c8ef021c234da02efd81df47efa0744a0da4`.
- Derived source OBJ SHA-256:
  `b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`.
- DAG generator source checkout: `21cef5a92739edd6d1d751417a2c20efe4ec2a2d`.
  No C++, header, or CMake source differs from the current Windows HEAD at the
  time this protocol was frozen. `mmgeo` SHA-256:
  `a4b4fd300237ea43787f1c7c04fca82e308e0fd7c0963546840a4e03a52e7a22`.
- Frozen DAG settings: ratio 0.7, 128 cluster vertices, 128 cluster triangles,
  DAG group 8, attribute QEM and corner seam/split enabled, MMLG v7. The graph
  has 246 nodes and 9 levels. The exact 50% selection contains 29 nodes and
  5,290 faces.
- MMLG SHA-256:
  `0412224b9846cadc5a25186a2e010fecea7d652de25f6c5891bc307c07ea51ed`.
  Candidate PLY SHA-256:
  `564561866e5eeba10b91000d41de69927bb06a8b084106eeff3506a6e4c4cb63`.
  Full-detail PLY SHA-256:
  `66590b37ddb1c268887290e7f3c1a4c1167a28cb208a54b85c219aad45f59402`.
  Candidate DAG JSON SHA-256:
  `ee248fe714ca5d4e776b01f8ceda035fb25b4f09ba70dca5c12da53e48f315fa`.
  Full-detail DAG JSON SHA-256:
  `81d5598802868b84e75e345d8a2c758a137e60a2aa51558bc1db1b1e5983b5e0`.

The PLY does not contain DAG node IDs. Reconstruct labels from MMLG v7 node
indices. Map source vertex IDs through the 100% cut, whose leaf-face order is
identical to the full-detail PLY face order; map generated vertices from their
MMLG records. Assign each selected MMLG node's triangles to the matching
selected-PLY faces by exact float32 position triples. Require a one-to-one
5,290-face match before fitting. Do not use the original OBJ's vertex order as
the MMLG source vertex order.

## Fit, controls, and scoring

- Use the original source OBJ (10,580 faces), loaded by the same Python source
  loader used by the existing CPU fit protocol, as the image and surface
  reference. Normalize all geometries with its center and radius. Keep faces
  fixed throughout fitting. The mmgeo full-detail PLY is only a vertex-ID
  mapping aid, never the scoring reference. Its 5,290 points map one-to-one to
  the source OBJ with maximum coordinate difference `4.2312e-6`; after that
  map, all 10,580 unoriented source face-index triples match exactly.
- Fit the ManyMesh cut twice: once with the 29-node shared-boundary lock mask,
  and once with only open-boundary locks. Fit the exact 5,290-face
  meshoptimizer LockBorder cut with only open-boundary locks. Include raw
  ManyMesh and raw meshoptimizer geometry as unoptimized controls.
- Use the existing `fit_projective_rgb_cpu.py` CPU path: Mitsuba 3.9.0,
  Dr.Jit 1.4.0 `llvm_ad_rgb`, two CPU threads, `direct_projective`, 96 x 96,
  neutral diffuse material, one directional light, constant background, 16
  fixed training camera/scale pairs, 4 spp, eight iterations maximum, maximum
  step 0.002, maximum displacement 0.012, and the existing fixed Laplacian
  preconditioner. Loss is unweighted full-frame linear-RGB MSE. The optimizer
  rejects steps that violate its face-normal orientation floor.
- Score the source, raw controls, and all fits on the same 24 reserved
  direction/scale pairs at 96 x 96 and 16 spp, with identical seeds and
  transfer function. Report each view and pooled PSNR, SSIM, and LDR-FLIP;
  also report sampled surface distance, normal agreement, exact face count,
  topology, source-boundary eligibility, cluster-boundary displacement, fit
  time, peak process RSS, and output bytes.
- This is a single reused asset. Views are paired but correlated; do not treat
  their count as independent assets or report an asset-level confidence
  interval. Do not report user preference, final MSAA/upscaler quality, mobile
  performance, GPU time, temporal stability, or geometric self-intersection
  results from this screen.

## Reproduction and interpretation

Use the local D-drive WSL2 CPU environment and save raw JSON plus fitted
geometry under an ignored output directory. Record the actual fit-script hash,
all output hashes, package versions, full command, raw per-view results, and
the lock-mask counts. The first diagnostic invocation used the full-detail
PLY as its renderer reference and is excluded from this protocol because it
did not use the pinned original source directly. Only a run using the source
OBJ above can decide whether this configuration is worth a separately frozen
asset-held-out study. It cannot establish that fitting all levels of the DAG
jointly is feasible: this preflight fits one selected cut and tests that cut's
cross-node boundaries.

Differentiable image-space geometry fitting is established prior art, including
Hasselgren et al. (EGSR 2021), LTM (CVPR 2024), and DiffSimp (arXiv 2026). A
boundary-locked cut fit is only a scoped implementation feasibility question;
cluster constraints alone are not a novelty claim. See the
[prior-art screen](../../docs/manymesh/siggraph-prior-art-screen-20261123.md)
and [SIGGRAPH direction](../../SIGGRAPH_2027_DIRECTION.md).
