# Bug Review Playbook

Use this reference only after cycle, layer, or dependency-direction evidence exists and the user asks for bug review, blast-radius review, or user-visible impact.

Treat the dependency finding as a lead. Do not call something a bug unless code evidence shows a real behavior mismatch, state hazard, or user-facing failure mode. If the evidence is weaker, label it as an architecture risk.

## Review Loop

1. Pick the highest-risk dependency path, not every path.
2. Read the key import edge and the caller paths that exercise both sides.
3. Ask which behavior is supposed to be stable across entry points.
4. Look for one of the six blast-radius patterns below.
5. Report confirmed bugs separately from likely bugs and architecture risks.
6. Explain the user-visible behavior and a verification idea for every confirmed or likely bug.

## Pattern 1: Contract Drift

Shared contracts include DTOs, API responses, database rows, enums, config shapes, command names, route names, event payloads, and error conventions.

Bug signals:

- One side treats a field as required while another treats it as optional.
- Two entry points use the same operation name but return different shapes or error modes.
- A database or persistence field has a new meaning but old callers still read it.
- Error handling is inconsistent: throw, return null, return Result, or swallow errors.

Likely user-visible behavior:

- A feature works in one UI path but fails through another path.
- Data appears saved but later loads incorrectly.
- Error messages disappear or become misleading.
- Old projects, sessions, or cached data break after an upgrade.

## Pattern 2: Hidden Coupling

Hidden coupling is a dependency that is not visible in the function signature or type surface.

Bug signals:

- Magic strings for event names, command names, storage keys, routes, channels, or feature flags.
- Dynamic registration, reflection, plugin discovery, or import-time registration.
- A caller must know a special order, sentinel value, or naming convention.
- Build-generated files or barrels hide the real edge.

Likely user-visible behavior:

- Clicking a command does nothing.
- A handler is missing only in one runtime or package build.
- A rename or move silently breaks a feature at runtime.
- A plugin, route, or menu item appears but does not execute.

## Pattern 3: Shared State Pollution

Shared state includes globals, singletons, process state, session registries, caches, front-end stores, environment variables, and mutable module-level variables.

Bug signals:

- Multiple windows, sessions, workers, or requests share one mutable object.
- Cleanup for one flow can remove state used by another flow.
- A cache is written through one path and read through another with different assumptions.
- Tests need global resets or depend on execution order.

Likely user-visible behavior:

- State from one session appears in another.
- Reconnect, refresh, or multi-window use shows stale content.
- A setting or auth state flips unexpectedly.
- A long-running task receives output or cancellation from the wrong session.

## Pattern 4: Boundary Leak

Boundary leaks happen when one layer or runtime knows details owned by another: UI knows database shape, domain knows framework adapters, infrastructure imports application code, or worker/main/renderer paths share implementation details.

Bug signals:

- A dependency cycle crosses UI/domain/infra, app/platform/context, client/server, worker/main/renderer, or service/adapter boundaries.
- A fallback adapter has different semantics than the primary adapter.
- Cross-cutting logic such as auth, telemetry, retry, transaction, or cache invalidation is embedded in core business flow.
- A large module owns unrelated IO, state, business rules, and presentation concerns.

Likely user-visible behavior:

- The same action behaves differently in desktop, web, headless, worker, or remote control surfaces.
- Delete/save/sync/import/export semantics differ by entry point.
- A feature works only when launched through one shell or runtime.
- Refactors cause unrelated screens or commands to change behavior.

## Pattern 5: Temporal Coupling

Temporal coupling means correctness depends on order: import before use, initialize once, register before dispatch, subscribe before emit, hydrate before render, or restore before append.

Bug signals:

- Module import performs side effects such as registration, connection, config reads, global writes, or listener setup.
- A lifecycle hook assumes another module already initialized.
- Reconnect, hot reload, retry, or restore paths use different order than cold start.
- A stream, snapshot, or cache mixes append and replace semantics.

Likely user-visible behavior:

- Cold start works but reload, reconnect, or resume fails.
- Terminal, log, or stream output is duplicated, reordered, or lost.
- A command works once but fails on the second invocation.
- A feature fails intermittently depending on startup timing.

## Pattern 6: Semantic Duplication

Semantic duplication is copied or parallel logic whose names match but meanings drift.

Bug signals:

- Two implementations of the same action use different side effects.
- One path soft-deletes while another permanently deletes.
- One path replaces state while another appends.
- Cache invalidation, derived data, indexing, or search updates exist in only one copy.
- Tests overfit implementation details and miss cross-entry behavior.

Likely user-visible behavior:

- Users cannot recover data they expected to be recoverable.
- Search, lists, counters, or previews stay stale after a write.
- Output appears twice or includes old content after restore.
- A bug appears only in a secondary UI, CLI, worker, or background path.

## Finding Template

Use this shape for each confirmed or likely bug:

```text
[P1/P2/P3] Title
Evidence: file:line
Risk pattern: Contract Drift / Hidden Coupling / Shared State Pollution / Boundary Leak / Temporal Coupling / Semantic Duplication
Why this follows from the dependency path:
User-visible behavior:
Verification idea:
Suggested fix direction:
```

Severity guide:

- **P1**: Data loss, security/privacy issue, corrupted persisted state, or action with irreversible side effects.
- **P2**: User-visible incorrect behavior, duplicated/lost output, broken workflow, or cross-entry semantic mismatch.
- **P3**: Lower-risk inconsistency, maintainability risk with plausible user impact, or fragile behavior requiring a specific condition.

## Reporting Discipline

- Prefer two strong findings over many weak suspicions.
- Name the dependency path that led to the bug.
- Include file and line evidence for the behavior, not only for the import edge.
- Say "architecture risk" when the impact is plausible but not proven.
- Do not recommend a large rewrite when a smaller boundary, adapter, type-only import, neutral module, or contract test would address the issue.
