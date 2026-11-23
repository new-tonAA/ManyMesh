# Tiny learned proposals for memory-capped strict-gate DAG construction (2026-11-19)

## Question

Can the lightweight learned-mesh route and the on-demand / low-memory DAG route form one
useful algorithm? The candidate is not a network that directly edits the mesh. A tiny predictor
would order ready-to-build parent groups by expected value per byte/work; the ordinary simplifier
would still construct each parent, and exact topology, authored-attribute, boundary, and geometry
gates would still decide whether it can be published. Accepted parents would be appended to a
disk-backed graph and their temporary state released. Until a parent is available, its children
remain the exact-cover cut. The target is a better complete-cut quality versus peak-RSS versus
total-work frontier under a hard memory budget.

This is a plausible systems/algorithm interface: learning allocates scarce construction effort,
while deterministic geometry code preserves validity. It does not establish novelty by itself.

## Relevant prior art boundary

The broad halves are already occupied. Neural Mesh Simplification learns vertex selection and
triangulation ([CVPR 2022 paper](https://openaccess.thecvf.com/content/CVPR2022/papers/Potamias_Neural_Mesh_Simplification_CVPR_2022_paper.pdf));
MeshCNN uses topology-preserving edge-collapse pooling ([SIGGRAPH/TOG 2019 paper](https://arxiv.org/abs/1809.05910));
and learned importance for edge-collapse/QEM is also explored in recent work ([GNN-guided QEM, 2026](https://www.mdpi.com/2227-7390/14/10/1610)).
Out-of-core hierarchical simplification already runs with only a cluster and its shared-vertex
neighbors resident ([Eurographics 2006 paper](https://diglib.eg.org/bitstream/handle/10.2312/egt.20061059.0107-0277/0107-0277.pdf?isAllowed=y&sequence=1));
an earlier out-of-core edge-contraction extension also uses learned linear classifiers to partition
large meshes ([2015 paper](https://www.jstage.jst.go.jp/article/iieej/45/3/45_318/_article/-char/en)).
Therefore neither “learned simplification,” “learned partitioning,” nor “out-of-core hierarchy” is
a defensible contribution.

The only potentially differentiating target left by this screen is a *strict-gate, budgeted
construction scheduler* whose predictions improve the measured complete-cut quality/RSS/work
frontier over non-learned schedulers and an oracle bound, on held-out authored meshes. A successful
result would need to show that the learned decision exploits interaction among ManyMesh's exact
gates, dependency structure, and memory residency in a way that simpler benefit/cost policies do
not. This is a research question, not a novelty claim.

## Cheap retrospective screen

`probe_learned_parent_admission.py` extracts 14 hand-designed features from four existing
regroup-pilot diagnostic captures and fits a 15-parameter logistic model. Each asset is held out in
turn. The label is whether a historical parent group was promoted. The work estimate is
`inputTriangles * observedAttempts`; it is not measured time or memory.

- Mean average precision is 0.934 versus 0.678 for a boundary-only ranking. This says the model
  ranks historical promotions on these four captures; it does not establish usable scheduling.
- At a 10% input-triangle skip budget, retained promotion recall is only 69.5% Cloth, 100% Material
  Sphere, 95.0% Monkey, and 93.9% Shapes. At 20%, it is 60.9%, 94.7%, 82.5%, and 90.4%.
- A threshold calibrated to 95% recall on the training assets has zero missed promotions on only
  two of four held-out assets. Mean estimated work saved is 31.2%, but this is dominated by unsafe
  skips: held-out Cloth recall is 62.5% while estimated work saved is 92.1%.
- Even a hindsight zero-miss cutoff, which is an optimistic diagnostic and cannot be deployed,
  saves 7.1%, 68.7%, 23.0%, and 11.9% estimated work on Cloth, Sphere, Monkey, and Shapes.

This rejects the naive policy “predict promotion and skip low scores.” The model has no observed
peak-RSS labels, raster quality deltas, parent dependencies, later-level propagation, or complete
cut composition in this screen. Promotion is not equivalent to marginal quality value: a parent
can pass all gates yet contribute little to the best complete cut, and skipping one parent can
change the value or feasibility of its ancestors.

## Decision and next falsification gate

Keep the two routes conceptually joined, but do not implement a learned runtime scheduler yet. The
current evidence is a negative feasibility screen for skipping builds. If revisited, train a
resource-aware priority (not a binary admission classifier) on measured marginal complete-cut
benefit, wall work, and incremental peak bytes, conditioned on currently available memory and
ancestor/descendant readiness. Always retain exact-gate fallback and publish only independently
valid parents.

Before a runtime prototype, use a frozen DAG/outcome replay to build the comparison table for the
same hard budgets: FIFO/fixed-level order, smallest-work-first, boundary/QEM heuristic, learned
priority, and a clairvoyant upper bound. The replay must honor dependencies and recompute complete
cuts; if the learned method cannot improve that frontier over the best simple policy on held-out
assets, close this combination. Only then consider a small runtime prototype measuring process
peak RSS, disk traffic, time to first valid cut, final work, and raster quality. Memory headroom
must be checked before any build or renderer run.

## Reproduction

```powershell
python tools/mmgeo/probe_learned_parent_admission.py --out out/learned-parent-admission-20261119/screen.json
```

The captured inputs are the four `out/quality-witness-current/*-regroup-pilot-200k/diagnostics.json`
files and their sibling `lod_graph.json` files. The output is intentionally ignored under `out/`.

No mesh was changed, no C++ implementation was added, and no SIGGRAPH-level contribution is
claimed by this screen.

## Dependency-aware frozen-outcome replay

The recorded successful groups map one-to-one onto output nodes in all four production graphs
(302/302). I added `probe_dependency_aware_dag_scheduler.py` to replay candidate order while
honoring these parent dependencies. For every replay state it descends from graph roots through
unavailable parents and checks that the resulting cut covers every original leaf exactly once.
At 10%, 20%, and 50% of the retrospective triangle-work budget, learned priority achieves mean
triangle reductions of 41.1%, 55.5%, and 63.5% relative to the no-build cut. The matched fixed-level
results are 37.6%, 51.9%, and 62.4%; smallest-work-first gives 22.4%, 40.8%, and 61.1%; and the
boundary heuristic gives 33.6%, 47.0%, and 62.3%.

This first learner is a limited positive signal, but its scalar promotion/reduction score is not a
quality-frontier win. At 10%, 20%, and 50% budgets, its mean maximum accumulated-error proxy is
0.0366, 0.0499, and 0.0650; the boundary heuristic is 0.0325, 0.0367, and 0.0505. At 20% budget,
the scalar learner Pareto-dominates the boundary policy on none of four assets and fixed-level on
only one.

## Quality-aware score screen

I extended the replay with two tiny ridge regressors trained only on promoted groups in the three
training assets: one predicts triangle-reduction fraction and one predicts accumulated-error
increment. The scheduling score is predicted promotion probability times predicted triangle
reduction per work, divided by predicted output error to a fixed exponent. The exponent sweep
`{0.5, 1, 2}` is exploratory and was not selected on a separate validation set.

At 10% budget, exponent 0.5 gives mean triangle reduction 41.1% and maximum-error proxy 0.0255;
at 20%, exponent 2 gives 52.9% and 0.0266. For comparison, at 20% the fixed-level, smallest-work,
and boundary policies give (51.9%, 0.0443), (40.8%, 0.0381), and (47.0%, 0.0367). The alpha-2
learner Pareto-dominates the boundary policy on 3/4 assets, smallest-work on 3/4, and fixed-level
on 2/4. Across the explored budgets, learned policies are not uniformly best; the selected
exponent changes the tradeoff.

The error regressor itself is not yet reliable. Its leave-one-asset-out MAE is better than a
training-mean predictor on only Shapes (0.00289 vs 0.00486); it is slightly or materially worse on
Cloth (0.00360 vs 0.00284), Material Sphere (0.00281 vs 0.00271), and Monkey (0.00319 vs 0.00303).
The reduction-fraction regressor beats the mean baseline on all four assets. Thus the lower
complete-cut error proxy could come from a useful ranking interaction, but it does not establish
that the model learned to predict error cost. This remains an exploratory four-asset replay with
post-hoc exponent sweep, a DAG accumulated-error proxy rather than rendered image error, and work
estimated as `inputTriangles * attempts`; it measures no RSS, I/O, or wall time. The clairvoyant
feasible scheduler uses actual historical outcomes and is not an optimality bound.

Decision: keep the joint direction alive as a falsifiable candidate, not a contribution claim. The
next gate is a pre-registered quality-aware scoring rule calibrated without the held-out asset,
tested on more held-out meshes, then checked with a small runtime measurement of complete-cut
raster error, peak RSS, I/O, and wall time. If a simple boundary/QEM priority matches the learned
frontier, close the learned component. The current captures are only four assets, and Material
Sphere has just 35 production groups, so no generalization conclusion follows.

Reproduce with:

```powershell
python tools/mmgeo/probe_dependency_aware_dag_scheduler.py --out out/learned-parent-admission-20261119/dependency-replay-quality-aware.json
```

## Frozen rule on additional geometries

I fixed the inverse-error exponent to `1.0` and evaluated it on six geometries that were not used
to select that exponent: Pirate, Crease, Smooth, Thin, Torus, and UV. One capture per source mesh
was selected, avoiding the repeated 1-thread / 4-thread runs and alternate Shapes partitions as
false independent assets. The frozen rule was evaluated against fixed-level, smallest-work,
boundary, and hindsight priorities with the same exact leaf-cover replay check.

Pirate is the only new geometry with enough production groups to make this a useful ranking check
(152 groups, 38 promoted). At 10%, 20%, and 50% work budgets, the frozen learner reduces the
no-build cut by 24.1%, 37.5%, and 45.1%; fixed-level gives 24.4%, 38.7%, and 45.2%. The learner's
maximum-error proxy is 0.03534, 0.03534, and 0.04795, versus fixed-level's 0.03534, 0.03745,
and 0.04795. At 20%, it trades 1.2 percentage points of triangle reduction for a lower error
proxy than fixed-level, and Pareto-dominates the boundary heuristic (33.8% / 0.04795). It does not
beat the strongest simple baseline overall. The other five new meshes have only 3–5 production
groups each; their schedulers make identical choices at most budgets and provide no useful
ranking evidence.

Decision: the pre-fixed learner does **not** clear the out-of-sample benefit gate. Keep this as a
negative result and do not start a runtime or high-memory build for this policy. The earlier
development-set frontier gain is not robust on the only sizable additional geometry. A new
candidate must first show a clear frozen-rule win on multiple independent meshes with enough
groups, then be evaluated on raster loss and measured resources.

Reproduce with:

```powershell
python tools/mmgeo/probe_frozen_quality_aware_cross_asset.py --out out/learned-parent-admission-20261119/frozen-cross-asset.json
```

## Exact-cut-teacher imitation (2026-11-19)

The exact finite cut oracle exposes parent IDs in its selected dependency closure. I tested whether a
small model trained on that global cut signal can outperform the earlier local promotion/error
predictor. For each training asset, the teacher labels a parent by how often it appears in an exact
best cut across six work budgets and three fixed per-asset promoted-parent error quantiles. The
student sees only the 14 pre-build group features. All labels for the held-out asset are excluded
from that fold; the per-asset thresholds are computed only to construct that asset's teacher labels.
The replay keeps the same dependency readiness, work proxy, and complete-cut reconstruction checks.
For equal work/triangle states the oracle keeps one deterministic representative, so different
equally optimal parent sets can yield noisy selection-frequency labels.

On four leave-one-asset-out folds and 24 asset/budget points, the oracle-imitation student strictly
dominates the existing quality-aware policy at only `1/24` points; the existing policy dominates it
at `7/24`. At the 15 points where the student's max accumulated-error proxy is no worse, it uses an
average of 272 more triangles (signed gain, defined as existing-policy triangles minus student
triangles). It avoids strict domination by fixed-level, smallest-work-first, and boundary at 19/24
points, but that count includes ordinary Pareto tradeoffs and is not a win rate. This target shift
therefore does not produce a robust cross-asset improvement.

The first exploratory version used error caps produced by a learned quality policy; that could leak
the held-out asset indirectly through cross-fold model fitting. I discarded that result and fixed
the teacher targets to within-asset error quantiles before rerunning. The corrected reproduction is:

```powershell
python tools/mmgeo/probe_oracle_guided_dag_scheduler.py --state-limit 6000 --out out/exact-cut-frontier/oracle-guided-fixed-quantiles-loao.json
```

## Deterministic error-slack priority screen (2026-11-19)

I tested a non-learning alternative to the quality-aware learned priority. Each policy received the
same hard maximum accumulated-error cap, and the replay reconstructed the complete cut after every
budget. The new policy ranked a ready parent by normalized child-error slack divided by a cheap
pre-build attempt proxy (`1 + locked fraction + boundary edges per triangle + maximum child
boundary fraction`), with estimated input work as the tie-break. A graph-wide audit verified that
all internal-node accumulated errors are at least their maximum child error before the replay
allowed over-cap child states to be pruned.

Across four captured meshes, three asset-local error quantiles, and six work budgets (72 points per
policy), every output respected its cap and exact leaf coverage. The slack rule strictly dominated
the quality-aware rule at 4/72 points; quality-aware strictly dominated slack at 4/72. Mean triangle
reduction from the no-build cut was 13,680 versus 14,191 for quality-aware, and mean gap to the
exact feasible frontier was 659 versus 147 triangles. Boundary priority was stronger than slack
on average (13,805 reduction; 533-triangle oracle gap). Thus this rule does not improve the current
hybrid policy screen.

The replay uses exact captured attempt work for budget accounting, while its proposed priority uses
only a rough geometric proxy. Error caps are chosen from each asset's captured successful-parent
error distribution, so this is a controlled replay contract, not an online threshold predictor.
Accumulated error is only a proxy for rendered quality; the result measures no wall time or RSS.
Reproduce with:

```powershell
python tools/mmgeo/probe_slack_aware_cut_scheduler.py --state-limit 6000
```

The corresponding ignored JSON is `out/exact-cut-frontier/slack-aware-cut-replay.json`. Decision:
close this standalone slack-priority idea. It does not resolve the combined-route question: the
separate learned-shortlist plus deterministic path-loss evaluator also lacks a held-out quality or
end-to-end cost gain (see [hybrid path-loss screen](HYBRID_LEARNED_PATH_LOSS_20261119.md)). A
defensible combined direction remains a tiny model that proposes candidates while a deterministic
geometric evaluator and explicit validity checks make final decisions, but it needs new paired
assets/paths and measured end-to-end savings before it merits integration.

The exact teacher is an upper-bound labeler, not a runtime oracle. It knows which historical parent
builds succeeded and optimizes accumulated error, not rendered image error. A broader claim of
learning DAG task priorities is also preempted by existing work such as
[*Learning to Schedule DAG Tasks*](https://arxiv.org/abs/2103.03412); any remaining distinction would
need to be a measured complete-cut gain under ManyMesh's strict gates. Decision: close this
oracle-imitation variant unless a larger, path/asset-held-out dataset reveals a specific feature
signal absent from the current captures. No C++ changes, builds, renderer runs, controlled
process-RSS measurements, or SIGGRAPH contribution are established here.
