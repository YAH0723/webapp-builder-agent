# B4: batched generation and single independent acceptance

B4 reduces repeated model work in the expensive backend and frontend stages. It
inherits B3's exact context deduplication, permission-consistent tool examples,
canonical API owner evidence and bounded repair loops. It uses general requirement
and interface metadata; no application-specific business rules are bundled.

| Stage | B3 | B4 default |
| --- | --- | --- |
| 08 backend | Test author + implementation per API | Test author + implementation per 5 APIs |
| 09 UI design | One proposal per requirement | One proposal per 6 requirements, complete association maps |
| 10 UI implementation | One page, presentation first | Four pages with canonical API wiring and shared helpers |
| 11 interaction design | Model-generated trigger description | Deterministic validated requirement/UI/API bindings |
| 12 acceptance | Process tests + grouped repair + separate independent acceptance | One independent suite family, four requirements per author/repair group |

Records retain source order, split by item count and 80,000 metadata characters;
an oversized record is retained alone. This limit is not a full prompt token budget.
Canonical API ownership includes all original owner requirements. Every batch must
create its complete set of files; missing members fail. Failed implementation groups
restore source and path-index snapshots and retain failure evidence.

The acceptance author rereads original YAML and sees only original scenarios,
canonical interface metadata, relevant schema and fixed fixture utilities. It cannot
read application sources or implementation-owned tests. Application repair cannot
edit any test or fixture. Each successful group runs current and previously accepted
suites. Final verification attempts every intended acceptance suite, backend HTTP
regression, UI presence regression and builds. Internal GREEN is not an official score.
Batch generation does not prove semantic scenario coverage; generated assertions and
official outcomes still require evaluation.

`ARC_AGENT_PROFILE=b4` is default. `b3` selects earlier orchestration; `b0` disables
optimizations but does not reproduce an immutable historical archive. Each B4 feature
has a boolean switch: `ARC_B4_BACKEND_BATCHES`, `ARC_B4_UI_DESIGN_BATCHES`,
`ARC_B4_UI_IMPLEMENTATION_BATCHES`, `ARC_B4_DIRECT_BINDINGS`,
`ARC_B4_ACCEPTANCE_FIRST`. Direct bindings are used only with acceptance-first.

Positive integer settings: `ARC_B4_API_BATCH_SIZE=5`,
`ARC_B4_UI_DESIGN_BATCH_SIZE=6`, `ARC_B4_PAGE_BATCH_SIZE=4`,
`ARC_B4_ACCEPTANCE_BATCH_SIZE=4`, `ARC_B4_BATCH_CONTEXT_CHARS=80000`,
`ARC_B4_BATCH_CALLS=48`. Existing B3 controls remain available. Logical call limits
exclude SDK transport retries. Plans appear in `.arc/b3_metrics.jsonl`; actual group
checks appear in stage reports. No model, reasoning or credential changes are made.

Larger groups may increase response size and couple failures. One early failure can
roll back a whole group; later groups still run and final reports retain failures.
Failed groups split once into two smaller recovery groups by default; children never
split again. `ARC_B4_ADAPTIVE_SPLIT=0` disables this bounded recovery. Reports retain
the parent failure even when its members subsequently recover.
Single acceptance removes duplicate authoring and a separate automatic test review;
a faulty generated assertion can therefore block its group. This is a deliberate
candidate tradeoff, not a measured improvement. Compare one bundled platform run with
fixed model/settings using official pass count, actual charge, wall time and composite
score. Local mock/replay tests establish mechanisms only.
