# M3 completion checklist (historical)

The original goal was to align temporal M3 experiments with the structure of
NSS / Mob-FGSR, using reproducible measurements. Completed boxes preserve the
historical record. Current research gates are in [MANYMESH.md](MANYMESH.md);
sections 8.7 and 8.8 now live in [the history](MANYMESH_HISTORY.md).

## Learned temporal model

- [x] Add `--export <dir>` to `tools/mmtemporal/temporal.py`: export current coarse
  frame, reprojected history, and full-detail target in a layout compatible with mmtrain.
- [x] Train `stack=1` without history versus `stack=2` with current frame and history.
- [x] Record the comparison: 30.18 versus 29.56 / 28.93.
- [x] Record the conclusion in historical section 8.7.

## History rejection

- [x] Reject reprojected history samples outside the image.
- [x] Add color clipping when current and historical colors differ substantially,
  as a proxy for visibility or shading changes.
- [x] Record that color clipping harmed this experiment: +0.65 became
  +0.02 / +0.07 / +0.21.
- [x] State that pure rotational pan has no parallax or true disocclusion test.
  Translating cameras and depth buffers are needed to test disocclusion.
- [x] Record the conclusion in historical section 8.7.

## Additional training data

- [x] Support a pan sequence per view in `mm_bench`
  (`--views V --jitter N --pan D`); previously one pan covered the entire sequence.
- [x] Generate four sequences of eight frames, below the planned 6x12 because of
  rendering throughput limits.
- [x] Reproduce learning +0.70 dB, temporal +0.95 dB, combined +1.52 dB;
  the reported difference narrowed from +1.25 to +0.57.
- [x] Record the conclusion in historical section 8.8.

## Known limits

- Only four training and two validation views, with one random seed.
- Rotational pan is easier than game cameras with parallax and occlusion.
- The desktop integrated GPU was shared with other tasks; absolute timings are unreliable.
