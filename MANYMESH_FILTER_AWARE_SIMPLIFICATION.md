# Filter-aware reversible local mesh simplification

Date: 2026-11-14; literature reassessed through 2026-11-22.
Status: hypothesis, C++ error kernel, and controlled thin-strip experiments.
A general dynamic mesh algorithm, novelty, and real-time gains remain unverified.
Latest controls and blockers: [experiment record](tools/mmgeo/FILTERED_BOUNDARY_EXPERIMENT.md).

## 1. Research decision

Improve local simplification itself: estimate image error from smooth surfaces and
visibility-boundary displacement, optimize collapse placement, record reversible
operations, and update local geometry under view and execution budgets.

Disable neural reconstruction initially. Freeze material, lighting, resolution,
and antialiasing. Study temporal upscaling only after establishing geometry gains.
Adding TAA, upscaling, or an MLP alone is not a contribution. See the
[research ledger](MANYMESH_RESEARCH_ROADMAP.md) for status and gates.

Existing components include QEM/attribute/Corner simplification, quality gates,
a fixed single-parent hierarchy, and dynamic cuts. There is no resumable online
collapse/split executor. Read-only regrouping trials have not established gains
or proved that grouping blockage is the main cause.

## 2. Boundary changes differ from smooth displacement

For a locally straight image boundary with color jump delta_c, length L, and
screen-normal displacement d, ignoring endpoints, curvature, and other boundaries:

```text
E_boundary(d) = L ||delta_c||^2 |d|.
```

This unfiltered continuous squared-image error is first order in displacement;
a first-order color linearization in a smooth region yields quadratic error.
Using squared world distance for both misses that distinction. This observation
is not a novelty claim.

Pixel filtering matters. Convolve the boundary with a Gaussian of sigma > 0 and
let Phi be the standard normal CDF. Per unit length and unit color contrast:

```text
rho_sigma(d) = integral [Phi(u/sigma) - Phi((u-d)/sigma)]^2 du
             = |d| erf(|d|/(2 sigma))
               + 2 sigma/sqrt(pi) [exp(-d^2/(4 sigma^2)) - 1].
```

Writing u = |d| and G_sqrt(2)sigma for a normalized Gaussian with standard deviation
sqrt(2)*sigma, the step difference is an interval indicator convolved with a
Gaussian. Kernel autocorrelation gives the analytic derivation:

```text
rho_sigma(d) = 2 integral_0^u (u-s) G_sqrt(2)sigma(s) ds
rho_sigma'(d)  = erf(d/(2 sigma))
rho_sigma''(d) = exp(-d^2/(4 sigma^2)) / (sigma sqrt(pi)) > 0
as d -> 0: rho_sigma(d) = d^2/(2 sigma sqrt(pi)) + O(d^4)
as |d|/sigma -> infinity: rho_sigma(d) = |d| - 2 sigma/sqrt(pi) + o(1).
```

Small displacements have quadratic loss; large displacements approach linear loss.
Do not apply unfiltered absolute displacement to all antialiased subpixel motion.
Historical Python standard-library quadrature checked sigma=0.5:

| Displacement in pixels | Closed form | Numerical integral |
|---:|---:|---:|
| 0.01 | 0.000056418 | 0.000056418 |
| 0.05 | 0.001409887 | 0.001409887 |
| 0.20 | 0.022418328 | 0.022418328 |
| 1.00 | 0.486064958 | 0.486064958 |

This checks the formula, not mesh quality or speed. Sigma=0.5 is illustrative,
not a measured TAA/upscaler parameter. A synthetic ranking example uses length
80 px, sigma=0.5: boundary A moves 0.2 px with contrast 1, B moves 0.4 px with
contrast 0.1. Squared displacement ranks A's 0.04 below B's 0.16, while filtered
image error ranks A's 1.793466 above B's 0.070350. No actual QEM/Corner run is
involved; strong attribute-aware baselines may also recognize contrast.

## 3. Candidate local solver

For one legal candidate edge, optimize placement x in R^3 within a finite trust
region. Freeze visibility, surface correspondence, boundary samples, and attribute
interpolation charts. Use smooth color/depth/normal residuals A_i*x-b_i,
screen-normal boundary displacement d_j(x)=a_j^T*x-b_j, and weights
w_j=length_j*||delta_c_j||^2 with consistent pixel-area normalization:

```text
F(x) = sum_i omega_i ||A_i*x-b_i||^2
       + sum_j w_j rho_sigma_j(a_j^T*x-b_j)
       + eta Q_geom(x).
```

With fixed coefficients, nonnegative weights and positive-semidefinite Q_geom,
F is convex. A damped Newton or other low-dimensional solver can handle a convex
trust region. Regularization must remove degenerate directions; strict convexity
and uniqueness are not automatic. Convexity applies only to this frozen single-edge
proxy, not perspective projection, reinterpolation, topology legality, visibility
changes, or combinations of edits.

For a fixed real one-dimensional filter k, define
C(s)=integral k(t)k(t+s)dt. Then
rho_k(d)=2 integral_0^|d| (|d|-s)C(s)ds. Nonnegative kernels give C>=0 and preserve
single-boundary convexity; negative-lobe sharpening kernels need not. This permits
tables for measured fixed spatial kernels, not replacing nonlinear temporal models
with one kernel.

Candidate procedure:

1. Generate legal edges/placements using existing topology/material/chart rules.
2. Solve the small proxy, retaining the QEM placement as a control or fallback.
3. Check actual topology, attributes, thin sheets, boundaries, and error gates.
4. Trigger local patch depth/coverage validation near silhouette ownership changes,
   near-equal depth order, or closing slits.
5. Accept only after validation and when predicted benefit exceeds estimation error.
   Defer verification that exceeds budget; do not assume safety.
6. Update affected neighbors only and save connectivity/attributes needed to undo.

Surface and boundary terms need disjoint support or explicit overlap subtraction.
Overlapping filtered boundaries, curvature, and appearance/disappearance events can
invalidate independent sums; evaluate a patch or reject conservatively. Infer no
lighting/texture derivatives from background pixels. Start with controlled normal
shading and known materials; later cover highlights, shadows, textures, unseen views.

### 3.1 Thin structures require coupled boundaries

For locally parallel boundaries with signed color jumps c_i, old positions a_i,
and new positions b_i, per-unit-length residuals and inner products are:

```text
r_i(t) = Phi((t-a_i)/sigma) - Phi((t-b_i)/sigma)
K_ij = 1/2 [rho_sigma(a_i-b_j) + rho_sigma(b_i-a_j)
            - rho_sigma(a_i-a_j) - rho_sigma(b_i-b_j)]
E = sum_i sum_j (c_i dot c_j) K_ij.
```

K is a Gram matrix of actual residual functions and hence positive semidefinite
in exact arithmetic. If b_i depends on optimized placement, single-boundary
convexity does not establish joint convexity. Score a small placement set first;
do not promise global Newton convergence.

For sigma=0.5, opposite color jumps moving from (0,0.3) to (0.2,0.5) yield
0.044836656 by independent addition, but 0.003810298 with cross terms, matching
numerical integration. Independent addition overestimates by about 11.8x here.
This validates only the one-dimensional parallel-boundary model. Neither mesh
benefit nor novelty of the closed-form kernel follows.

A possible mechanism maintains sparse coupling for nearby filtered contours,
uses independent terms farther away, and validates events with patches. Earlier
DAG interaction trials used different candidates and a two-sided single-sample
depth proxy; they neither prove nor reject these filtered cross terms. Gaussian
support is infinite, so neighbor truncation is approximate and needs error checks.

## 4. Toward demand-driven dynamic geometry

Operation state needs local support, undo data, dependencies, version, geometry/
attribute correspondences, estimated error, and measured execution work.
Coarsen with legal edits that reduce faces at low incremental error; refine by
undoing edits where demand increases. Charge dependency closures together. Prevent
support conflicts in batches and do not sum single-edit benefits as exact batch gains.

Updating only regions affected by cameras, visibility, or edits is a design goal,
not measured behavior. First implement a resumable CPU state machine and correctness
control, then consider GPU execution. Do not restart full simplification each frame.
Closed topology, material partitions, and gates can make requested budgets infeasible.
Progressive meshes, view-dependent refinement, coherent updates, and reversible
collapse/split operations are established mechanisms, not standalone contributions.

## 5. Temporal reconstruction as a second phase

Ask whether simplification destroys reusable historical surfaces and which cheap
correspondences establish history validity. Local collapse provenance plus current/
historical visibility may help, but coarse-to-fine mappings are generally not
bijective. Deleted occlusion layers and silhouettes cannot be recovered by mapping;
history rejection must remain possible.

```text
T_update + T_geometry + T_shading + T_reconstruction <= T_budget
```

Minimize final error under this total budget, reporting actual CPU/GPU and sync
costs. Triangle counts do not measure frame time. Real TAA/upscaling is nonlinear
and depends on history; rho_sigma describes only controlled spatial filtering.
Measure a real reconstructor's response and compare it with the fixed-filter proxy.

A laptop can first evaluate nonneural TAAU/FSR2-style paths; Arm ASR is relevant
to mobile investigation. DLSS needs RTX and is not an Iris Xe deployment path.
Consider tiny models for local coefficients or failure risk before full-resolution CNNs.

## 6. Repository confounds to exclude

- The historical `LodGraph.cpp:927-948` lock calculation mixed original-leaf/current
  member counts and wrote raw-vertex masks, while Corner and the unified gate read
  canonical-position masks. Establish the contract in a minimal test; static code
  differences do not prove cracks or stalled simplification.
- Raw node face counts differ from assembled/deduplicated faces. Budget the actual
  submission path consistently.
- Existing gates use sampling, not continuous Hausdorff or global intersection proofs.
- Bind old regroup records to their code versions instead of calling them current results.

## 7. Entry experiment and stopping rules

Start with local collapses before a dynamic system; hold hierarchy, selector,
material, and reconstruction fixed.

1. Freeze legal candidates/gates; compare QEM, Corner, quadratic screen error,
   filtered-boundary proxy, and an oracle reading reference renders.
2. Separate placement optimization from edge ranking at equal candidate-evaluation cost.
3. Cover smooth surfaces, contours, thin rods, slits, UV seams, highlights, and
   occlusion. Report proxy errors, false accepts, and validation-trigger rates.
4. On unseen assets with frozen parameters and continuous cameras, compare equal
   faces, equal quality, and equal total time. Include failures and tail latency.
5. In the dynamic phase measure switching/history invalidation, refinement latency,
   caches/memory, and dependency closures, not just static PSNR.
6. Stop if the proxy fails strong image-driven baselines on quality/cost or patch
   rerendering consumes the gain. Upscaling cannot establish a missing geometry gain.

A SIGGRAPH candidate needs a justified proxy, inexpensive compatible geometry
updates, and end-to-end benefit under strong baselines. A closed form, weighted
QEM, GPU port, or upscaler integration alone is insufficient.

## 8. Prior art and boundaries

- [Hoppe, View-Dependent Refinement, 1997](https://hhoppe.com/proj/vdrpm/): selective
  refinement, coherent updates, and smooth transitions are established.
- [Hoppe, New Quadric Metric, 1999](https://hhoppe.com/proj/newqem/): attributes and
  wedge discontinuities are established.
- [Image-Driven Simplification, 2000](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf):
  initial retrieval failed; a later report checked sections 3-4. Multiview luminance
  RMS collapse ranking, local rectangle redraw, dirty flags, and lazy updates already
  exist. Topologically distant edges can be image neighbors. A candidate must improve
  prediction accuracy/cost and dynamic use, not merely introduce local image updates.
- [Appearance-Driven Simplification, 2021](https://research.nvidia.com/publication/2021-04_appearance-driven-automatic-3d-model-simplification):
  joint mesh/appearance optimization is established.
- [Dynamic Mesh Processing on the GPU, 2025](https://doi.org/10.1145/3731162): existing
  system work covers GPU dynamic topology and decimation.
- [HLOD ASAP, 2026](https://onlinelibrary.wiley.com/doi/10.1111/cgf.70380): the abstract
  covers progressive interiors/boundaries, neighbor consistency, and reduced popping.
  Publisher full text returned 403; the abstract cannot complete the overlap audit.

### Joint reconstruction literature supplement

[Appearance-Driven Simplification full text](https://arxiv.org/html/2104.03989)
includes supersampled references, distance-dependent prefiltering, and silhouette/
MSAA handling. Optimization fixes externally simplified topology. Filter/silhouette
awareness alone is insufficient; compare discrete-collapse, local-update, and dynamic costs.
[Adaptive Temporal Antialiasing, 2018](https://research.nvidia.com/sites/default/files/pubs/2018-08_Adaptive-Temporal-Antialiasing/adaptive-temporal-antialiasing-preprint.pdf)
uses adaptive ray samples to supplement TAA. Full-text extraction failed in that
review, so its complete mechanism and relation to geometry budgets remain unaudited.
A complete precedent comparison for joint geometry, pixel samples, and history
validity is missing; that does not imply no precedent exists. Also audit image
processing, shape derivatives, and differentiable rendering for the boundary formula.

Deployment references, not local performance evidence:
[FSR temporal upscaling](https://gpuopen.com/manuals/fidelityfx_sdk/techniques/super-resolution-temporal/),
[XeSS](https://www.intel.com/content/www/us/en/developer/topic-technology/gamedev/xess.html),
[DLSS](https://developer.nvidia.com/rtx/dlss),
[Arm ASR](https://github.com/arm/accuracy-super-resolution-generic-library).
TAA addresses same-resolution AA; TAAU adds upsampling. Evaluate FSR temporal
upscaling separately from frame generation. XeSS has a non-XMX path, but hardware
support does not prove speedup on Iris Xe. Changed triangle IDs alone do not
invalidate history; audit correspondence, depth visibility, and confidence.

### 2026-11-16 literature reassessment

Lindstrom-Turk already compares source/candidate multiview image error per collapse,
using object buffers or local redraws. Pfeiffer's 2001 thesis abstract likewise
limits generated image data to edge neighborhoods. Replacing that local image error
with a filtered proxy requires a substantial same-quality total-cost advantage.
SIGGRAPH 2026 quad-dominant reduction uses global ILP edge selection; clustered HLOD
permits progressive boundary simplification with neighbor constraints. Neither is
identical to a filtered view objective, but broad global-selection and progressive
cluster-boundary claims are closed. Thin-strip experiments establish no general
mesh, visibility, or production-shading advantage for rho_sigma.

Keep this as a hypothesis. Compare Corner/QEM, full local reference redraw, and the
analytic proxy on the same frozen real candidates, counting extraction, validation,
caching, undo, and full-build costs. Stop on either cost or unseen-asset quality
failure; adding dynamic hierarchy or upscaling does not remedy a failed gate.

### 2026-11-16 differentiable/topological derivative correction

[EdgeGrad, ECCV 2024](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/11059.pdf)
computes raster-loss gradients including occlusion/revelation and intersections.
[Topological Derivatives, ICCV 2023](https://openaccess.thecvf.com/content/ICCV2023/papers/Mehta_A_Theory_of_Topological_Derivatives_for_Inverse_Rendering_of_Geometry_ICCV2023_paper.pdf)
uses level-set derivatives for image-driven hole/region insertion and removal.
[DiffSoup, CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/papers/Tojo_DiffSoup_Direct_Differentiable_Rasterization_of_Triangle_Soup_for_Extreme_Radiance_CVPR_2026_paper.pdf)
optimizes opaque triangle soup from multiview images, splitting by projected edge
length and pruning by multiview coverage under triangle budgets.

The narrower unsolved candidate is selecting finite legal collapses of a given
ManyMesh source mesh, preserving connectivity and attribute boundaries, below the
cost of local redraw per candidate. Combining raster differentials with corrections
for triangles disappearing along a collapse path is only an untested hypothesis.
Existing differentiation, topology changes, and image-guided budgets do not become
novel merely by combination.

### 2026-11-22 prior-art update

[Rasterized Edge Gradients (EdgeGrad), ECCV 2024](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/11059.pdf)
computes raster-loss gradients for mesh vertex positions at visibility boundaries,
occlusion/disocclusion, and geometry intersections without changing the forward
rasterized image. It directly overlaps the proposed use of image-loss boundary
signals to guide vertex edits. It does not define a legal edge-collapse sequence,
preserve ManyMesh's chart/material contracts, or establish a dynamic simplification
budget; those are implementation differences, not contributions without measured
benefit.

[DiffSoup, CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/papers/Tojo_DiffSoup_Direct_Differentiable_Rasterization_of_Triangle_Soup_for_Extreme_Radiance_CVPR_2026_paper.pdf)
reconstructs radiance fields from multi-view images as a budgeted, unstructured
triangle soup using differentiable rasterization, stochastic binary opacity, and
neural textures. It does not simplify an authored connected mesh or preserve its
topology and attributes, but it closes broad claims around image-supervised,
triangle-budgeted reconstruction into ordinary rasterizable geometry. A fixed-mesh
candidate would need to demonstrate a distinct capability on authored assets and
a repeatable quality-cost advantage over this work where the input contracts
overlap, as well as EdgeGrad, exact local redraw, and meshoptimizer/Corner controls.

These papers further reduce the plausible novelty space; they do not establish
that the constrained edge-collapse problem is solved. The candidate remains
unvalidated. Do not implement a production path until legal candidate sequences
on real meshes show a stable matched-cost gain over those direct baselines.

Before implementation, freeze full legal candidate pools on at least two real
meshes. Compare QEM/Corner, exact local redraw, shared raster-backprop EdgeGrad
first-order ranking, and path integration with disappearing-face corrections.
Report full-pool rankings, exact selected filtered RGB/coverage/depth changes,
matched-face cumulative error, raster/differential calls, and total cost. Include
visibility changes, subpixel structures, seams, and disappearing-face-dominated
support. Stop if integration approaches per-candidate redraw cost, depends strongly
on sample phase, or loses to exact redraw/image-driven baselines on quality/cost.
No algorithm, result, or SIGGRAPH contribution is established here.

Existing `out/filter-real-candidates/` and `CornerCandidateCapture` are not full
candidate pools: capture records only the currently best legal placement per directed
edge in the initial state, neither all placements nor candidates regenerated after
accepted edits. New capture-interface tests had only syntax-check records, not
execution results. Verify that contract and bind captures to source/gate versions
before the next experiment. Fixed-pool replay is not full sequential simplification.
