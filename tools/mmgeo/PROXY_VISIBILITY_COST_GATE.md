# Proxy visibility: prior art and a finite image cost gate

Date: 2026-11-15. Research screen; no new estimator or SIGGRAPH contribution established.

## Direct prior art

[Billen, Lagae, and Dutre, EGSR 2014](https://graphics.cs.kuleuven.be/publications/BLD14PVEGP/BLD14PVEGP_paper.pdf)
already use approximate geometry and stochastic exact/correction queries for unbiased shadow
visibility. Sections 3 and 4 analyze variance and choose sampling probabilities, including
inside/outside proxies and a cost heuristic. Their general proxies include ordinary quadratic
edge collapse and clustering. Their experiments also show the central failure mode: tracing more
rays can still give worse equal-time error because added noise exceeds the benefit. Simple
geometry can already be cheap to query through its acceleration structure. This directly rules
out claiming generic unbiased coarse-mesh visibility correction or adaptive probabilities here.

[Silvennoinen et al., CGF 2014](https://doi.org/10.1111/cgf.12271) construct small polygonal
occluders preserving occlusion properties from triangle soups. Generic visibility-aware proxy
construction is also established. The publisher abstract was accessible; the full author PDF
exceeded the browsing tool's size limit, so this is not a complete method comparison.

[Yan et al., SIGGRAPH Asia 2024](https://kyan.ai/publication/diff_var_siga24_compressed.pdf)
differentiate rendering variance with respect to scene and sampling parameters. Their Section 5,
Equations 29 and 33--35, explicitly include predicted execution time multiplied by variance in
the optimization objective. This does not establish that they solved discrete unbiased geometric
proxy construction, but it does rule out calling the generic time-times-variance objective new.

[Neural Two-Level Monte Carlo Real-Time Rendering, CGF 2025](https://doi.org/10.1111/cgf.70050)
combines inexpensive cached estimates with an unbiased path-traced residual. Replacing the
surrogate by geometry still needs a specific new mechanism beyond ordinary residual estimation.

## The two targets must be separated

The frozen capture and QEM artifacts supply only geometry. We rasterize all 12 existing
orthographic views of Torus, Monkey, and Pirate, at 128x128 pixels and 3x3 subpixel samples.
The finite target for each pixel is its **box-filtered binary coverage**, the mean of its nine
fine-mesh coverage atoms. A hypothetical Monte Carlo sample chooses one of those atoms uniformly,
with replacement. Full enumeration supplies the reference; it is not a stochastic renderer timing.

For pixel j, let F_j(u) be fine occupancy and G_j(u) proxy occupancy at the same subpixel atom.
For an independent Bernoulli correction B with constant probability p, consider the established
estimator `Y_j=G_j+B/p*(F_j-G_j)`. This is unbiased for the fine coverage of every pixel. Values
can be negative or exceed one; clamping them would invalidate this statement. Define

```
V = mean_j Var_u(F_j(u))
q = mean_j E_u[(F_j(u)-G_j(u))^2] = fraction of disagreeing atoms
mean_j Var(Y_j) = V + q*(1/p - 1)
```

Views and pixels have equal weight. This V excludes variation between different pixels' means.
A fully covered or empty fine pixel has zero within-pixel variance, but an incorrect proxy can
still add correction noise there. This makes the coverage-image gate substantially stricter than
the separate scalar image-area integral gate. The area integral instead has
`V_area=mu*(1-mu)`, with mu pooled over all rays. It cannot substitute for an image MSE result.

Normalize the expected fine-query cost to one, and write `r=E[c_proxy]/E[c_fine]`. With constant p,
the expected cost is `r+p`, assuming additive query work and no overhead. The efficiency metric is

```
K(p) = (r+p) * (V + q*(1/p-1)),  0 < p <= 1
K_fine = V
```

This compares variance at equal **expected** work for fixed iid sample counts. It does not justify
randomly stopping at a deadline or replacing a deterministic/stratified sampling baseline by iid
sampling. Costs can depend on the ray; constant p still permits the averaged additive expression.
Adaptive p, GPU divergence, building a second acceleration structure, and probe overhead need
additional treatment.

For `0<q<V`, ordinary calculus gives `p*=min(1,sqrt(r*q/(V-q)))`. With `t=q/V`, strict gain over
direct fine queries is possible in this estimator family exactly when

```
r < (1-sqrt(t))/(1+sqrt(t)).
```

If `q>=V`, no positive r gives a strict gain for this constant-p family, even with oracle knowledge
of q. If q=0, the proxy is exact on this fully enumerated finite support, and p=0 is permissible
there; no such certificate is inferred for unseen rays. If V=0, direct fine sampling already has
zero variance. These are standard estimator algebra and optimization, not a novelty claim.

## Measurements

The authoritative result is `out/proxy-visibility-cost-gate-20261115-v2/report.json` (schema 2).
Its SHA-256 is `f89274307b319ea99600d09467d9db3828a7ff3c779eed31471e954e43ce7ea1`.
The earlier schema-1 report is area-integral-only and is superseded for any image-quality decision.
The script rerasterizes source and all nine existing QEM outputs, verifies all **108** disagreement
counts against the archived evaluation, and binds captures, manifests, mesh artifacts, raster
source, evaluator source, and its own source by SHA-256. Twelve fine views per asset are shared
among its three output levels. Original experiments and meshes are unchanged.

Limits below use mean coverage-image MSE over all pixels and the twelve views. Positive cost
ratios must be **strictly below** the limit; zero means no strict improvement is possible in this
family. The area-integral column deliberately shows how misleading the weaker target would be.

| Asset | Actual retained faces | q/V for image | Image cost-ratio limit | Area-integral limit | Mismatches in constant fine pixels |
|---|---:|---:|---:|---:|---:|
| Torus | 864 / 1152 (75.00%) | 0.1276 | 47.36% | 91.00% | 13.19% |
| Torus | 576 / 1152 (50.00%) | 0.4516 | 19.62% | 83.71% | 17.74% |
| Torus | 288 / 1152 (25.00%) | 1.7944 | 0 | 69.97% | 31.72% |
| Monkey | 11808 / 15744 (75.00%) | 0.0009 | 94.15% | 99.26% | 0 |
| Monkey | 7872 / 15744 (50.00%) | 0.0168 | 77.07% | 96.86% | 2.70% |
| Monkey | 3936 / 15744 (25.00%) | 0.1350 | 46.26% | 91.34% | 11.24% |
| Pirate | 3760 / 5010 (75.05%) | 0.1009 | 51.79% | 88.96% | 14.92% |
| Pirate | 2516 / 5010 (50.22%) | 0.4497 | 19.72% | 78.04% | 20.48% |
| Pirate | 1314 / 5010 (26.23%) | 1.4757 | 0 | 63.47% | 38.99% |

The mean within-pixel fine variances are 0.0033577, 0.0024947, and 0.0040567 for Torus, Monkey,
and Pirate. Their area-integral variances are much larger because they include variation between
foreground and background pixels. At the roughly half-face outputs, Torus/Pirate would require
proxy queries about **5.10x/5.07x cheaper**, before overhead, for any strict benefit. At roughly
quarter faces they cannot improve this constant-p estimator even in the limit of a free proxy.
Monkey remains potentially feasible within this finite model, conditional on actual ray costs;
it does not establish a new method or a hardware speedup. These are 108 fresh image comparisons,
15,925,248 paired finite coverage atoms, with all archived disagreement counts reproduced exactly.

The cost limits concern **measured finite coverage distributions and constant correction p**.
They are not bounds for every unbiased estimator or arbitrary geometric proxy. Triangle count
ratios are reported only to identify outputs; they are not substituted for actual ray costs.
The oracle p tables omit probe/build/selection overhead, so they are optimistic within this family.
Per-view limits and mismatches in constant fine pixels are included in the JSON.

## Verification and decision

Six targeted tests pass: rational enumeration of Bernoulli outcomes and both mismatch directions;
closed-form optimum against a dense independent probability grid; the strict break-even boundary;
perfect/constant fine targets; no-gain/invalid-input cases; and independent per-pixel enumeration
that catches the between-pixel variance mistake. No C++ was changed or newly built for this screen.
The completed report also passed a separate hash and aggregation check: all 108 comparisons,
pooled four-way counts, exact image-variance numerators/denominators, shared fine variance across
levels, and the two no-gain cases were checked against the saved inputs and report fields.

```
python -m unittest discover -s tools/mmgeo -p test_proxy_visibility_cost_gate.py -v
python tools/mmgeo/proxy_visibility_cost_gate.py --output out/proxy-visibility-cost-gate-20261115-v2/report.json
```

The generic unbiased proxy-correction proposal is closed as a new contribution. The generic
variance-times-time optimization proposal is also insufficient. A remaining geometric construction
idea would need an explicit operation/representation and a measured advantage over ordinary QEM,
occlusion-preserving proxies, and established residual-estimation controls. No such mechanism
has been demonstrated. Coverage-only gates cannot establish shadow/BSDF/path-transport quality;
hardware acceleration-structure traversal costs have not been measured. The native mmgeo execution
constraint remains as recorded in the research ledger. The SIGGRAPH goal is still unmet.
