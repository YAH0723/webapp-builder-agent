# B4.2: contract-generated transport

B4.2 inherits B4.1 and compiles transport glue from the canonical stage-06 API
contracts. It removes model-owned repetition and transport mistakes while retaining
model-owned business validation, SQL operations, authorization and frontend state.
The feature is general to the repository's React/Express/SQLite stack.

Generated files:

| File | Responsibility |
| --- | --- |
| `backend/src/api/register.ts` | Canonical methods/paths, request adaptation, response status/body/headers |
| `backend/src/api/contract-types.ts` | Request and response TypeScript shapes |
| `frontend/src/generated/api-contracts.ts` | Typed API identities, endpoints and declared response statuses |
| `frontend/src/generated/api-client.ts` | JSON request transport, parameter encoding, query arrays, cancellation |

Missing handlers receive editable `501 Not implemented` TDD stubs with stable paths.
The compiler-owned registry imports every canonical handler. Backend batch tasks
replace their business implementations and cannot modify the generated registry.
Compiler-owned transport code is omitted from implementation context where unnecessary.
Existing custom registries and client/type files are preserved; a custom registry
continues through model-owned wiring. File ownership is tracked by content hashes in
`.arc/contract_codegen.json`. Deliberate external edits release ownership rather than
being overwritten. Unsupported methods, route patterns or response shapes fall back
to normal model-owned wiring, with an explicit report reason.
Contracts with redirect/cache response statuses retain generated server wiring but
use custom browser transport; a generic fetch helper cannot preserve every browser
redirect/cache interaction.

The registry preserves header arrays such as multiple Set-Cookie values, empty
204/304/HEAD responses and explicitly non-JSON string responses. Static routes precede
parameterized alternatives; explicit HEAD precedes GET fallback behavior. Handlers
retain request params/query/body/headers and the actual database connection.

The frontend helper performs one fetch per invocation, without automatic retries or
global deduplication. It encodes route values, rejects missing parameters before any
request, preserves repeated query values, uses browser-managed same-origin cookies,
and returns declared success/rejection statuses with body and Headers. Unexpected
statuses throw an error carrying the actual status/body/headers. It never fabricates
a successful response. Applications still own visible loading/error states, one submit
owner and identity handling. Non-JSON protocols use custom application helpers.

Generated types describe common JSON-schema structures, not runtime validation.
Unsupported references become `unknown`; format and business constraints remain
explicit canonical requirements for the model and tests.

`ARC_B4_CONTRACT_CODEGEN=0` disables the addition for a fresh generated workspace.
Other B4/B4.1 switches remain available. Model/reasoning and credential settings are
unchanged. Compare frozen B4.1 and B4.2 packages on identical platform configurations.

Local validation includes ownership/fallback tests, generic real HTTP/client tests
(identity encoding, route priority, headers, cookies, rejection without writes, empty
bodies and unexpected statuses), a new two-API batch starting from 501 stubs, and
the exported-application cross-layer fault replay. These checks verify mechanisms;
they do not establish actual token, cost, time or official-score improvements.

```sh
# Use an already installed compatible dependency directory, without downloading packages.
# Set ARC_CONTRACT_TEST_NODE_MODULES in your shell, then:
python -m unittest discover -s tests -p test_b42_contract_codegen.py
```

If dependencies are not supplied, the real Node test class is explicitly skipped;
the ownership and schema checks still run.
