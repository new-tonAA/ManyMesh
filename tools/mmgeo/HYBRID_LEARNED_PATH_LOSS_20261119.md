# Hybrid learned proposal with exact path-loss evaluation (2026-11-19)

**Archived exploratory result.** The residual-MLP branch was later closed; see
the [research decision](HYBRID_PATH_LOSS_RESEARCH_DECISION_20261119.md). Raw
capture and feature data are ignored under `out/pathloss-captures`, and this
checkout does not contain all helper scripts used by the original screens.
On 2026-11-25, the audit could not be rerun here: Python 3.12's scikit-learn
extension failed to load, while Python 3.10 has no SciPy or scikit-learn. The
numbers below are archived historical results, not a fresh reproduction.

## Decision

The two routes can be combined at the **edge-collapse decision**. Keep the existing legal-collapse generator and filtered depth-envelope event solver. Train a small model to predict the path-integrated image loss of a proposed collapse from its local geometry and visibility-event features. Use the model to rank a large candidate pool; evaluate a short list, plus uncertain or high-risk proposals, with the exact event solver before committing a collapse. A committed operation is therefore still an operation the existing topology/attribute checks accept.

This is a research hypothesis, not a novelty claim. A model that merely imitates QEM, predicts an image score, or speeds up mesh simplification is not enough.

## Why this is the plausible junction

The current exact prototype scores legal local collapses against a shared scene under an orthographic horizontal camera segment. It integrates filtered coverage/depth error over visibility events, and can beat dense local redraw for some measured Monkey neighborhoods. Its limitations are substantial: CPU Python, small image tiles, one-dimensional paths, no material/color error, and mixed results across assets. It is an evaluator, not an end-to-end simplifier.

The direct learning route has a strong prior-art baseline. Potamias et al., *Neural Mesh Simplification* (CVPR 2022), already use a lightweight learned pipeline to choose vertices and triangles, emphasize real-time execution, and report up to 10x speedup over traditional simplification ([CVF paper and abstract](https://openaccess.thecvf.com/content/CVPR2022/html/Potamias_Neural_Mesh_Simplification_CVPR_2022_paper.html)). SIGGRAPH 2024's *Neural Geometry Fields for Meshes* further establishes neural representations built around discrete mesh geometry ([official SIGGRAPH program](https://www.siggraph.org/wp-content/uploads/2024/09/Conference-Papers.html)); its representation task differs from legal-collapse selection. Image-space loss for mesh simplification is also established by Lindstrom and Turk's *Image-Driven Simplification* (SIGGRAPH 2000, [paper](https://faculty.cc.gatech.edu/~turk/my_papers/image_simp_tog2000.pdf)). Continuous visibility along camera segments is established in *Continuous from-Segment Visibility* (TVCG 2025, [paper](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Popescu-TVCG-2025-1DVisibility.pdf)). Thus, neither “lightweight neural simplification,” “image-driven collapse,” nor “camera-path visibility events” is the differentiator.

The narrow candidate distinction is **learning to amortize the exact, filtered source-versus-legal-collapse path-loss oracle**, while retaining exact evaluation for decisions that can change the accepted collapse sequence. The literature search so far is preliminary; this distinction is not verified as new.

## Falsifiable hypothesis

For a fixed asset/path workload, a compact model trained on exact event-integral labels can reduce total simplification time at a fixed final path-image-error budget, because it avoids exact evaluation of most legal candidates. Its advantage must survive held-out meshes and held-out camera paths, and must beat both (a) exact evaluation of every candidate and (b) a non-learned local-feature ranking baseline. If model scoring plus feature construction is not cheaper than exact evaluation at useful recall, this hybrid has no practical point.

### Candidate model

- Inputs must be cheaper than the exact target: scale-normalized local collapse features (QEM cost, edge length, local valence/curvature, affected-face count, projected patch footprint), plus path summaries from a very coarse fixed sample set or cached from already accepted mesh state. Do not feed exact event counts or exact common-envelope queries if computing them costs the work the model is meant to save. No vertex IDs, asset IDs, or camera sample index.
- Target: exact integrated filtered coverage/depth loss for the legal collapse, with the current evaluator's shared common-scene semantics. Train on log loss and pairwise candidate ordering; keep a separate calibrated uncertainty estimate for shortlist/fallback decisions.
- Model: a CPU-only, small MLP over candidate features (initial cap: 3 hidden layers, 128 units; report parameter count and measured peak RAM). It ranks existing legal candidates; it does not emit a mesh or invent connectivity.
- Decision: exact-evaluate top-k and uncertainty-triggered candidates. Only collapse after exact score plus existing legality checks. Measure the complete loop, including feature extraction, inference, exact checks, and topology updates.

The model is deliberately a candidate ranker, not a learned replacement oracle. If exact checks approach the full candidate count, count that as a failed speed hypothesis rather than a successful “hybrid.”

## First experiment, before implementation in the simplifier

1. Freeze capture, candidate, path, raster/filter settings, and script hashes. Generate exact labels for legal candidates across a sufficiently large candidate pool with the current event evaluator. Existing 12-candidate screens are far too small to justify model training. Do not create synthetic mesh/path pairs that leak between train and test.
2. Split by **mesh and camera path**, not random candidate rows. Train on some meshes and paths; report separately on unseen meshes and unseen paths. A second split should hold out both.
3. Compare: QEM/local descriptors; a linear or tree model on the same features; a compact MLP; exact all-candidate ranking. Use identical candidate pools and candidate legality.
4. Report top-1/top-8 recall of the exact best collapse, pairwise ranking error, regret of selected exact loss, final integrated loss versus triangle count after a sequential collapse replay, wall time for the full scoring loop, peak RAM, model size, and the number/fraction of exact calls. Report both cold-start and amortized time, including offline label/training cost. Validate the final mesh with dense raster paths at higher resolution, not only the event solver's own labels.
5. Ablate path/event features, uncertainty-triggered exact checks, and shared-occluder features. Include null-loss and rare-event cases; report the fraction of configurations where the hybrid loses.

## Current signal audit (not a model result)

I added `audit_path_loss_qem_baseline.py` to join existing exact-energy labels back to captured meshoptimizer priorities. It deduplicates identical screen/candidate pools, excludes exact-energy ties within `max(1e-12, 1e-6 * scale)`, gives half credit to tied QEM priorities, and reports both pairwise ranking accuracy and overlap between the exact-minimum and QEM-minimum tie sets.

- In the Monkey seed-30000, 64px screen, lower QEM priority orders only 32/56 non-tied pairs correctly (`57.1%`); its best-priority tie set misses the four-candidate exact-minimum set. At 128px, it orders 33/61 (`54.1%`) and again misses the exact minimum.
- Pirate seed-3000 is much more correlated (`83.6%` of 61 pairs), while Torus seed-2500 is `77.0%` of 61. QEM's minimum tie set misses each exact-minimum set in those two screens.
- The remaining captured screens mostly have exact losses tied at zero under the selected tile/path, so they provide no useful ranking supervision. A newly generated low-poly Cube screen has 57 non-tied pairs; QEM gets 34 correct (`59.6%`) but misses the four-candidate exact-minimum set. A Rounded Cube screen has 52 non-tied pairs; QEM gets 28 (`53.8%`) and its best-priority set intersects the four-candidate exact-minimum set.
- New captures add Camera and Material Sphere. Camera unit 1, seed 360, has 48 non-tied pairs at each of two angles; QEM gets `75.0%` and `83.3%`, respectively, with the same six-candidate exact-minimum tie set at both angles and QEM's two-candidate minimum set inside it. Material Sphere has active silhouette groups with `63.9%` (39/61) and `83.6%` (51/61) pairwise accuracy; QEM misses the exact minimum in the first and selects the unique minimum in the second. Two other Material Sphere views are all-zero, including the same seed at a different angle.
- A Sphere silhouette group adds 61 non-tied pairs; QEM gets 37 (`60.7%`) and its best-priority set misses the exact two-candidate minimum set.

This is weak evidence that the exact path objective can change useful collapse ordering relative to QEM, and that the signal is asset-dependent. It is **not** evidence that a neural model can learn the ordering or that a hybrid is faster. Twelve of twenty-two candidate-pool groups have non-tied pairs, but they cover only eight assets; multiple Monkey, Camera, and Material Sphere screens reuse candidate neighborhoods, and Rounded Cube/Cube are low-poly controls. Most other screen/path settings have null losses and cannot supervise a ranker. There is no held-out path evaluation. The raster-ranking audit now keeps temporal sample counts separate; reproduce the default screens with `python -I tools/mmgeo/audit_path_loss_qem_baseline.py`, and the expanded CPU pilot with `python -I tools/mmgeo/audit_path_loss_qem_baseline.py --captures out/pathloss-captures --results out/pathloss-captures --out out/pathloss-captures/qem-audit.json`. Raw screens are ignored under `out/`.

I added `build_path_loss_feature_table.py`, which joins captured exact labels to 16 inexpensive features (local QEM/geometry, affected-face statistics, projected edge/target footprint, view angle, and path extent). It does not use exact event counts or common-envelope queries as inputs. The current table has 252 rows across 22 candidate groups; 13 groups contain any loss above `1e-12`, while the rest carry no useful regression signal. Recreate it with `python tools/mmgeo/build_path_loss_feature_table.py`; its raw JSON is ignored under `out/`.

## Exploratory leave-one-asset-out MLP

I ran a deliberately tiny CPU MLP (`16, 8` hidden units) on the 16-feature table, holding out every screen from one capture asset per fold. This is an early diagnostic on 8 assets, 22 groups, and 647 non-tied candidate pairs; it is not a final model evaluation.

- Pooled pairwise accuracy: QEM `67.4%`; MLP `63.1%`.
- Exact-minimum tie-set overlap: MLP `6/12` informative groups; QEM `5/12`.
- Mean group-range-normalized top-1 regret: MLP `10.2%`; QEM's **optimistic** best member of each minimum-priority tie set `6.9%`.

The MLP wins more groups on pairwise accuracy (7 versus 5) but loses overall weighted ranking and has worse normalized top-1 regret than the optimistic QEM baseline. The present cheap local-feature model therefore fails the first generalization gate. It does not establish that a path-aware learned proposal is impossible: the feature set has no direct estimate of which changed surface samples survive common-scene occlusion. It does establish that a generic small MLP over local geometry and camera metadata is not enough.

Reproduce with `python tools/mmgeo/pilot_path_loss_ranker.py`; raw fold results are ignored under `out/`. scikit-learn emitted a compatibility warning because installed SciPy requires NumPy below 2.5 while this environment has NumPy 2.5.4; the run completed with exit code 0. No inference-speed, full simplification, or dense held-out rendering measurement was made.

## Coarse raster and exact shortlist screen

The expanded pilot has 13 screens using exactly one temporal raster sample. Across its 388 non-tied candidate pairs, that one-sample raster orders `76.8%` correctly versus `68.3%` for QEM on the same groups. Its aggregate absolute energy error is still `41.8%`, with one screen's worst candidate relative error above `15x`. The raster path measured a median `11.4 ms`, while exact common setup plus scoring all candidates measured `918 ms` (about `75x` slower in this Python prototype).

Exact re-ranking after the raster shortlist recovers only `5/7` informative groups at top-1, top-2, and top-4; top-8 recovers `7/7`. Mean normalized regret after exact re-ranking is `4.9%`, `3.9%`, `3.9%`, and `0%`, respectively. Estimated hybrid times are `0.49 s`, `0.62 s`, `0.73 s`, and `0.84 s`, based on the measured common setup and an assumed linear per-candidate exact cost. These are estimates, not measured hybrid timings; at top-8 the saving versus exact-all is modest, while the smaller shortlist sometimes misses the true best collapse.

I also trained the tiny MLP with coarse raster energy as an input, using group-relative rank targets and leave-one-asset-out evaluation on the five assets with one-sample screens. It reaches only `42.8%` pooled pair accuracy, versus `76.8%` for direct coarse raster and `68.3%` for QEM. Its normalized top-1 regret is `47.1%` versus `4.9%` for coarse raster and `5.5%` for QEM's optimistic tie-set choice. This first learned correction is a clear failure; it does not justify adding a network to the pipeline.

Reproduce the shortlist/raster audit with `python -I tools/mmgeo/audit_path_loss_qem_baseline.py --captures out/pathloss-captures --results out/pathloss-captures --out out/pathloss-captures/qem-audit.json`. Rebuild features and run the coarse-raster MLP diagnostic with:

```powershell
python tools/mmgeo/build_path_loss_feature_table.py
python tools/mmgeo/pilot_path_loss_ranker.py --raster-steps 1 --target group_rank --include-coarse-raster --out out/pathloss-captures/mlp-coarse-rank-loao.json
```

The apparent low-sample speedup is not enough: its energy estimate is poor, top-4 plus exact misses some winners, top-8 saves little, and the learned correction loses badly. Any further hybrid should add a visibility descriptor with a measured cost and beat the direct raster shortlist under the same held-out asset/path split. If it cannot, close this learning branch. This remains a narrow research candidate, not a novelty or SIGGRAPH claim.

### Early stop criteria

Stop before simplifier integration if any of these hold:

- On mesh-and-path-held-out data, the compact model fails to beat the non-learned feature ranker in exact-loss regret.
- To match exact ranking quality, the hybrid must exact-evaluate nearly every candidate, or the combined feature/model/exact cost is not lower than exact-all.
- The speed gain exists only when the same pretrained model and cached path summary can serve enough collapse decisions to amortize model/data preparation; per-mesh training alone may be too expensive.
- Sequential collapse replay accumulates substantially more final image error than exact-all at the same face budget, even after uncertainty-triggered checks.
- The result depends on one asset, a fixed camera angle, or training/test candidates from the same local collapse neighborhood.

Passing this screen would justify an end-to-end prototype, not a SIGGRAPH claim. That prototype would still need broader path families (including perspective), full-frame filtered RGB/material-aware validation, diverse held-out assets, a strong raster/image-driven simplification baseline, and a systems-level CPU/memory comparison.

## Research boundary

The intended output can be a simplified mesh, but the research question is not “can a network output a mesh?” That is established. The question is whether exact event-based filtered path-loss supervision makes a compact, uncertainty-aware proposal stage reliably cheaper while preserving the quality of sequential legal collapses. Until the held-out experiment succeeds and a wider literature search is complete, the SIGGRAPH 2027 objective remains unmet.

## Paired-target residual shortlist follow-up (2026-11-19)

I rebuilt the feature table from the current captured result files so the exact labels and inexpensive collapse descriptors are paired by capture hash and candidate ID. The table has 264 candidate rows in 23 groups across eight assets. I then tested a narrower hybrid: one low-sample raster score is the baseline; a tiny CPU MLP predicts only its log-loss residual from local collapse descriptors; the event solver exactly scores the model's top-K proposals. This asks whether a learner can improve the cheap raster shortlist, rather than asking it to replace the exact objective.

On the 13 groups with one raster sample (five assets, 388 non-tied pairs), QEM, raster, and residual MLP pooled pair accuracies are `66.8%`, `75.3%`, and `77.3%`. The raster top-2 shortlist contains an exact minimizer in `11/13` groups; residual MLP top-2 reaches `12/13`. After exact scoring of the two shortlisted candidates, mean range-normalized regret falls from `2.10%` for raster top-2 to `1.12%` for residual-MLP top-2. At top-4 both methods still miss one group; top-8 recovers all groups. The residual MLP is only a small, provisional improvement over the cheap raster shortlist. The 13 groups are correlated, only five assets are represented, and camera paths are not held out separately.

The broader 23-group run weakens the case: residual MLP top-4 hits the winner in `21/23` groups versus `21/23` for raster, with slightly lower best-shortlist regret (`0.12%` versus `1.19%`); residual Ridge does worse than raster. Direct MLP regression on exact event loss also remains behind raster and QEM. These results depend on which raster budget is used, so they must not be pooled into a single headline.

Reproduce the paired data and one-sample screen with:

```powershell
python tools/mmgeo/build_path_loss_feature_table.py --out out/pathloss-captures/path-loss-features-current.json
python tools/mmgeo/audit_path_loss_residual_hybrid.py --model mlp --raster-steps 1 --out out/pathloss-captures/residual-mlp-1step-loao.json
```

The audit implementation is [audit_path_loss_residual_hybrid.py](audit_path_loss_residual_hybrid.py). It uses asset-held-out folds and exact labels, but does not hold out camera trajectories or perform an interval-certified fallback. It measures ranking/shortlist regret, not end-to-end hybrid runtime. The existing exact solver has substantial common-scene setup, so reducing candidate calls may save only the candidate-stage share. No sequential collapse replay or production simplifier integration was performed. Treat this as a route worth one better-controlled validation, not as a successful hybrid or a novelty result.

### View-direction and joint asset/path holdout

To check whether the asset-held-out gain was path-specific, I added `--split path` and `--split joint` to the audit. The available one-sample data contains only two camera view directions, both with horizontal pan, so this is a coarse view-direction holdout, not a broad camera-trajectory benchmark; path lengths are not held out separately. With a whole view direction held out, the residual MLP top-2 hit rate returned to `11/13`, the same as raster, and its mean normalized top-2 regret matched raster at `2.10%`. With asset and view direction jointly held out, only 11 groups had usable training folds: residual MLP and raster both hit `9/11` at top-2 and have the same `2.49%` mean normalized regret. Thus the earlier `12/13` asset-held-out result does not survive even this limited unseen-view-direction check. The MLP's small apparent gain is not evidence of path generalization.

Reproduce with:

```powershell
python tools/mmgeo/audit_path_loss_residual_hybrid.py --model mlp --raster-steps 1 --split path --out out/pathloss-captures/residual-mlp-1step-path-loo.json
python tools/mmgeo/audit_path_loss_residual_hybrid.py --model mlp --raster-steps 1 --split joint --out out/pathloss-captures/residual-mlp-1step-joint-loo.json
```

These results close the current small-data hybrid as an unsupported contribution: the evidence supports keeping raster-only shortlist as the simpler baseline. A new hybrid attempt needs path-diverse paired labels and a feature/uncertainty target that improves exact shortlist decisions on genuinely unseen trajectories, then must show measured end-to-end savings after common event setup.

As a limited pan-direction check, I also screened the seven 64-sample groups with a held-out view/pan direction. Raster itself already had 7/7 top-1 hits and `100%` pooled pair accuracy; residual MLP also had 7/7, so it added no ranking value. The model's zero regret against the exact labels is not a useful win when the raster baseline already saturates this tiny set. Reproduce with `python tools/mmgeo/audit_path_loss_residual_hybrid.py --model mlp --raster-steps 64 --split path --out out/pathloss-captures/residual-mlp-64step-path-loo.json`. This screen reinforces the decision to stop the present learned residual branch until more difficult, held-out paths show a real gap that a small model can close.
