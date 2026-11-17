# Appearance compensation: novelty and feasibility preflight

2026-11-15. A research question and rejection criteria, NOT an established contribution.
The completed source-moment transfer control is in NORMAL_TRANSFER_ATTRIBUTION.md.

## Evidence and limits

The fixed-geometry control leaves image-driven/QEM RGB changes at +16.73% Torus, +0.81%
Monkey and -26.93% Pirate. It rejects the specific explanation that source-moment averaging
alone removes the mismatch. It does not show whether optimized normals/materials can recover
the appearance. All assets are development data; no generalization evidence exists.

Simply optimizing more attributes would duplicate an established method family. Sources checked:

| Closest work | Established mechanism | Consequence for this project |
|---|---|---|
| [Hoppe 1999](https://hhoppe.com/newqem.pdf) | Attribute quadrics, wedges and simultaneous position/attribute optimization | Adding normals, handling wedges or eliminating a local attribute block is insufficient novelty. |
| [Hasselgren et al. 2021](https://research.nvidia.com/labs/rtr/publication/hasselgren2021diffmodeling/) | Joint image-driven shape and shading optimization, including normal maps and spatial BRDFs | Moving recoverable detail from geometry into shading is already established. |
| [Zhang et al. 2022](https://www.sciencedirect.com/science/article/pii/S0097849322000930) | Decoupled geometry/UV/texture processing, updated correspondence, least-squares texture generation | Rebuilding correspondence and refitting textures is not a new high-level idea. Only the publisher abstract/preview was accessible. |
| [Bhosikar et al. 2026](https://arxiv.org/abs/2605.14029) | Geometric/boundary/normal quadrics and downstream appearance transfer | Another weighted normal/QEM term is not a defensible distinction. Only the abstract was inspected. |
| [O'Leary and Rust, NIST report](https://nvlpubs.nist.gov/nistpubs/ir/2012/NIST.IR.7856.pdf) | Variable projection eliminates conditionally linear variables; originating work dates to 1973 | A reduced least-squares formula is classical mathematics, not a new simplification algorithm. |

Searches did NOT establish absence of related work. The table records positive overlaps, not an
exhaustive novelty clearance. Abstract-level inspection must not be reported as full-paper review.

## Precise candidate question

For a mesh M, fixed camera/light population V, and an explicitly budgeted feasible attribute
set A(M), define

    E*(M) = min_{a in A(M)} sum_{v in V} ||F R(M,a,v) - I_source(v)||^2.

Score a collapse by E*(M_after) - E*(M_before). Both sides must use the same attribute budget
and optimization accuracy. Comparing optimized AFTER to unoptimized BEFORE is invalid.
Per-view independent colors, extra texels, extra normal wedges, or changed material capacity
must not be silently introduced. Count attribute storage, shader work, fitting, updates, and
correspondence maintenance in the resource budget. E* is an optimization target, not a proved
efficient algorithm or a complete physical appearance metric.

For an unconstrained LINEAR, fixed-ownership surrogate with residual r and attribute Jacobian J,

    min_d ||r + J d||^2 = r^T (I - J J^+) r.

This identity is exact only for that surrogate. Unit-normal constraints, interpolation and
renormalization, clipping/specular terms, visibility changes, and attribute budgets invalidate
a claim that this is the exact nonlinear attainable rendering error. A truncated Jacobian or
finite fitting light set also cannot certify unseen lighting. A Taylor approximation is not
automatically a lower bound. QR/SVD is preferable to explicitly forming a projector or inverse.

Eliminating shared attributes generally couples their incident samples. A local collapse does
not imply a local update of the globally optimized solution or its projector. Adding filter
halos to a geometric patch cache alone does not address that coupling. Any low-rank update
proposal must account for changed dimensions, nullspaces, conditioning and commit/rollback;
Woodbury or a Schur complement alone would still be classical linear algebra.

The ONLY presently open possibility is a specific cheaper incremental evaluation of a
budget-constrained attainable error with a useful validity domain. We have neither a proven
update mechanism nor a novelty claim for it. Do not present the equation above as the answer.

## Smallest next decision experiment

Before a new progressive implementation:

1. Fix legal attribute variables and budgets. Initially use smooth unit vertex normals with
   two tangent degrees of freedom per surviving vertex; no extra wedges, UVs or material maps.
   This is a restricted classical control, not a replacement for the eventual attribute baseline.
2. At one saved Torus checkpoint, use a deterministic set of current legal QEM proposals and
   identical source-normalized cameras/lights. Save the complete proposal list before measuring.
   Torus is diagnostic development data; reserve new assets/views/lights for later validation.
3. Compare geometric score, actual RGB with fixed normals, and actual RGB after equally budgeted
   normal fitting on BOTH the current and proposed mesh. Always re-render the actual proposal;
   frozen-owner derivatives cannot stand in for a visibility-changing edit.
4. Separate fitting gain, changed candidate ordering, and nonlinear held-out-view/light quality.
   Report failed solves and every candidate. A rank change is only motivation, not novelty.
5. Only if the compensated ordering helps, derive a concrete incremental approximation or bound
   and compare its total cost against the full fitting control on the SAME implementation and
   candidate population. Include initialization and committed-state maintenance. Existing generic
   filter-patch pruning already lost total time; do not repackage its rejection rate as speedup.

If these controls do not expose a useful decision gap, stop this candidate. If they do, that
still leaves the original contribution, strong attribute baselines, unseen assets, dynamic
tracks, native performance and full material validation to establish. No SIGGRAPH claim passes
from the current evidence.
