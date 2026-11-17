# Per-ray ManyMesh LoD with ReSTIR: novelty and feasibility screen

Date: 2026-11-17. This is a candidate direction, not a novelty claim or a SIGGRAPH-ready result.

## Candidate

Study whether a nested, on-demand ManyMesh hierarchy can expose different mesh cuts to different
ray hits in the same frame while keeping ReSTIR path reuse valid across those cuts. The contribution
would need to be a path-space transport method, not merely a per-ray LOD selector.

For each stored path vertex, a reservoir would retain the object/instance identity, a canonical
surface coordinate, the source LOD, and the ray-footprint state used to choose it. On reuse, each
vertex is mapped from its source LOD to the LOD selected for the transported target path. The shift
Jacobian must include the area change for every mapped vertex. If LOD choice is stochastic, its
selection-probability ratio also belongs in the path density. Partial mappings must reject or fall
back to fresh sampling. A deterministic footprint rule still needs a correct treatment of its
piecewise path-space domains and discontinuities.

This is the hard problem: different paths in one frame may hit different geometry representations.
Applying a UV map independently at each hit is not enough to establish a correct ReSTIR estimator.
The work must derive the target path measure, account for topology and visibility changes, and show
that reused samples converge to the same reference as independent path tracing.

## Prior-art boundary

1. [Real-Time Level-of-Detail Rendering with ReSTIR (SIGGRAPH 2026)](https://research.nvidia.com/labs/rtr/publication/wang2026levelofdetail/wang2026levelofdetail.pdf)
   maps path vertices across changing topology using UV-space partial bijections and multiplies the
   shift Jacobian by the per-vertex mapping Jacobian. Its implementation holds one LOD per object per
   frame. The paper says its formulation does not require that restriction and lists per-ray LOD as
   future work. It also reports residual error from UV imprecision and inter-LOD normal differences.
   This is the closest direct predecessor and makes any extension a high bar.
2. [Locally-Adaptive Level-of-Detail for Hardware-Accelerated Ray Tracing (SIGGRAPH Asia 2023)](https://doi.org/10.1145/3618359)
   already selects tessellation detail independently for primary and secondary rays and preserves
   watertightness in a specialized acceleration structure. Therefore, per-ray LOD and secondary-ray
   adaptation are not novel by themselves. Its representation is a pre-generated tessellation
   hierarchy, and it does not establish ReSTIR reservoir transport between heterogeneous mesh cuts.
3. [Level-of-Detail for Production-Scale Path Tracing (2015)](https://diglib.eg.org/server/api/core/bitstreams/67704986-a9f7-44a7-afe1-3fdeb6c6a267/content)
   already uses ray diameter for path-tracing LOD, including primary and secondary rays.
4. [Stochastic Levels of Detail with DXR (2020)](https://developer.nvidia.com/blog/implementing-stochastic-lod-with-microsoft-dxr/)
   preempts random per-ray transitions between adjacent LODs.

The bounded search found no direct publication combining arbitrary nested triangle-mesh cuts,
per-hit LOD within a frame, and ReSTIR path-space reuse across those heterogeneous cuts. That is a
search result, not proof that no such work exists. The new claim would have to be the estimator and
its measurable benefit after the above methods are held as controls.

## Falsifiable experiment

Use the public [ReSTIR-LoD implementation](https://github.com/elite-sheep/ReSTIR-LoD) as the
renderer baseline if it can be made to run on WARP. Start with a very small scene and resolution;
do not port a renderer before this gate succeeds.

Compare:

- object-wide LOD with the published ReSTIR-LoD mapping;
- per-ray LOD without reuse;
- per-ray LOD with naive reuse, as an artifact control;
- the proposed per-hit mapping and density-corrected ReSTIR reuse;
- high-sample path tracing at matched render time and as a converged reference.

Measure independent-run image MSE/variance and bias against the reference; LOD-map support and
shift failure rates; temporal error around LOD-field changes; reservoir reuse rate; and full-frame
time and memory on real DXR hardware. WARP may be used for estimator correctness and small variance
screens only. WARP is a CPU software renderer and cannot support GPU performance claims.

Kill the direction if (a) the proposed mapping cannot preserve the target path measure, (b) it does
not beat object-wide ReSTIR-LoD at equal geometry and rendering budgets, or (c) support failures
force nearly as many fresh paths as the baseline. Do not treat a lower variance with biased results
as a win.

## Local feasibility evidence

On this Windows 11 system, `d3d12.dll` is version `10.0.26100.9818`. A read-only COM capability
probe created the explicit `Microsoft Basic Render Driver` WARP adapter and a D3D12 device, then
queried `D3D12_FEATURE_DATA_D3D12_OPTIONS5`; it returned `RaytracingTier = 11` (Tier 1.1). Normal
DXGI `EnumAdapters1` also listed this WARP adapter at index 3 with the software-adapter flag. The
Windows SDK includes `dxc.exe` under
`C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\dxc.exe`.

Microsoft documents the adapter selection through `IDXGIFactory4::EnumWarpAdapter` and states that
updated WARP supports ray tracing. Falcor 8.0 is the renderer version named by ReSTIR-LoD, and its
device API supports selecting an adapter index. However, the headless ReSTIR-LoD Python path has not
yet been shown to select the software adapter, and no ray-tracing dispatch has been run locally.
Thus WARP has passed a **device-capability gate only**, not an application or rendering gate.

## Decision

This is currently the strongest new lead because the 2026 ReSTIR-LoD paper explicitly identifies
per-ray LOD as future work, while the 2023 ray-tracing LOD paper supplies a strong selector baseline.
Confidence remains low-to-medium: estimator correctness, WARP integration, useful quality gains, and
real-GPU total cost are all unproven. No production C++ was changed and no software tests were run.

## Superseding correction (2026-11-17)

The “per-ray ManyMesh LOD” framing above is inaccurate for the current implementation: ManyMesh
selects one frame-frozen spatial cut, and every ray sees that cut. ReSTIR-LoD says its formulation
does not require one LOD per object per frame, so mixed cuts alone do not imply a new estimator.
NVIDIA `vk_lod_clusters` and RTXMG already cover streamed spatial cluster LOD and path tracing; a
public non-peer-reviewed renderer report also describes combining such a system with ReSTIR DI/GI.
See [`RESTIR_MIXED_CUT_PRIOR_ART_CORRECTION_20261117.md`](RESTIR_MIXED_CUT_PRIOR_ART_CORRECTION_20261117.md).

Do not treat this screen's candidate as a novel per-ray estimator. The follow-up map-composition
idea was also downgraded after finding progressive-mesh and bijective fine-to-coarse mapping prior
art; see [`RESTIR_MIXED_CUT_PRIOR_ART_CORRECTION_20261117.md`](RESTIR_MIXED_CUT_PRIOR_ART_CORRECTION_20261117.md).
The separate reuse-aware collapse-order hypothesis remains low confidence. No renderer experiment
or SIGGRAPH-level result has been established.
