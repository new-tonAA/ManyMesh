# Progressive LOD byte-to-quality pilot

Status: **closed for the current raw `.mmb` page representation**. This is a
single training-asset development result, not an end-to-end streaming,
compression-method, mobile-performance, or novelty claim.

## Result

On Thingi10K asset 84736, the 5,290-face ManyMesh cut was Pareto-dominated at
the same face count by Draco 1.5.7 encoding a meshoptimizer 0.18.1
border-preserving 5,290-face cut. The static stream is 11,386 bytes versus
298,612 bytes for the ManyMesh 64 KiB page configuration, and its mean LDR-FLIP
is lower (better): 0.001009 versus 0.003739. Both decoded meshes pass the
topology and boundary checks and have 5,290 faces. The raw page candidate uses
**26.23× more bytes and has worse image quality**.

The strict absolute-FLIP matching set (difference at most 0.001) is empty
because the valid static controls are substantially better than the candidate.
The same-face Pareto dominance is stronger evidence than a matched-quality
pair: the static control uses fewer bytes and improves every reported image
metric. The byte-savings gate therefore fails. Close this raw-page layout as a
compression candidate; this result does not reject progressive streaming in
general.

### Geometry and image quality

The full source STL, not a DAG full-detail cut, is the image reference. All
entries use the same eight orthographic views, 192 × 192 output, 4× pixel
supersampling, flat face-normal lighting, and LDR-FLIP at 67 pixels per degree.
The renderer is a CPU research rasterizer, not Filament or a perceptual user
study.

| Geometry | Faces | Boundary edges | Mean FLIP ↓ | PSNR ↑ | SSIM ↑ | Silhouette XOR ↓ | Coverage MAE ↓ |
|---|---:|---:|---:|---:|---:|---:|---:|
| Source reference | 10,580 | 0 | 0.000000 | — | 1.000000 | 0.000000% | 0.000000 |
| meshoptimizer cut, uncompressed | 5,290 | 0 | 0.000900 | 50.393 dB | 0.999150 | 0.004069% | 0.00004408 |
| ManyMesh cut, uncompressed | 5,290 | 0 | 0.003739 | 40.190 dB | 0.989953 | 0.021362% | 0.00021786 |
| meshoptimizer cut + Draco 14-bit | 5,290 | 0 | 0.001009 | 48.929 dB | 0.999050 | 0.008816% | 0.00006188 |

The 14-bit Draco comparator preserves the exact 5,290-face count and boundary.
Its mean FLIP is 0.002729 lower than ManyMesh's, while the selected ManyMesh
cut itself exactly preserves the source boundary. Per-view metrics and all
codec outputs are in the [raw receipt](STREAM_RATE_DISTORTION_PILOT_20261127.json).

### Encoded static controls

Bytes are complete geometry streams for the stated representation. Meshopt
includes its 32-byte header; Draco uses the complete encoded stream. Rows with
invalid decoded topology are recorded but excluded from the frontier.

| Input | Codec | Position bits | Bytes | Mean FLIP ↓ | Topology eligible |
|---|---|---:|---:|---:|---|
| Full source | meshopt | 8 | 19,248 | 0.009941 | No |
| Full source | Draco | 8 | 8,505 | 0.009939 | No |
| Full source | meshopt | 11 | 26,012 | 0.001870 | No |
| Full source | Draco | 11 | 13,185 | 0.001866 | No |
| Full source | meshopt | 14 | 31,365 | 0.000472 | Yes |
| Full source | Draco | 14 | 19,790 | 0.000472 | Yes |
| Full source | meshopt | 20 | 43,357 | 0.000015 | Yes |
| Full source | Draco | 20 | 31,679 | 0.000015 | Yes |
| Exact 50% meshoptimizer cut | meshopt | 8 | 10,166 | 0.008901 | No |
| Exact 50% meshoptimizer cut | Draco | 8 | 5,197 | 0.008920 | No |
| Exact 50% meshoptimizer cut | meshopt | 11 | 13,859 | 0.002039 | No |
| Exact 50% meshoptimizer cut | Draco | 11 | 8,109 | 0.002037 | No |
| Exact 50% meshoptimizer cut | meshopt | 14 | 16,268 | 0.001011 | Yes |
| Exact 50% meshoptimizer cut | Draco | 14 | 11,386 | 0.001009 | Yes |
| Exact 50% meshoptimizer cut | meshopt | 20 | 22,544 | 0.000900 | Yes |
| Exact 50% meshoptimizer cut | Draco | 20 | 17,208 | 0.000900 | Yes |

All 8-bit and 11-bit decoded variants fail topology checks after quantization;
they are not quality wins or Pareto points. All valid exact-face compressed
meshoptimizer controls use fewer bytes and achieve lower FLIP than the raw
ManyMesh page candidate.

### Page accounting

The 64 KiB cut fetches 29 selected nodes in four ranges. The MMLG metadata
prefix through the node-offset table is 24,880 bytes, the selected node records
sum to 69,148 bytes, and the four fetched page payloads total 242,352 bytes.
The selected nodes reference 2,615 source positions, adding 31,380 bytes of
float32 XYZ data. Total: **298,612 bytes**, excluding HTTP/TLS framing,
materials, and textures. Page packing amplifies the selected node records by
3.50× before adding metadata and source positions.

| Page size | Range requests | Selected page bytes | Complete geometry lower bound |
|---:|---:|---:|---:|
| 1 KiB | 29 | 69,148 | 125,408 bytes |
| 4 KiB | 24 | 97,112 | 153,372 bytes |
| 16 KiB | 12 | 169,508 | 225,768 bytes |
| 64 KiB | 4 | 242,352 | 298,612 bytes |
| 256 KiB | 2 | 483,164 | 539,424 bytes |

Even the smallest tested page setting requires 11.02× the bytes of the
same-face Draco control, before transport framing. These are byte and request
counts only; no network latency or time-to-quality was measured.

## Protocol and limits

- Asset 84736 (Thingiverse item 28675), train split, Creative Commons
  Attribution. Source STL SHA-256:
  `4de846fb7c6ae5259655d89f2cf9c8ef021c234da02efd81df47efa0744a0da4`.
  Derived OBJ SHA-256:
  `b23ac1e5f6a8b513dd87bb2d50584676a0098c9e669fb342eaff5c1e2091cc7c`.
- The 5,290-face DAG cut has 29 nodes, 2,615 referenced source vertices, and
  30 referenced generated vertices. The requested 25% cut missed its face
  budget and was excluded before quality scoring.
- Controls use Draco 1.5.7 Edgebreaker and meshoptimizer 0.18.1 at 8, 11, 14,
  and 20 position bits. Decode timing is the median of 11 in-process codec
  decodes; it is not a frame-time comparison. Peak memory was not measured.
- Host: 13th Gen Intel Core i7-13700H, Windows laptop with WSL2 Linux
  `6.18.58.1-microsoft-standard-WSL2`; Python 3.12.3, NumPy 2.3.4,
  scikit-image 0.25.2, flip-evaluator 1.7, trimesh 4.5.3, and Node.js 22.16.0.
  Python scoring ran under WSL2; codec processes used the local Windows Node
  executable through WSL interop. No GPU, phone, network transfer, or held-out
  asset was involved.
- This result is one asset and eight fixed views. It does not establish
  generalization, user preference, mobile performance, or a result for other
  page layouts or streaming methods.

## Reproduction

The DAG was generated from the derived OBJ with the D-drive WSL build of
`mmgeo`. The generator was built from source revision
`21cef5a92739edd6d1d751417a2c20efe4ec2a2d`; its binary SHA-256 is recorded in
the raw receipt.

```sh
/root/ManyMesh-build/tools/mmgeo/mmgeo \
  /mnt/e/ManyMesh/out/stream-rate-distortion-preflight-20261127/84736/source.obj \
  --out /mnt/e/ManyMesh/out/stream-rate-distortion-preflight-20261127/84736 \
  --mode dag --target-ratio-cut 0.75,0.5,0.25 --page-bytes 65536
```

The Python runner uses the repository's WSL Node bridge so all codec inputs and
outputs are converted to Windows paths for `node.exe`:

```sh
cd /mnt/e/ManyMesh
mkdir -p out/stream-rate-distortion-preflight-20261127/84736/bin
cp tools/mmtrain/wsl_node_bridge.sh \
  out/stream-rate-distortion-preflight-20261127/84736/bin/node
chmod +x out/stream-rate-distortion-preflight-20261127/84736/bin/node
PATH="$PWD/out/stream-rate-distortion-preflight-20261127/84736/bin:$PATH" \
  /root/ManyMesh-build/pytorch3d-cpu-venv/bin/python \
  tools/mmtrain/bench_stream_rate_distortion_pilot.py \
  --manifest /mnt/e/ManyMesh/out/thingi10k-metadata/meshes/download_manifest.json \
  --asset-root /mnt/e/ManyMesh/out/thingi10k-metadata/meshes \
  --candidate-dir /mnt/e/ManyMesh/out/stream-rate-distortion-preflight-20261127/84736 \
  --mmgeo /root/ManyMesh-build/tools/mmgeo/mmgeo \
  --mmgeo-source-revision 21cef5a92739edd6d1d751417a2c20efe4ec2a2d \
  --out /mnt/e/ManyMesh/out/stream-rate-distortion-preflight-20261127/84736/pilot-results.json
```

The runner, Node bridge, codec WASM/JavaScript files, source mesh, graph, and
candidate hashes are pinned in the [raw receipt](STREAM_RATE_DISTORTION_PILOT_20261127.json).
