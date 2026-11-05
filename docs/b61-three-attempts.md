# B6.1: three-attempt recovery and tool-error stop conditions

B6.1 retains B6's compact route, reusable runtime and twelve-logical-request total
budget. It changes retry behavior in shared file editing and design proposals; it
does not change the acceptance oracle, business requirements or test expectations.

- A file task defaults to at most **three edit attempts including the first**,
  even if a legacy caller requests ten. Different failures do not reset that limit.
- Design/proposal validation similarly defaults to three attempts including the first.
- Stable repeated-failure identities cover tool errors and malformed responses,
  as well as executed acceptance failures. Changing a diagnosis, previous output,
  call index or replacement span cannot disguise the same error code/path.
- Permission feedback names the blocked path, permitted existing writable sources
  and whether stage-owned new helpers are possible. It never grants new access.
- Exhausted permission failures are nonretryable. Classic batch recovery does not
  split that failed group to reopen another budget for the same ownership problem.
- Successful read/discovery requests are not failed edit attempts. They still consume
  model calls; B6's twelve-logical-request total limit remains. SDK retries are outside it.
- Environment failures still stop immediately. Exhausted business tasks retain explicit
  failures; only a separately verified deployable partial application may be graded.

Defaults can be explicitly configured for controlled experiments:
`ARC_B3_MAX_EDIT_ROUNDS=3`, `ARC_B3_MAX_PROPOSAL_ATTEMPTS=3`,
`ARC_B3_MAX_SAME_FAILURES=3`, and `ARC_B6_REPAIR_ROUNDS=3`.
Actual file-task rounds are the minimum of the caller's limit and shared edit cap.
The inherited bounded-repair switch controls the shared caps; the packaged default
enables them. Frozen B6/B5.1 ZIPs are unchanged.

Fault injection covers protected-write variants, atomic rollback, feedback paths,
suppression of batch splitting, stale replacement spans, malformed JSON, different
acceptance failures and recovery within the limit. The real inventory browser replay
still repairs its injected wrong endpoint and checks production HTTP and SQLite.

These tests do not establish platform savings or pass-rate improvements. Full-suite
validation is not claimed: inherited `test_file_agent.py` imports removed legacy
`sync_implementations`/`sync_pages`/`sync_triggers` functions and is not part of the
targeted passing suite. New retry tests use current runtime APIs.
