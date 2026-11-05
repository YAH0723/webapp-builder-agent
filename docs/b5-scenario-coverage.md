# B5: scenario execution mapping and continuous user journeys

B5 inherits B4.3. Independent test authors still reread original YAML and cannot read
application sources. Application repair cannot edit tests or fixture utilities.

Every original leaf step is mapped to static Playwright `arc-step` annotations. Tests
are collected with `--list` before implementation; missing mappings are sent to the
independent author, not to the application repair agent. Final acceptance requires real
passing execution of mapped cases, with no skip/expected-failure shortcut. Reports retain
per-case annotations and outcomes and publish `scenario_coverage` separately from counts.
This checks traceability and execution only. It cannot prove that a generated assertion
correctly expresses the requirement; an annotation is never semantic proof.

One supplemental user journey is planned when at least two original requirements share
an API/page or explicitly mention a known route. Up to four related requirements retain
source order. This resource grouping is not a semantic dependency DAG. The independent
author chooses a meaningful original user flow and writes a separate browser-only suite.
It must carry real object identities and state across operations, navigating/reloading
when required, and must not SQL-seed or directly API-create its intermediate results.
The journey is generated after isolated suites, and its application repair regresses all
previously accepted suites. Failed journey repair rolls back only that repair, preserving
the earlier implementation and reporting the unresolved journey honestly.

Failures additionally expose observed source/API evidence and all original API owners.
The grouped repair agent can address common request/state owners instead of producing
separate patches for each failed case. These are deterministic localization hints, not
proof that every similar timeout shares a cause. There is no global failure cache that
silently skips unresolved requirements.

Independent flags (existing B4 feature namespace): `ARC_B4_SCENARIO_COVERAGE`,
`ARC_B4_USER_JOURNEYS`, `ARC_B4_SHARED_FAILURE_DIAGNOSIS`; set each to `0` to disable.
All are enabled in the default B4-family profile. Model/reasoning settings remain B4.3's.
The journey adds a test-author task and real regression work; total cost improvement is
not assumed. Compare official quality, actual costs and composite scores on the same task.

Local tests include omitted/skipped/failed mapping rejection and a real general Notes
application with an injected request-address fault, isolated requirement cases and a
continuous creation/navigation/persistence journey. Scripted model responses validate
mechanisms; they do not predict real model quality or official scores.
