# B6: compact whole-application generation with reusable primitives

B6 is an experimental route for general structured web-app requirements, not a
pre-generated benchmark application. It runs by default on this branch:

```sh
python main.py REQUIREMENTS_DIRECTORY -o NEW_APPLICATION_DIRECTORY
# Preserve the prior B5.1 orchestration for comparison:
python main.py REQUIREMENTS_DIRECTORY -o ANOTHER_DIRECTORY --pipeline classic
```

Use a fresh output directory. Inputs, labels, entities, business routes, startup data
and scenario assertions come from the supplied requirements. No task-name detection,
benchmark solution, or model credentials are bundled.

## What was already reused

Earlier versions copied a React/Express/SQLite scaffold, dependency lock, deployment
and test runners. B4.2 also generated canonical API registration, transport types and
a JSON client from contracts. Those helpers did not implement business behavior.

## What changes

The compact route replaces the thirteen passes with:

1. Parse all original requirement/scenario IDs; deduplicate identical image files.
2. Install the scaffold, versioned reusable runtime, environment guards and real test runner.
3. Analyze every unique referenced image, in batches of up to four originals per request.
4. Make one concise joint business/data/page plan; validate all requirement IDs appear.
5. Independently author one scenario suite from original requirements, plan and image
   evidence, without application source access. Collection and TypeScript checks must pass.
6. Generate the complete backend and frontend together, then build and execute the suite.
   Repair only application sources against actual evidence. Accepted tests stay read-only.
7. Publish the final report from the already executed full gate; do not rerun an identical
   suite merely to mark a separate reporting stage green.

There is no paid automatic fallback to all thirteen passes if the experiment fails.
The default **global budget is twelve logical model calls**, including image batches,
planning, independent test authoring, initial application and all repair/read calls.
SDK transport retries are outside this counter. It is not a billed-token or cost ceiling.
Inputs whose minimum reference batches plus three core calls exceed the budget are
rejected before inference; references are not silently dropped.

## Reusable runtime

The runtime is application code maintained in this repository, copied to the output
and hash-tracked as read-only. Its model-visible API guide is short; repair can retrieve
exact helper sources without copying them into every request.

| Primitive | Responsibility | Application responsibility |
|---|---|---|
| `DocumentStore` | SQLite JSON records, stable IDs, resource namespaces, CRUD, transactions | Field validation, authorization, relationships, filters, pagination, deletion rules |
| HTTP helpers | Async error forwarding, explicit HTTP errors, basic text/integer checks | Actual routes, domain errors, response shapes and access policy |
| `api` | Same-origin JSON requests, cookies, real status/body errors, no retries | Endpoint contracts and state transitions |
| `useResource` | Abortable requests, URL-keyed state, reload and loading/error state | Page composition and mutation timing |
| UI primitives | Layout, accessible field labels, tables, confirmation dialog, notices | Required controls, labels, specialized interactions and visual styling |
| Navigation | History-based links, back/forward, search parameters | Required routes and URL encoding |

Document storage is **optional**, not an automatic relational schema. The generated
application receives the real better-sqlite3 connection and can define SQL tables,
constraints, joins and specialized operations. The framework installs no business
records or permissive generic data API. SQL/schema/startup initialization must be
idempotent. Specialized UI remains application-owned.

Cancellation of an obsolete browser request is not a network failure. The B6 fixture
ignores only Chromium `net::ERR_ABORTED` and Firefox `NS_BINDING_ABORTED`; other API
request failures and page errors remain failures.

## Controls and evidence

- `ARC_PIPELINE=compact|classic` or `--pipeline`: choose the experimental or retained route.
- `ARC_B6_MAX_MODEL_CALLS=12`: total logical requests; no unlimited per-phase budget.
- `ARC_B6_REPAIR_ROUNDS=4`: checked application repair rounds, still within the global budget.
- `ARC_B6_CHECK_TIMEOUT=300`: seconds per build/browser check command. App startup is 60 seconds.
- B5.1 context/inference policy controls still apply to text requests. Explicit user
  model/reasoning/endpoint credentials retain their existing precedence.
- `.arc/compact-metrics.json`: per-request phase, serialized character size and duration;
  character counts, especially image base64, are not token/billing measurements.
- `.arc/compact-plan.json`, `compact-state.json`, `compact-runtime.json`,
  `compact-last-tests.json`, `compilation.json`: plan, hashes, required outcome IDs,
  collected/executed test evidence and final status.

Every original step, plus description-only leaf requirements, needs a collected test
annotation and passing execution. Mapping does not prove assertion quality or official
coverage. Failures preserve actual reports and sources; exit behavior for deployable
partial results is explained below.

Repeat the full gate without models or dependency downloads:

```sh
python team-tools/check-compact.py APPLICATION_DIRECTORY
```

## Local validation and remaining uncertainty

A new generic inventory fixture composes these helpers and uses scripted model
responses through the real TextModel serialization/budget path. It injects a wrong
creation endpoint; independent browser checks fail, a source-only repair corrects it,
and a continuous workflow verifies creation, reload, edit cancellation, rename,
delete cancellation and confirmed deletion. Separate production-build HTTP checks
cover validation/statuses, SQLite restart durability, transaction rollback and resource
namespace isolation. These tests make no paid inference calls.

This demonstrates runtime integration and orchestration. It does **not** measure model
generation reliability, ARC-Bench pass rate, total tokens, billed cost or run duration.
Large joint outputs, one-suite authoring omissions, custom relational behavior and
specialized UI remain risks requiring platform comparison. B6 trades fine-grained
intermediate artifacts for fewer model coordination rounds; it does not publish the
classic schema/API/UI/trigger design artifact families.

If application generation/repair exhausts its budget after publishing sources, B6 can
preserve a partial result for official evaluation. It must first pass a fresh full build
and start the compiled production server against a temporary SQLite database, serving
both `/api/health` and frontend HTML. The report remains `COMPLETED_WITH_FAILURES`, with
`evaluation_ready: true` and separate `compact-deployment.json` evidence; CLI exit 0
permits grading and does not claim acceptance passed. Missing/changed tests or runtime,
environment failures, build errors or startup failure cannot take this path. The probe
does not establish business correctness and makes no model calls.
