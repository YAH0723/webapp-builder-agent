# B4.1: local replay and bounded UI design recovery

Runtime change: a failed UI design batch can split once into two smaller batches.
Successful sibling designs are saved; an uncovered requirement still fails the stage.
The initial failure remains in `.arc/ui_design_batches.json`. Other B4 generation
settings, model defaults and independent acceptance remain unchanged.

`team-tools/replay-stage.py` runs a single stage (08–12) with explicit scripted model
responses and real local compiler/tests/builds. It disables real SDK construction,
dependency installation and browser downloads. Use a disposable generated application
with `.arc`, original requirements, installed dependencies and Chromium already present.
Edits, reports and build outputs are applied to that application.

```sh
uv run python team-tools/replay-stage.py --workspace DISPOSABLE_APP --requirements INPUT_DIR --stage 08 --responses responses.json --report releases/replay08.json
```

Responses are an ordered JSON array. Every entry has a `response` object and optional
`expect.task_keys`, `expect.task_contains` and `expect.instructions_contain` assertions.
For example, an existing batch whose tests already exist can replay an empty edit:

```json
[{"expect":{"task_keys":["apis","test_paths"]},"response":{"tool_calls":[]}}]
```

Create/repair scenarios use ordinary flat `edit_file` responses with actual file content.
Add one entry for every expected model round. Unexpected, exhausted or unused responses
fail the replay rather than falling back to a real model. A real stage failure remains
failed; a completed tape alone does not mean its application tests passed.

Reports store initial workload hashes, logical scripted-call counts, supplied-file counts,
request/instruction characters and real elapsed time. Characters are not token estimates.
To compare two local checks/replays:

```sh
uv run python team-tools/compare-local.py first.json second.json --output releases/comparison.json
```

Only matching stage, scope, initial workload digest and check selection are flagged as
comparable. Hardware/process load still affects time. Different initial faults or test
sets are not a controlled comparison. No local replay establishes actual model quality,
API billing or official scores.

Mechanism tests: `python -m unittest discover -s tests -p test_b41_replay.py`.
