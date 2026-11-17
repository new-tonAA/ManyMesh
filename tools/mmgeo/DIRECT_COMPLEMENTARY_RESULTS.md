# Direct complementary placement: results

2026-11-14. This is a geometry-only research experiment, not a production simplifier.
See [frozen protocol](DIRECT_COMPLEMENTARY_PROTOCOL.md).

The implementation now GENERATES two positions by alternating finite-history objective search,
rather than only mixing a pre-enumerated list. Static search gets the same 48-proposal ceiling;
actual valid redraw counts differ and are reported. Both start at the same captured Corner target,
keep identical collapse connectivity, and use unchanged geometric guards. Every population case
is retained, including failures to improve. There is no reference to test views in fitting.

## Why the midpoint control matters

In any region where the rendered residual is affine, r(x)=Ax+b, the expected IID T-frame error is

    L_T(x,y) = ||r((x+y)/2)||^2 + ||A(x-y)||^2/(4T).

If the midpoint is geometrically admissible, one static midpoint is at least as good as the pair.
This is a standard linearity/variance observation, not a new theorem claimed as a contribution.
It rules out seeking a fundamental temporal advantage purely in affine smooth displacement.
Nonlinear visibility/shading or a nonconvex admissible geometry set is necessary to escape this
argument, but does not guarantee a useful practical method. Perspective/raster equations and
occlusion are not globally affine; the identity is not asserted for arbitrary meshes.

Tests verify the identity and a nonlinear toy where a pair can outperform all static choices.
The toy is a mathematical control, not evidence of a rendering or asset improvement.

## Validation and execution

Final outputs: `out/direct-complementary-cached/{torus,monkey,pirate}.json`.
The first case in each of the six frames is re-rendered over the entire image using the complete
rasterizer, checking the static residual and all pair metrics against the local cached evaluation.
These checks validate support bounds and unchanged-background composition, using the SAME
rasterizer; they are not independent validation of hardware coverage or shader correctness.

## Results: 144 candidates, 48 per asset

| Asset | Training pair vs static | Held-out pair vs static | Held-out worse cases | Coverage regressions |
|---|---:|---:|---:|---:|
| Torus | 0.01160% better | 0.00311% worse | 1 / 96 | 0 |
| Monkey | 0.00833% worse | 0.01141% worse | 22 / 96 | 0 |
| Pirate | 0.61913% worse | 2.63142% worse | 15 / 96 | 6 |

“Held-out” here means two frozen camera offsets not used for fitting, on the same development
assets; it does not mean unseen assets. For Pirate, pair SSE is 1.41826416 vs static 1.38190054.
Training gains fail to generalize; the aggregate predeclared gate fails on every asset.
Best single state seen during pair search and pair mean bias also fail to provide a useful gain.
Median fit times are similar (static/pair): 10.52/10.58 ms Torus, 22.58/21.86 ms Monkey,
13.52/14.02 ms Pirate. These are Python CPU pilot timings, not renderer timings. The search
uses equal proposal ceilings, but actual raster counts are not equal.

Decision: reject this direct two-state placement method for further expansion. The result does
not reject every possible multi-state geometry construction, but there is no evidence here of
quality/cost improvement or publication-level novelty. Next useful work must target the nonlinear
visibility cases with a different construction and compare against equal-budget best-static
optimization before adding runtime machinery.

The initial uncached Torus run and cached final run choose exactly the same targets in all 48
cases. Initial Monkey/Pirate uncached runs were interrupted due to redundant unchanged-geometry
rendering; they are not counted as completed experiments or included in final timing summaries.
The cache does not change the objective/search/guard rules and is not a novelty claim.

36 Python tests pass, including six new tests for finite-history loss, matched proposal ceilings,
guard rejection, search descent, the affine midpoint identity and nonlinear counterexample.
No production C++ change or new C++ build validation is part of this continuation.

Reproduce, substituting each asset:

```sh
python -I tools/mmgeo/evaluate_direct_complementary.py out/filter-real-candidates/monkey.json out/depth-candidate-trajectory/monkey.json --out out/direct-complementary-cached/monkey.json
python -I tools/mmgeo/audit_direct_complementary.py out/filter-real-candidates/monkey.json out/depth-candidate-trajectory/monkey.json out/direct-complementary-cached/monkey.json --out out/direct-complementary-cached/audit-monkey.json
python -I -m unittest discover -s tools/mmgeo -p 'test_*.py'
```
