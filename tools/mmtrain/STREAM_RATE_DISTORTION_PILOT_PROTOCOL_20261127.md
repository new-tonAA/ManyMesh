# Progressive LOD byte-to-quality pilot protocol

Status: frozen single-asset development pilot. This evaluates the current
uncompressed `.mmb` page layout as a transfer representation; it is not a
compression method claim or an end-to-end network benchmark.

## Question and gate

For an exact 50% face cut, can the current ManyMesh page stream use at least
10% fewer complete geometry bytes than the best static meshoptimizer or Draco
control while keeping mean LDR-FLIP within 0.001 of that control? Include the
source vertex data required by the selected nodes, the MMLG bootstrap metadata,
and every fetched page. If the one-asset development result is dominated, stop
this file layout as a compression candidate before spending the held-out set.

The gate is a pilot filter only. A pass would require a larger frozen train /
validation / test study and a real transport test. A failure closes only the
current raw-page accounting and settings; it does not falsify progressive mesh
streaming in general.

## Frozen asset and build

- Development asset: Thingi10K file 84736, 10,580 faces, train split, CC BY.
  Its source URL, license, and SHA-256 come from
  `out/thingi10k-metadata/meshes/download_manifest.json`.
- `mmgeo` input is a temporary OBJ exported from that STL by trimesh 4.5.3.
  Keep the STL and OBJ hashes in the receipt.
- Build one balanced DAG using the checkout's `mmgeo` executable, page size
  65,536 bytes, and default DAG settings. Score only its exact 5,290-face
  selected cut. The requested 25% export misses its face budget and is excluded
  as ineligible; do not include it in the quality frontier.
- Candidate, source and graph outputs are development-only. Do not access the
  Thingi10K validation or test split in this pilot.

## Strong static controls

Encode (a) the full source mesh and (b) an exact 5,290-face meshoptimizer
simplification with the pinned Draco 1.5.7 Edgebreaker and meshoptimizer 0.18.1
vertex/index codecs at 8, 11, 14 and 20 position bits. Count each full Draco
stream and both meshoptimizer streams plus its 32-byte header. The simplified
control must pass the same topology and boundary checks; otherwise report its
quality as unavailable, not as a win or loss.

The source mesh, meshoptimizer cut and ManyMesh cut share one source reference,
camera list and geometry-only renderer. They have no UVs or authored normals.
This intentionally measures geometry only; materials and other attributes are
outside the pilot.

## Quality and byte accounting

- Render eight fixed orthographic azimuths at 192 x 192 with 4x pixel
  supersampling, flat grayscale, and the same full-source reference. Record
  LDR-FLIP at 67 pixels per degree, PSNR, SSIM, coverage MAE and silhouette
  XOR for every view and aggregate.
- For ManyMesh, count the serialized MMLG prefix through the node-offset
  table, every 65,536-byte page touched by the selected node IDs, and 12 bytes
  for each unique referenced source position (float32 XYZ). The generated
  vertex records and canonical position table are already in the prefix.
  Also report the individual node-record sum and a page-size sensitivity at
  1, 4, 16, 64 and 256 KiB.
- Report HTTP Range request counts separately. Do not invent header bytes,
  network latency, GPU time, or a time-to-quality result. The pilot's byte
  totals exclude HTTP/TLS framing, materials and texture payloads.
- Record topology, face-count eligibility, graph and input hashes, codec
  versions, per-view measurements, encode/decode costs and peak memory where
  available. Keep missing measurements explicit.

## Decision limits

This reused development asset is not a confirmation result. A dominated pilot
closes the current file layout only. A pilot pass does not establish asset
generalization, actual network improvement, mobile performance, perceptual
preference, or novelty over progressive mesh and meshlet-streaming systems.
