# ReSTIR-LoD UV Transport Preflight

Date: 2026-11-16. A local geometric/map-support diagnostic, not a ReSTIR experiment.

## Question

Does ordinary ManyMesh LOD generation leave holes or non-reciprocal nearest correspondences in the
shared UV domain, creating a basic transport-support problem that a new simplification objective
could solve?

## Inputs and procedure

The existing Release `mmgeo.exe` built four LOD chains from the repository's Torus, Monkey, Sphere,
and Cloth OBJ assets. Requested parameters were `--mode chain --levels 4 --ratio 0.65
--target-error 1 --dump-obj 1 --dump-format obj --write-dag 0`; achieved triangle counts are reported
below because target/error gates stopped some chains early. The executable SHA-256 was
`46B5AB1FE0CBF2AB9C2E1EB900FD94DFB7DF08665EDDCE955118849E96774900`.

For each finest-to-coarser transition, `measure_lod_uv_transport.py` drew 10,000 deterministic
samples weighted uniformly by the source triangles' UV area. It found target triangles containing
the same UV, chose the nearest world-space point (consistent with the correspondence tie-break in
ReSTIR-LoD), then measured forward support, nearest-map round-trip consistency, normalized position
displacement, geometric face-normal angle, and target/source area Jacobian. The diagnostic script
SHA-256 is `C15B87A5D102DA2C632D82EB60BB2E5EC88B589A96D24C7870AC33BAB75E1D42`. Every JSON report binds
its source/target OBJ hashes and the executed script hash.

| Asset | Source → target triangles | Faces removed | UV support | Ambiguous target hits | Nearest round-trip | p95 displacement / bounds | p99 normal angle | p99 area Jacobian |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Torus | 1,152 → 748 | 35.1% | 100% | 0% | 100% | 0.60% | 6.5° | 1.33 |
| Torus | 1,152 → 486 | 57.8% | 100% | 0% | 100% | 2.13% | 44.1° | 1.65 |
| Monkey | 15,744 → 12,070 | 23.3% | 100% | 0.14% | 100% | 0.11% | 8.6° | 1.21 |
| Monkey | 15,744 → 11,702 | 25.7% | 100% | 0.17% | 100% | 0.13% | 9.0° | 1.25 |
| Sphere | 8,064 → 5,240 | 35.0% | 100% | 0% | 100% | 0.06% | 4.7° | 1.32 |
| Sphere | 8,064 → 3,406 | 57.8% | 100% | 0% | 100% | 0.16% | 4.9° | 1.41 |
| Sphere | 8,064 → 2,214 | 72.5% | 100% | 0% | 100% | 0.32% | 9.0° | 1.46 |
| Cloth | 74,976 → 73,012 | 2.6% | 100% | 62.4% | 100% | 0.04% | 9.2° | 1.15 |
| Cloth | 74,976 → 72,814 | 2.9% | 100% | 62.9% | 100% | 0.05% | 6.7° | 1.14 |

All nine transitions had zero unsupported samples and 100% pointwise nearest round trips. With 10,000
successes, the one-sided 95% binomial upper bound on a missed-sample rate is about 0.03% per row; this
does not prove zero holes. Cloth has substantial overlapping UV support (about 63% of sampled points
hit multiple target faces), even though the nearest branch was reciprocal for the sampled points.
The reciprocal check is local and finite; it is not a proof of a globally continuous partial
bijection. The displacement, normal, and Jacobian distributions are weighted by UV area, not camera
visibility, BSDF, path contribution, or ReSTIR reservoir weight.

Reproduce a chain with:

```powershell
out/cmake-vulkan/tools/mmgeo/Release/mmgeo.exe assets/models/sphere/sphere.obj `
  --out out/restir-lod-map-preflight-20261116/sphere --mode chain --levels 4 `
  --ratio 0.65 --target-error 1 --dump-obj 1 --dump-format obj --write-dag 0
```

Then measure the maps, repeating `--target` for every coarse LOD:

```powershell
python -I tools/mmgeo/measure_lod_uv_transport.py `
  --source out/restir-lod-map-preflight-20261116/sphere/lod0.obj `
  --target out/restir-lod-map-preflight-20261116/sphere/lod1.obj `
  --target out/restir-lod-map-preflight-20261116/sphere/lod2.obj `
  --target out/restir-lod-map-preflight-20261116/sphere/lod3.obj `
  --samples 10000 --seed 20261125 `
  --out out/restir-lod-map-preflight-20261116/sphere_uv_final.json
```

The captured reports are:

- `out/restir-lod-map-preflight-20261116/torus_uv_final.json`
- `out/restir-lod-map-preflight-20261116/monkey_uv_final.json`
- `out/restir-lod-map-preflight-20261116/sphere_uv_final.json`
- `out/restir-lod-map-preflight-20261116/cloth_uv_final.json`

## Decision

On these four local assets, ordinary UV-preserving simplification already gives complete sampled
UV support and reciprocal nearest matches, including a high-overlap chart. Therefore “optimize
collapses just to fill UV support or make the nearest UV map reciprocal” is not a supported novelty
claim and is downgraded. The Jacobian and normal tails vary with mesh and reduction level, but this
UV-area proxy cannot establish a ReSTIR weight/variance benefit. That narrower statistical objective
still requires path-distributed samples and an actual ReSTIR renderer; this diagnostic does not test
it. Cloth's chain barely reduced at all, so it is not evidence at a useful face budget.
