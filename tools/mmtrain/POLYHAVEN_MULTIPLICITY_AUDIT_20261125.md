# Poly Haven multiplicity robustness audit

Completed 2026-11-25. This is a post-hoc statistical audit of the
already-published 21-model screen. It neither selects a method nor
changes the frozen asset cohort. Positive effects favor ManyMesh.

## Method

The family contains the 16 original endpoints: four image metrics
(PSNR, SSIM, LDR-FLIP, and silhouette XOR), two matched-face controls,
and two sampling modes. Views are averaged within asset, assets within
connected source group, then whole groups are resampled. A shared set
of 200,000 bootstrap draws preserves dependence across endpoints.
The centered bootstrap max-|t| critical value gives two-sided
familywise 95% simultaneous intervals. The bootstrap is an uncertainty
model over this selected cohort, not random sampling of all possible meshes.

LPIPS is excluded because it was added post hoc in a separate supplement.
Its interval remains descriptive and does not affect the primary family.

## Results

The max-|t| critical value is 2.4327. All simultaneous upper bounds below zero: **True**.

| Mode | Control | Metric | ManyMesh improvement | Individual 95% CI | Simultaneous 95% CI |
|---|---|---|---:|---:|---:|
| native | qem_preserve_border | psnr_db | -2.09768 | [-2.57062, -1.61066] | [-2.71222, -1.48313] |
| native | qem_preserve_border | ssim | -0.003263 | [-0.00434833, -0.00212801] | [-0.00468823, -0.00183776] |
| native | qem_preserve_border | flip | -0.00146464 | [-0.00198005, -0.000919584] | [-0.00214402, -0.000785263] |
| native | qem_preserve_border | silhouette_xor_fraction | -0.00035401 | [-0.000449233, -0.00026135] | [-0.000474677, -0.000233344] |
| native | meshoptimizer_lock_border | psnr_db | -2.27025 | [-2.69701, -1.81556] | [-2.83386, -1.70664] |
| native | meshoptimizer_lock_border | ssim | -0.00515502 | [-0.00629923, -0.00397476] | [-0.00664987, -0.00366018] |
| native | meshoptimizer_lock_border | flip | -0.0020717 | [-0.00254192, -0.00158379] | [-0.00268804, -0.00145536] |
| native | meshoptimizer_lock_border | silhouette_xor_fraction | -0.000315345 | [-0.000393584, -0.000238921] | [-0.000414267, -0.000216423] |
| msaa4 | qem_preserve_border | psnr_db | -4.4545 | [-5.37973, -3.46835] | [-5.67872, -3.23029] |
| msaa4 | qem_preserve_border | ssim | -0.00317018 | [-0.00423732, -0.00205391] | [-0.00457257, -0.00176779] |
| msaa4 | qem_preserve_border | flip | -0.00158074 | [-0.00213485, -0.000988207] | [-0.00231578, -0.000845695] |
| msaa4 | qem_preserve_border | silhouette_xor_fraction | -0.000387482 | [-0.000475025, -0.000297703] | [-0.000501496, -0.000273468] |
| msaa4 | meshoptimizer_lock_border | psnr_db | -5.39636 | [-6.23454, -4.44095] | [-6.54854, -4.24418] |
| msaa4 | meshoptimizer_lock_border | ssim | -0.00516863 | [-0.00626635, -0.00401531] | [-0.00661827, -0.003719] |
| msaa4 | meshoptimizer_lock_border | flip | -0.00228961 | [-0.00278904, -0.00176626] | [-0.0029478, -0.00163142] |
| msaa4 | meshoptimizer_lock_border | silhouette_xor_fraction | -0.000378463 | [-0.000455571, -0.000297614] | [-0.000479514, -0.000277413] |

## Limits

This does not turn the fixed-view Iris Xe comparison into an equal-time,
mobile, temporal, or user-preference result. The candidate cohort was
conditioned on static topology and exact-face boundary eligibility.
The bootstrap intervals quantify source-group variation in these 21
assets; they do not prove generalization to the wider mesh population.

The machine-readable receipt preserves the input hash, seed, endpoint
definitions, group means, and simultaneous intervals. See the [JSON receipt]
(polyhaven_multiplicity_audit_20261125.json) and [analysis script]
(audit_polyhaven_multiplicity.py). Reproduce with:

```powershell
python tools/mmtrain/audit_polyhaven_multiplicity.py
```

Input SHA-256: `e3c15f56f13ea6c0b8f21a131f1d76ed648884e8ff69aca72346a0620e4fd9ad`.
