# mmtrain

Trains and compares reconstruction networks for ManyMesh: coarse geometry goes in, a full
quality picture is supposed to come out.

The question this tool exists to answer is whether the **Geometry Error Map** — the per cluster
error the geometry stage already computes — is worth feeding to the network. Everything else
here is scaffolding for that comparison.

## Data

A directory (default `out/m3`) containing, per view:

| File | Contents |
|-|-|
| `lr_vNN.png` | render of the decimated mesh, the observation |
| `hr_vNN.png` | render of the full mesh, the target |
| `err/vNN/error_map.pgm` | the error the geometry stage projected for that view |

Produced by `tools/mmgeo` (which emits the decimated mesh and the per view error map) and
`samples/mm_bench` (which renders both meshes from the same camera list — run it twice with
the same `--views`, and the pairs line up exactly, because the camera is an explicit
parameter).

## Usage

```shell
python tools/mmtrain/train.py --data out/m3 --model tiny --scale 2 --iterations 1500

  --model bicubic|tiny|espcn|fsrcnn|unet
  --scale N          observation is reduced by N; 1 compares at equal resolution
  --iterations N     default 1500
  --no-error-map     ablation: train with the colour input only
  --out <path>       save the weights and a JSON of the metrics
```

`bicubic` runs no network at all — it is the floor, and it is the number any learned method
has to beat.

## Architectures

| `--model` | Source |
|-|-|
| `tiny` | ours: a few 3×3 convolutions predicting a residual over the observation |
| `espcn` | Shi et al., CVPR 2016, sub-pixel convolution |
| `fsrcnn` | Dong et al., ECCV 2016, shrinking / mapping / expanding |
| `unet` | a small encoder-decoder, as a capacity check rather than a proposal |

`espcn` and `fsrcnn` upsample inside the network, so they take the reduced image directly.
`tiny` and `unet` take a bicubically restored image and predict a residual, which is the
cheaper arrangement for same-resolution restoration.

## What it found

On the Stanford dragon, 20.8% of the original triangles, 16 views (12 train / 4 validation),
CPU only:

| Method | scale 1 (pure geometry) | scale 2 (half res) |
|-|-|-|
| coarse / bicubic (floor) | 31.48 dB | 30.59 dB |
| tiny | **33.36 dB** | **31.57 dB** |
| unet | 33.23 dB | 31.67 dB |
| espcn | 31.90 dB | 29.56 dB |
| fsrcnn | 32.07 dB | 28.69 dB |

**Reconstruction works**: at equal resolution a small network recovers +1.88 dB over the
coarse render, and at half resolution it beats bicubic by about +1 dB.

**The error map does not, yet**: its contribution ranges from −0.19 dB to +0.13 dB and flips
sign between models and between the two tasks — far below anything visible. The diagnosis is
that the map is essentially a silhouette mask (a median of 15/255 over the pixels it covers,
because it is normalised against a pixel budget the mesh is comfortably inside), and the
silhouette is already visible in the colour input. There is also very little error to guide
with: the mesh is already good. See MANYMESH.md §7.3 for the plan.

## What else was tried

| Change | Result |
|-|-|
| `kpn` (Bako et al. 2017 kernel prediction) instead of `tiny` | 31.48 dB vs 33.37 — worse |
| `unet` (176k parameters) instead of `tiny` (28k) | 33.23 dB vs 33.37 — no better |
| 6000 iterations instead of 1500 | 33.42 dB vs 33.37 — converged |
| normalising the error map per view | +0.04 dB — no real effect |
| adding an edge (gradient) loss term | 33.37 → **33.50 dB**, SSIM 0.9797 → 0.9800 |

Kernel prediction is the architecture the literature uses when an auxiliary buffer is meant to
guide a reconstruction, and it is the wrong tool here: a normalised filter can only *filter*,
and what is missing is high frequency geometry detail, which has to be synthesised. That the
best result comes from the smallest model trained the shortest says the limits are elsewhere.

The edge term is worth keeping on: plain L1 is minimised by the median, which for a
reconstruction means a blurred answer that would rather hedge an edge than move it.

## Why the error map does not help

It is not a broken signal. Measured against the actual per pixel difference between the coarse
and full renders, **99.3% of the total error falls inside the pixels the map covers**, and its
magnitude tracks severity monotonically across quartiles (0.0141 to 0.0235).

It is a redundant one. Those errors are all at edges, and an edge that is in the wrong place is
already visible in the colour image. So the map adds about +0.03 dB over colour alone.

For a conditioning input to earn its place it has to carry something the colour does not — the
*signed direction* of the geometry error, say. That is not available at run time: knowing it
means having the full detail geometry, which is what the pipeline exists to avoid.

Which reframes what this stage is: the gain comes from the network's learned prior over high
frequency detail, not from the conditioning. Improving the prior - more data, a perceptual or
adversarial loss - is the productive direction. A better error map is not.

## Fairness note

`espcn` and `fsrcnn` scoring below bicubic here says nothing about those architectures. Their
papers train for a hundred thousand iterations on tens of thousands of images; this runs 1500
iterations on twelve. Treat those rows as "at an equal, very small budget", which is the point
of the comparison — not as a verdict on the methods.
