# Exact discrete filter-energy C++ kernel

Date: 2026-11-14. Experimental private module; not a new simplification algorithm claim.

## Mechanism

Let F be the fixed, finite, separable Gaussian convolution followed by box downsampling, r the
current output-image residual, and d a sparse vector of ACTUAL raster sample changes. Then

    deltaE = 2 d^T F^T r + d^T (F^T F) d.

`libs/manymesh/src/DiscreteFilterEnergy.{h,cpp}` computes this increment in two ways:

- Gram: pairwise inner products of exact discrete impulse responses, without making a candidate
  output image. Worst-case quadratic in changed-sample count.
- Splat: scatter sparse impulses into a tight output patch and evaluate residual change. This is
  the strong native baseline, not a full-frame convolution or Python implementation.

The finite viewport, truncated kernel, box-filter/downsample phase and two-channel residuals are
represented explicitly. Updates may cancel previous error; sign=-1 reverses the linear image
update under unchanged filter/camera. This is not undo of geometry or visibility.

The input must already reflect correct nearest-surface visibility. There is no coarse-raster
substitution or neural prediction. No nonlinear temporal reconstruction guarantee follows.
The quadratic identity and sparse convolution are standard mathematics; absence of an exact paper
search hit does not establish mesh-simplification novelty.

## Tests and scope

Three new C++ tests passed against an independent dense convolution and reduction implementation:

1. Viewport edges and ALL sample phases at scales 1/2/3/4, sigma .2/.9/1.7, duplicate coordinates.
2. Random accumulated changes and cancellation, matching complete recomputation.
3. Invalid coordinates/dimensions/sigma/nonfinite values rejected without changing history.

Headers formatted using repository tool and standalone header syntax checked. No public Filament
API/binding changes. The module is private to ManyMesh and not wired into production ranking.

## Real-candidate benchmark

`export_raster_deltas.py` resolves actual real candidates from the frozen 48-candidate trajectory,
exports all nonzero sample changes without tolerance dropping, and records extraction times.
Input/script/report hashes are recorded. Export artifacts: `out/discrete-filter-pilot/`.

`mm_filter_energy_bench` compares Gram and Splat in the SAME native binary, with warm-up and six
alternating timing blocks. Large Gram inputs (>2048 events) are explicitly skipped to avoid
quadratic explosions; skipped cases cannot be hidden from reporting. All scores must agree with
the independently filtered exported reference before timing is accepted. Input parsing is outside
scorer timing, and Python visibility extraction is not a native end-to-end measurement.

The benchmark reports score-only performance; it must NOT be advertised as mesh simplification
or whole-frame speedup. Reusable filter table setup and persistent arrays are separately reported.

## Validation limitations

Mandatory full desktop Debug command re-attempted; existing prebuilt-tools cache still selects GNU
and repository rejects it. utils repeated with 333 passed / one JobPoolExhaustionNullJobRun failure.
Full ManyMesh regression completed: 94 passed, one HTTP environment skip. All 864 exported
real-candidate scores matched the independently filtered references; no Gram cases exceeded the
2048-event cap. Maximum absolute difference was about 1.03e-14.

## Native performance result: reject pairwise Gram as the main scoring path

| Asset | Median changed samples | Splat median microseconds | Gram median microseconds | Total splat/Gram time ratio |
|---|---:|---:|---:|---:|
| Torus | 474.5 | 39.53 | 879.27 | 0.0278 |
| Monkey | 50.5 | 4.27 | 14.89 | 0.0755 |
| Pirate | 13 | 1.15 | 1.48 | 0.0572 |

Total ratios include dense tails; they are not ratios of the medians. Gram was faster in only
4/288, 34/288 and 97/288 individual cases respectively. These are score-only CPU measurements,
not performance of geometry updates or a renderer. Setup took 0.15–0.33 ms, persistent arrays
337088 bytes per tested instance, excluding scratch and allocator overhead.

Decision: do not expand pairwise Gram scoring as the proposed main algorithm. Exact discrete
filter algebra is useful for verification, but avoiding candidate-image construction did not beat
a native sparse-splat baseline. This is a measured native negative result, not merely a Python
implementation concern. No new mesh algorithm or SIGGRAPH contribution has been established.
Artifacts: `out/discrete-filter-pilot/{torus,monkey,pirate}-score.json` and `summary.json`.
