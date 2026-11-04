# B3 flow batching

This candidate starts from B0 compiler revision `e529ae516a2f231e41439b750dfb5b88f7e20657`.
The initial checkout uses the documentation cleanup on main; its compiler matches B0.
It does not inherit B2's deterministic stage 11 or merged acceptance-first workflow.

Stage 12 separately authors process scenario suites, then groups adjacent requirements
sharing pages or API contracts. Each group gets original requirement contexts,
canonical interfaces, shared owners and relevant sources. One implementation loop
can edit related frontend and backend code together. It replaces per-requirement
implementation loops; it is not an extra generation pass.

Groups preserve requirement order. Defaults: four requirements and 60,000 estimated
task-context characters per group. One oversized requirement remains intact.
The size limit estimates metadata, not full prompt characters or tokens. This is
resource grouping, not a proven semantic dependency scheduler.

Tests are read-only during group repair. Each group checks current and earlier
accepted scenario suites, related UI suites, and full backend regression when
backend sources change. Every selected process suite must execute nonempty cases
without skips/flaky passes. Failed groups restore source and path-index snapshots;
later groups are attempted. Final B0 regression and its separate original-requirement
independent acceptance phase remain in place.

Other mechanisms:

- Remove exact repeated source excerpts and retained semantic records, without model
  summaries, requirement truncation or a new reference language.
- Generate tool examples from actual readable paths, without permission expansion.
- Supply shared API owners, source requirements and write obligations to API design;
  original schema and coverage validators remain authoritative.
- Derive localization hints from failed checks, excluding successful log inventories.
  Hints identify sources/contracts; they do not establish causality.
- Count logical calls including read/discovery loops: 32/file task, 32/design,
  48/group by default. Four consecutive unchanged acceptance failures stop that
  task explicitly. SDK retries retain B0 behavior and are outside these counts.
  Before any group edits, a failed UI presentation check can be re-observed once
  before calling the model; both results are retained. Final complete checks still run.

## Controls

`ARC_AGENT_PROFILE=b3` is default; `b0` disables the mechanisms for debugging.
Use the frozen B0 ZIP for an exact historical-source comparison.

Independent boolean settings (`0`/`1`): `ARC_B3_FLOW_BATCHES`,
`ARC_B3_SHARED_CONTRACTS`, `ARC_B3_CONTEXT_REUSE`, `ARC_B3_SCOPED_TOOLS`,
`ARC_B3_FAILURE_EVIDENCE`, `ARC_B3_BOUNDED_REPAIR`.

Positive integer settings: `ARC_B3_FLOW_SIZE`, `ARC_B3_FLOW_CONTEXT_CHARS`,
`ARC_B3_MAX_TASK_CALLS`, `ARC_B3_MAX_DESIGN_CALLS`, `ARC_B3_MAX_FLOW_CALLS`,
`ARC_B3_MAX_SAME_FAILURES`.

`.arc/b3_flow_plan.json` records groups; `.arc/b3_metrics.jsonl` records context
character sizes, accepted/stalled tasks and group states. Character savings are
not token or monetary savings. Standard model usage logs remain available.

## Validate and package

```sh
python -m unittest discover -s tests -p test_b3_flow_batches.py
python team-tools/package-baseline.py --variant B3
```

Packaging requires committed compiler sources and refuses to overwrite releases.
Task inputs, generated sites, logs, credentials and environment files are excluded.
The platform still supplies API configuration. Model, reasoning and maximum-output
defaults are unchanged from B0. Earlier-stage service recovery remains B0's existing
behavior; B2.2R1's deferred service-recovery scheduler is not included in this candidate.

Offline tests and scripted-model browser/HTTP replay establish mechanism and
integration behavior, not real-model quality or official score improvement.
Compare platform composite score, attributable fees, pass rate, completion and
runtime on the same task/version.
