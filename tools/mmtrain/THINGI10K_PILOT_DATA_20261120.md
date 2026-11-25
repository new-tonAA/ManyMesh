# Thingi10K pilot data for lightweight mesh learning (2026-11-20)

## What was acquired

The metadata-only screen is now backed by a small, license-audited geometry pilot.
The selection uses one file per Thing, four face-count bands, CC BY/BY-SA, public-domain,
GPL/LGPL, or BSD licenses, and a stable Thing-ID hash split. It selected 32 meshes:

| Split | Meshes | Triangles |
|---|---:|---:|
| Train | 16 | 186,950 |
| Validation | 8 | 86,676 |
| Test | 8 | 74,350 |

Files total 43.38 MiB. The largest is 8.39 MiB; all are below the downloader's 24 MiB
per-file and 160 MiB total limits. Geometry files and the download manifest live under the
ignored `out/thingi10k-metadata/meshes/` directory and are not committed. The manifest keeps
the source URL, file ID, Thing ID, license, split, byte count, and SHA-256 for each file.

## Integrity audit

All 32 file face counts match the selected metadata rows. A streaming STL audit found zero
zero-area triangles, zero edges incident to more than two faces, and edge-boundary counts
matching the published metadata exactly. Two-sided edges had opposite face winding. A small
number of selected meshes are open surfaces; this is allowed by the selection rule, which
requires manifold edges but does not require a closed solid.

The first audit attempt used an incorrect binary-STL vertex offset and was discarded. The
reported audit above uses the correct 84-byte STL header plus 12-byte facet normal offset,
and parses ASCII STL separately. This note records that correction so the failed counts are
not mistaken for a property of the dataset.

## Use and limits

The set is adequate for a laptop-scale pipeline and a strict train/validation/test split, but
not for claiming broad generalization. It contains only 32 Thingiverse objects, lacks a
category-balanced design, and is curated toward clean manifold inputs. It does not represent
the messy non-manifold cases covered by recent "in the wild" simplification work. A model must
beat deterministic QEM and a non-learned feature baseline on the held-out Things, at equal
triangle count, with geometry and rendered-image quality reported separately. No network has
been trained on this set yet.

## Reproduction

Metadata selection:

```powershell
python tools/mmtrain/curate_thingi10k_subset.py `
  out/thingi10k-metadata/geometry_data.csv `
  out/thingi10k-metadata/input_summary.csv `
  --per-bin 8 `
  --seed ManyMesh-2027 `
  --out out/thingi10k-metadata/selected-32.json
```

Bounded download (requires network access):

```powershell
python tools/mmtrain/download_thingi10k_subset.py `
  out/thingi10k-metadata/selected-32.json `
  out/thingi10k-metadata/meshes `
  --split all `
  --max-file-mib 24 `
  --max-total-mib 160
```

Sources: [Thingi10K project](https://github.com/Thingi10K/Thingi10K), [pinned raw-mesh
mirror](https://huggingface.co/datasets/Thingi10K/Thingi10K/tree/1e52df627995ba43b7b91143af4bed86f570037a/raw_meshes).
