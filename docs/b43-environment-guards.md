# B4.3: environment failures do not enter business repair

B4.3 inherits B4.2 and addresses the B3 failure chain: npm ETARGET, database repair
editing the root manifest, missing frontend dependencies, repeated model repair and
deployment building only the backend. Original B4-series archives remain unchanged.

- Package manifests, lockfile, root npm configuration, TypeScript scaffold configuration
  and deploy.sh are read-only to model file tools, including explicitly writable scopes.
- Compiler recovery restores only scaffold workspace identities and build/start scripts;
  it retains dependency additions and unrelated fields. Restored fields are audited in
  `.arc/environment_repairs.jsonl`. This contract targets the current fixed scaffold.
- The template includes the tested 284-entry lock graph and installs Playwright upfront.
  Existing user lockfiles are not deleted or replaced. The graph has passed an offline
  npm-ci dry run; this does not prove a remote registry or Linux binary download is available.
- Installation has at most two attempts, the second refreshing registry metadata through
  the same configured registry. It never asks a business model to resolve npm failure.
- A real Node probe checks backend/frontend resolution, native SQLite, Vite/plugin imports,
  and TypeScript's actual resolution of `vite/client` and Node types. Runtime resolution
  of `vite/client` alone is insufficient because that subpath is a type export.
- The full pipeline probes immediately after scaffolding, before the first model stage.
  Database runtime repair starts only after this probe succeeds. Frontend compilation
  and E2E execution also probe before their checks; browser installation failure blocks.
- `EnvironmentBlocked` propagates past local model loops, task continuation and group
  splitting. The compiler marks all later stages `BLOCKED_ENVIRONMENT`; CLI exits 1.
  Business assertion failures retain the normal repair/continuation behavior.
- Deployment requires both built frontend index.html and backend server.js before start.

Evidence: `.arc/environment.json`, repair journal and `.arc/compilation.json`. Environment
GREEN means the fixed runtime dependencies are executable, not that business behavior is
correct. The real browser/HTTP tests and final builds remain required.

`ARC_B4_ENVIRONMENT_GUARDS=0` disables the guard mechanisms for controlled experiments;
the frozen dependency template and deploy artifact checks still belong to this version.
Model/reasoning/credential defaults remain unchanged. No paid inference is needed for:

```sh
python -m unittest discover -s tests -p test_b43_environment.py
```

Persistent registry failures now end early with explicit evidence. They are not silently
turned into successful applications or zero-failure test reports. Platform quality, actual
billing and composite-score gains remain unmeasured until the next controlled submission.
