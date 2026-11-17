# Related-work boundary: dynamic GPU mesh processing

2026-11-15. Targeted check prompted by the dynamic/on-demand ManyMesh objective.

SIGGRAPH 2025 published **Dynamic Mesh Processing on the GPU** (Ahmed H. Mahmoud, Serban D.
Porumbescu, John D. Owens). The official conference program describes a GPU system for fully
dynamic triangle-mesh operations, with a patch-based structure, speculative conflict handling,
and a programming model. The ACM article is [TOG 44(4), Article136, DOI 10.1145/3731162](https://doi.org/10.1145/3731162).
Its abstract reports order-of-magnitude speedups over CPU solutions across applications.
Program source: [SIGGRAPH 2025 official schedule](https://s2025.conference-schedule.org/presentation/?id=papers_496&sess=sess134).
The official SIGGRAPH proceedings index independently lists its title and authors:
[SIGGRAPH 2025 conference papers](https://www.siggraph.org/wp-content/uploads/2025/08/Conference-Papers.html).

This is a direct systems-level overlap with any claim whose novelty is merely dynamic triangle
topology updates, patch-local mutation, conflict-safe parallel edge operations, or GPU execution.
ManyMesh therefore cannot claim those mechanisms as new. The present Python experiments do not
compare to this system, do not run on GPU, and do not demonstrate even a production CPU advantage.
The prior native execution constraints also mean no honest comparative performance claim is
available in this workspace.

The full author version is available through the
[UC eScholarship entry](https://escholarship.org/uc/item/1sm051d2). Its shortest-edge-collapse
example batches priority-ordered candidates with a 256-bin histogram and attempts the top 1%
concurrently, repeating histogram construction until the vertex target is reached. It explicitly
uses this to balance shortest-first quality against GPU parallelism. Thus ordered batched edge
collapse, histogram priority queues, cavity-based dynamic mutation and optimistic conflicts are
all direct baselines for an on-demand GPU simplifier, not open novelty by themselves.

The paper's demonstrated selection policy does not establish a renderer-coupled, path-dependent
collapse utility for filtered appearance error. This is a scope distinction, not a novelty
clearance.

Any future contribution must combine a genuinely new mesh-specific decision rule with evidence
that it changes valuable operations under a fixed budget AND a real advantage beyond generic
dynamic mesh support. It must compare against current regenerated QEM, the cumulative image
control, and the dynamic GPU baseline where available, measuring selection quality, update cost,
conflict/retry cost, quality regressions, memory, and full end-to-end time. Simply using the
paper's patch API for existing ManyMesh raster edits would be engineering integration, not a
paper contribution.

The most defensible remaining distinction is narrower: whether a renderer-coupled, path-dependent
collapse utility can be updated cheaply enough to improve the quality/parallelism trade-off over
batched ordered QEM, while preserving a measurable error guarantee or calibrated failure signal.
This remains only a research question. Our cumulative image control is serial, very expensive,
and has not beaten QEM consistently under RGB or relighting. There is no evidence yet that such
a rule would improve the prior system or amortize its attribute/render cost.

Relevance to the active compensation branch: the current tested normal-compensation ranking
chooses exactly the same candidate as the cheaper coverage/depth control, and its small extra-view
gain does not support an expensive dynamic attribute solver. Do not continue tuning that branch
unless the uniform precision study reveals a robust decision difference that the geometry score
misses.

## 2026-11-16 follow-up: view-dependent GPU collapse is older than the 2025 system

A targeted search found a more direct historical baseline than the recent dynamic-mesh paper:
Odaker, Kranzlmüller, and Volkert's 2016 *View-dependent Triangle Mesh Simplification using
GPU-accelerated Vertex Removal* (WSCG 2016; the related MEMICS 2015 chapter is titled *GPU-Accelerated
Real-Time Mesh Simplification Using Parallel Half Edge Collapses*). Their WSCG paper executes
independent half-edge-collapse-based vertex removals in parallel, with per-vertex boundaries to
avoid foldovers and topological inconsistencies, and targets view-dependent simplification in real
time. Its candidate error is geometric and then scaled by camera position/view direction; the 2016
revision uses a curvature-based geometric error and auxiliary replacement vertices to increase
parallelism. It does not score a filtered rendered-image difference. Primary sources:
[WSCG paper PDF](https://naos-be.zcu.cz/server/api/core/bitstreams/e1bbc834-e4dc-42e1-8603-98c6311433fb/content)
and [LMU record for the MEMICS chapter](https://epub.ub.uni-muenchen.de/47332/).

Another adjacent precedent is Xing et al.'s 2014 *Highly parallel algorithms for
visual-perception-guided surface remeshing*: it maps image-space perceptual cues back to a saliency
field and parallelizes GPU point resampling to control the resulting mesh complexity. It is
remeshing rather than connected legal edge-collapse scheduling, so it does not close that exact
operation contract. Primary record: [PubMed / DOI 10.1109/MCG.2013.84](https://pubmed.ncbi.nlm.nih.gov/24808168/).

The *conflict-free batch* component is also established for mesh edits. Ströter et al.'s HPG 2023
*Massively Parallel Adaptive Collapsing of Edges for Unstructured Tetrahedral Meshes* uses
cost-prioritized conflict detection to choose edges that can be collapsed in parallel, with a
second pass resolving conflicts at affected simplices. It targets tetrahedral coarsening and does
not use projected image-support conflicts; nevertheless, generic topology-conflict scheduling and
parallel edge collapse are prior art. [Paper PDF](https://diglib.eg.org/bitstream/handle/10.2312/hpg20231139/089-099.pdf).

Together with Lindstrom–Turk 2000's rendered-image edge-collapse ranking and local redraw, plus
Mahmoud et al. 2025's GPU cavity updates and batched shortest-edge decimation, these works occupy
the broad components separately: image-error simplification, view-dependent parallel simplification,
and high-throughput dynamic GPU topology. A composition of those components is not a novelty claim.

### Remaining falsifiable hypothesis (not cleared)

The only distinction in this image-driven GPU-collapse branch still worth a cheap feasibility screen
is a **screen-space batch-conflict graph**: accept a batch only when collapse topology supports do
not conflict and their projected, filter-expanded image supports are disjoint across every scored
view. Under fixed visibility,
fixed shading, and finite-support linear filtering, disjoint image supports make squared-image-error
changes additive; this permits exact batch scoring without pairwise image cross terms. The interesting
question is whether this preserves enough parallelism to beat (a) the 2016 view-dependent parallel
collapse baseline and (b) the 2025 cavity-based dynamic-mesh baseline, while approaching the quality
of sequential full local image-error ranking. Cameras, visibility changes, shadowing, and filter
halos must be included in the support contract; a 2D rectangle alone is not a correctness proof.

Existing data gives an unfavorable early signal. In the corrected real-candidate interaction audit,
11.6–14.8% of one-ring-disjoint pairs had nonzero filtered-residual cross terms; this is the
measured delta overlap rate, not the projected-support-box overlap rate. Strong (>10%) error cross
terms were 0.10–0.82%, and ranking reversals were 0.082–0.498% of tested triplets. Extending
independent versus pairwise-interaction batch selection to six views each of Torus, Monkey, and
Pirate produces identical schedules at k=2, 4, and 12 on all three meshes. At k=8, only one Pirate
view changes; its actual SSE falls by 8.45e-11 (0.386% mean gain across the six views). All tested
composites pass basic topology/orientation checks, but this tiny fixed-pool effect does not support
a useful quality claim or establish a contribution. Details: [cross-asset interaction audit](MULTI_COLLAPSE_INTERACTION_CROSS_ASSET_20261116.md).

### Kill screen: strict screen-disjoint batching loses quality at matched reduction

The [2026-11-16 support audit](SCREEN_BATCH_SUPPORT_AUDIT_20261116.md) replaces the earlier
feasibility guess with exact finite-pool comparisons across six views each of Torus, Monkey, and
Pirate. Projected old/new face boxes plus a filter halo conflict for 20.8–32.1% of topology-
compatible pairs; exact maximum batches contain only 7–10 of the requested 12 collapses. Measured
filtered-residual pixel masks lower some conflict rates and permit batches of 11–17 operations,
but the minimum-additive-cost disjoint batches still have 103x to 7.86 million x the actual SSE of
topology-only batches at the same collapse count. Because some topology-only errors are near zero,
the audit also reports absolute SSE increases per view. Residual-disjoint outputs agree with
additive SSE to at most 1.11e-16 and pass basic topology/orientation checks; their poor quality
comes from forbidding useful overlapping changes, including cancellations.

The exact MILP ran with SciPy 1.15.3 / NumPy 2.5.4 and emitted a dependency-version warning (SciPy
declares NumPy <2.5); its returned MIP gaps were zero, but reproduce in a supported environment
before relying on the exact optima. This closes strict screen-disjoint batching as the image-quality
selector for these three frozen geometry-only pools. It does not test regenerated sequences,
materials, shadows, or GPU throughput. Do not promote the conflict graph as a SIGGRAPH mechanism.

Do not implement a production path from this hypothesis yet. A decisive screen would need complete,
regenerated legal candidates on multiple meshes; same-gate outputs; equal reduction and image-quality
metrics; batch width, support-index construction/update, retries, and total time; a serial exact
local-redraw control; and an actual GPU comparison. Stop if the extra screen conflicts only shrink
batch width without improving held-out image quality, if visibility/shadow supports make the graph
dense, or if total time loses after index and raster costs. The current workstation's documented
Intel Iris Xe-only Vulkan capability does not provide a validated CUDA/RT path for the 2025 system,
so there is no GPU performance result here. This hypothesis remains low-confidence and is not
evidence that no one has studied it.
