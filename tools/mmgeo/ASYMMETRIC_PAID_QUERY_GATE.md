# Paid asymmetric local proxy query: negative cost gate

Date: 2026-11-15. This closes the remaining runtime question from the fixed-cut
local proxy screen; it does not establish a novel algorithm.

## Prior-art boundary

The proof used here is the oriented-boundary winding invariant. It is not new.
Bernardini, Klosowski, and El-Sana's *Directional Discretized Occluders for
Accelerated Occlusion Culling* already replaces complex geometry with simple
view-dependent polygons for conservative visibility queries
([Eurographics/CGF 2000 paper](https://onlinelibrary.wiley.com/doi/10.1111/1467-8659.00443),
[author PDF](https://static.aminer.org/pdf/PDF/000/787/398/directional_discretized_occluders_for_accelerated_occlusion_culling.pdf)).
Laine's 2006 thesis describes the related boundary-edge winding test, notes
that Bernardini et al.'s line-20 point-in-polygon rule is underspecified, and
shows why signed winding rather than even-odd parity is needed for tricky
occluders ([thesis, §4.6](https://users.aalto.fi/~laines9/publications/laine2006msc_paper.pdf)).
Consequently, this experiment makes no novelty claim for winding certificates,
conservative occluders, or coarse proxy queries.

## Experiment

The new evaluator applies the two outcome-specific implications to **all**
1,737 reduced patches, including patches rejected by the earlier combined
normal cone:

* Proxy hit + proxy one-sided-facing certificate: accept the hit.
* Proxy miss + source one-sided-facing certificate: accept the miss.
* Otherwise query the original fine subtree after already paying for the proxy.

Every candidate is still guarded by the finite-segment-spans-source-node test.
The source node's already-tested box is reused as the proxy-root test. The
report compares exact binary answers with the frozen fine-query target and
charges AABB=1, triangle=2, cone=0.5. These are hypothetical operation weights,
not measured hardware costs.

| Asset | Patch cap | Total cost / fine | Certified hits | Certified misses | Proxy then fine |
|---|---:|---:|---:|---:|---:|
| Torus | 32 | 1.402x | 553 | 158 | 5,980 |
| Torus | 64 | 1.500x | 0 | 0 | 6,546 |
| Torus | 128 | 1.559x | 0 | 0 | 6,334 |
| Monkey | 32 | 1.153x | 1,614 | 1,141 | 2,356 |
| Monkey | 64 | 1.257x | 1,095 | 788 | 3,400 |
| Monkey | 128 | 1.356x | 779 | 464 | 4,014 |
| Pirate | 32 | 1.258x | 53 | 28 | 2,623 |
| Pirate | 64 | 1.368x | 14 | 6 | 3,266 |
| Pirate | 128 | 1.430x | 2 | 3 | 3,401 |

All nine cases return the same answers as the fine baseline over 110,592
queries, but all nine cost more under the stated model. This falsifies the
remaining hypothesis that the asymmetric certificates alone rescue the
current fixed-cut local proxy design. The experiment does not rule out other
proxy representations, fused kernels, or workloads.

## Reproduction and artifacts

Run from the repository root:

```powershell
python tools/mmgeo/evaluate_asymmetric_patch_queries.py out/fused-patch-visibility-20261115-v2/report.json
```

Evaluator: `evaluate_asymmetric_patch_queries.py`, SHA-256
`5b217b3c0eb83075964faaab72f84b4d7389230e86a4b82bf481f14c5b741622`.
Input fused report SHA-256:
`ce030715cff41ca62f8201c18a4e4a02134acecceb590a0f3fc46988aec60ceb`.
Output: `out/fused-patch-visibility-20261115-v2/asymmetric-paid-queries.json`,
SHA-256 `1fb765cfc44b691ed1f6a0919976ce4081d5d3f85365c725bcb31db6299a10c0`.

Scope remains three reused development meshes and a synthetic orthographic ray
cohort. There is no held-out asset, renderer integration, production `Corner`
reproduction, GPU measurement, end-to-end rendering benefit, or publication
quality contribution. The SIGGRAPH 2027 goal remains unmet.
