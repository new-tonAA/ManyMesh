# Cluster sidecar decoder mechanical screen

Date: 2026-11-21. This is an identity/control result, not trained reconstruction or
a SIGGRAPH contribution. It implements the first mechanical step of the
[decoder protocol](../../MANYMESH_CLUSTER_DECODER_STUDY.md).

## What ran

All 16 training Things from the existing licensed pilot, totaling 186,950 triangles,
were read serially. No validation/test geometry was loaded. Deterministic adjacency
growth partitions these source meshes into 2,427 clusters of at most 128 faces.
This is a control partitioner, not the production DAG or meshoptimizer baseline.
Of 93,256 welded input vertices, 62,698 are free to move; the remainder are locked
at source boundaries or cluster interfaces. The STL corpus contains geometry only.

The persisted shared polynomial basis has 30 float32 latent channels per cluster.
All latents are zero in this screen. Both mesh and model are loaded from saved NPZ
files; sidecars bind their geometry/partition and model hashes. Fixed output preserves
positions, triangles, and cluster IDs. The second variant splits eight faces per
asset at their centroids, adding 16 faces per asset without splitting shared edges.
All 32 decodes pass the current boundary/edge/winding/degeneracy/duplicate/local-flip
checks and exact input-position preservation. The test suite also exercises nonzero
latents and invalid outputs, including displacement cap and local flip rejection.

## Resource observations

| Measurement | Fixed topology | Eight face splits per asset |
|---|---:|---:|
| Total output triangles | 186,950 | 187,206 |
| Total sidecar bytes, including metadata/container | 306,888 | 307,912 |
| Median audited decode time per asset | 0.880 s | 0.907 s |
| Maximum audited decode time | 11.160 s | 11.274 s |

One shared model file is 4,128 bytes, including container overhead; raw weights
are 3,600 bytes. Uncompressed NPZ base files total 8,233,024 bytes; source STLs
total 22,489,529 bytes, mixing ASCII and binary, so that difference is not a
compression comparison. Peak process working set across the serial run is
149,254,144 bytes (about 142.3 MiB). It includes imports, parsing, partitioning,
encoding, and audits; it is neither an isolated decoder peak nor a hard memory cap.

Times include input/model-array validation, sidecar loading, polynomial evaluation,
output construction, and local audits. They exclude imports, STL parsing, clustering,
and model/base file loading. These are one-run observations on the recorded Windows
desktop Python/NumPy environment, not warm-up-controlled performance estimates.
The interpreter-heavy audits and repeated topology construction are expensive; no
low-latency load or low-resource deployment claim is supported by these timings.

## Reproduction and retained evidence

```powershell
python -m unittest discover -s tools/mmtrain -p test_cluster_decoder.py -v
python tools/mmtrain/cluster_decoder_pilot.py `
  out/thingi10k-metadata/meshes/download_manifest.json `
  --out out/cluster-decoder-train-smoke --limit 16
```

The 14 targeted tests passed. The first all-train attempt stopped on an ASCII STL
after one binary asset; ASCII parsing was added and tested against a binary facet
with nonzero normal/attribute bytes to catch vertex-offset errors. The completed
run then processed all 16 assets. The retained
[receipt](cluster_decoder_smoke_20261121.json) includes script, manifest, report,
and source hashes, runtime versions, per-asset costs, source links, and licenses.
Meshes/sidecars/decoded outputs and the original full report remain under ignored
`out/cluster-decoder-train-smoke/`; geometry is not redistributed with this note.

## Limits and next gate

Zero residuals do not reconstruct missing geometry; centroid insertion here does
not change the piecewise planar surface. Thus this screen supplies no quality,
compression, learned generalization, or equal-cost baseline advantage. Synthetic
nonzero-latent tests prove only the exercised mechanical behavior.

The audit does not establish global intersection freedom, vertex-link manifoldness,
authored UV/normal/material preservation, or error relative to a high-detail source.
All remain required before the publication topology/attribute gate can pass.
Next prepare actual coarse/reference training pairs, add deterministic displacement
and refinement controls, and fit a shared decoder on training data only. Model and
latent byte costs, complete load costs, geometry/image quality, and failure rates
must all be measured. Do not evaluate the decoder on test until choices are frozen.
