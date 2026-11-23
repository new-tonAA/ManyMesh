# ManyMesh research continuation prompt

Continue the user's ManyMesh research objective toward SIGGRAPH-quality evidence.
Work in the shared repository and preserve existing changes. Keep repository
material in English and use the user's language in progress updates and replies.
Treat this as one persistent objective across turns: a new message usually
steers the active work rather than replacing it. Read the current worktree and
relevant experiment receipts before relying on an earlier summary.

## Continue with evidence

At the start of each continuation, recover the active goal and inspect the
current repository state. Classify the previous turn as progress, a verified
wait on a live process, or no progress. For a no-progress turn, repeat the
relevant preflight and take the next safe action that can change the decision;
do not merely restate the same blocker or restart a process without checking
its live handle and outputs. Keep the broad goal intact when an individual
experiment is blocked.

Keep the experiment dependency graph explicit. A failed low-cost heuristic
screen closes that heuristic under the tested implementation; it does not
automatically invalidate a separate method hypothesis unless the latter was
pre-registered as conditional on that screen. Conversely, an infeasible
face-count match is not a quality win or loss. Label it as a budget/eligibility
failure, keep it out of quality rankings, and update every downstream gate that
depended on it. Before running a replacement experiment, check whether its
inputs and prerequisite artifacts exist and whether the runnable binary was
built from the source hash being reported.

Before closing an iteration, map every requested deliverable and gate to
current evidence. Label each as verified, contradicted, incomplete, or
unverified. Do not claim completion from a plan, link check, or narrow smoke
test when the requirement calls for an algorithmic result, held-out data, a
device measurement, or a manuscript. Keep the overall objective active until
the actual success criteria have evidence. Mark work blocked only after the
same external blocker recurs for at least three consecutive goal turns and no
independent progress remains; otherwise continue the work that is still
possible.

## Recover the objective

1. Read the latest user instructions, [research status](MANYMESH.md),
   [SIGGRAPH direction and evidence gate](SIGGRAPH_2027_DIRECTION.md), the
   [prior-art screen](docs/manymesh/siggraph-prior-art-screen-20261123.md), and the last
   relevant experiment receipt. If the user provided a reviewer note or
   attachment, read it before continuing when it is available.
2. Identify the smallest open question whose answer could change a research
   decision. Check the [roadmap](MANYMESH_RESEARCH_ROADMAP.md) and existing reports
   for the same mechanism under a different name. Resume unfinished runs from
   their receipts when the inputs match. A closed configuration needs a new
   mechanism or new evidence to reopen.
3. Pick one primary experiment or a concrete evidence gap to resolve. Write one
   sentence stating the mechanism, its strongest comparator, the planned
   resource match, and the outcome that would reject it. Inspect primary sources
   for the closest prior art. Identify the exact claimed distinction or record
   the overlap and redirect the work.

## Execute a decision-making experiment

- Freeze asset identities, license receipts, split, views or camera paths,
  baselines, parameter settings, reference render, metrics, and decision
  thresholds before looking at the candidate results. Use reused assets for
  development. Reserve an independently licensed confirmation set and evaluate
  a frozen method on the held-out test set once.
- Use the strongest relevant baseline. For geometry, include the existing
  QEM/CornerSimplifier and stock meshoptimizer cluster LOD where applicable.
  For image-space methods, include native output, 4× MSAA, SMAA, and
  low-resolution upscaling. For compression, include full payload bytes and
  suitable versioned meshoptimizer or Draco modes. Compare against a measured
  baseline at equal faces, bytes, or time, depending on the claim.
- Keep the camera, shading, transfer function, and reference identical within
  each paired comparison. Report the aggregate and every model. Report
  LDR-FLIP alongside PSNR and SSIM for static raster quality. Add LPIPS when it
  addresses the claim. For geometry, include silhouette and sampled surface
  distance and normals, plus topology and boundary failures. For moving LOD,
  report a suitable full-reference video metric and a switch-local diagnostic
  along frozen camera paths. State when any metric is unavailable.
- Measure the full cost of the changed operation, including auxiliary passes,
  CPU preparation or decoding, complete bytes, and peak memory as relevant.
  Report GPU and CPU measurements under their own units and scope. Pair
  uncertainty over assets after aggregating views or paths. Keep research-only
  proxy results, oracles, and all failed or excluded cases visible in the receipt.
- For each run, record commands, inputs and hashes, hardware and software
  versions, raw per-asset measurements, budget eligibility, and the decision.
  Verify claimed counts and deltas from the raw data. Check the changed files,
  links, and reproduction instructions. Safe retries must preserve the
  comparison conditions and their observation history.
- For a comparative geometry claim, verify the reference mesh, actual candidate
  face counts, strict topology and boundary eligibility, and matched budget
  before scoring relative image quality. Pin the full source mesh separately
  from any DAG full-detail cut; never silently call a hierarchy reference the
  original source. If no eligible pair remains, report the quality result as
  unavailable rather than substituting source-relative diagnostics.

## Close the iteration

- Advance a candidate only when its novelty distinction is defensible and the
  paired results support a repeatable quality–cost improvement against strong
  controls with topology and boundary constraints satisfied. Close a failed
  configuration and state what evidence would change that decision. Keep the
  short status page current and link the dated report for detail.
- Treat fixed-view desktop evidence as desktop evidence. Mobile claims need
  device measurements, and claims about preference need human evidence.
  Keep production C++, the public renderer API, and the `.mmb` format deferred
  under the current research scope until the evidence gate passes.
- Use GitHub when a specific task requires repository, PR, or CI context and
  the account is connected. Honor explicit authorization already given for
  publication; do not ask for it again. Scope each publication to the reviewed
  changes and leave unrelated dirty files out. Use the Taste frontend skill
  for requested website or interactive-demo work. Research figures, geometry
  outputs, and scientific decisions follow their measurement protocol.
- End with the outcome, its limits, the artifact or receipt, and the next
  unresolved decision. Continue authorized work while it advances the objective.
  Honor an explicit pause, a runtime-enforced limit, or a concrete blocker.
  Keep the overall project open until its actual success criteria are met.

## Reusable per-iteration prompt

> Continue the user's full ManyMesh objective; do not shrink it to the easiest
> open task. Inspect the current goal, worktree, remote state, and latest user
> steering before relying on previous summaries. Choose one action that can
> change a research or delivery decision. Check its prerequisites and closest
> prior art, freeze the comparison before scoring, then execute and verify the
> result from raw evidence. Preserve unrelated work. Keep all repository prose
> in English. Publish only reviewed, scoped changes when publication is already
> authorized. Report what changed, how it was verified, its limits, and the
> next unresolved gate. Keep the goal active unless its full success criteria
> are proven or a repeated external blocker leaves no independent work.
