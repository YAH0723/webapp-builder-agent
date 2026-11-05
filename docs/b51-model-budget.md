# B5.1: per-task inference and complete-request context budgets

B5.1 inherits B5's independent scenario tests, browser journey and environment guards.
It changes inference/context policy, not application requirements or test expectations.
Model identity, endpoint, credentials and SDK retry behavior are unchanged.

| Task | Default requested reasoning | Initial output ceiling |
| --- | --- | --- |
| Routine code edits | none | 48,000 |
| Independent test authoring | low | 48,000 |
| Schema/interface/UI design | low | 32,000 |
| Application repair | low | 32,000 |

Only actual failed application checks count toward escalation. After two such failures,
one repair request per task can request high reasoning, capped at 32,000 output tokens.
Read requests and later repairs cannot repeatedly consume that high-reasoning slot.
Rejected rounds can expand output ceilings, bounded by both the existing global ceiling
and a default 96,000 policy ceiling. Output includes reasoning. Lowering a ceiling alone
is not a claim of savings; truncation stays a failure and never passes the gate.

An explicit `MODEL_REASONING` is preserved unless `ARC_B5_OVERRIDE_REASONING=1`.
The provider may reject reasoning controls and fall back to its defaults; requested
settings are not proof of actual provider reasoning or billed savings.

The input budget measures serialized messages, including instructions, file content,
canonical contracts, original requirements, tool schemas, reads and feedback. The default
is 196,608 characters, not an exact tokenizer count. Exact redundant repair records are
removed only when their canonical counterparts remain complete. Requirements and business
contracts are never truncated.

Large files can become existing-file descriptors with lexical symbols/line numbers. Their
exact content remains available through ordinary read_file ranges. Long reads are paged
with correct line coordinates and an explicit next offset. Deduplication restores actual
read observations when a previously pinned full file becomes windowed. Existing generated
UI elements can be fetched from the advertised index; they are omitted only when that
actual page/element retrieval interface exists. If mandatory context still exceeds budget,
the call is rejected locally for task splitting, without sending an inference request or
retrying the identical oversized input through the local model loop.

Stable tool/read-only file context is serialized before mutable tasks/feedback. Every
request remains self-contained. No hidden server memory, custom reference DSL or guaranteed
cache hit is assumed. API charges still require platform measurement.

Independent switches: `ARC_B5_TASK_REASONING`, `ARC_B5_OUTPUT_BUDGET`,
`ARC_B5_CONTEXT_BUDGET`, `ARC_B5_CACHE_LAYOUT`, `ARC_B5_REPAIR_ESCALATION`.
Set each to 0 to disable. Task-specific modes use `ARC_B5_EDIT_REASONING`,
`ARC_B5_TEST_REASONING`, `ARC_B5_DESIGN_REASONING`, `ARC_B5_REPAIR_REASONING`.
Positive limits: `ARC_B5_MAX_REQUEST_CHARS`, `ARC_B5_EXCERPT_LINES` (160),
`ARC_B5_MAX_POLICY_OUTPUT_TOKENS` (96000), `ARC_B5_ESCALATED_OUTPUT_TOKENS` (32000),
and `ARC_B5_{EDIT,TEST,DESIGN,REPAIR}_OUTPUT_TOKENS`.

Metadata in `.arc/b3_metrics.jsonl` records requested policy, actual serialized character
sizes, omitted files, read pagination and local budget rejections. SDK retries are outside
logical call counters. Zero-network transport tests and a real-browser scripted replay
verify mechanisms; actual model quality, monetary savings and official score remain unmeasured.
