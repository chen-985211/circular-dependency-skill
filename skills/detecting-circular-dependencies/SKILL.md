---
name: detecting-circular-dependencies
description: Use when checking whether selected code modules, packages, files, services, layers, or imports participate in circular dependencies, architecture-layer cycles, dependency direction problems, boundary drift, blast-radius risks, or bug risks caused by dependency loops in a local project. Use especially before refactors, architecture cleanup, code review, or when the user asks to find user-visible bugs from dependency or cycle analysis.
---

# Detecting Circular Dependencies

## Core Principle

Treat circular dependency analysis as graph analysis over real internal import edges. A selected module participates in a circular dependency only when it belongs to a strongly connected component, including a direct self-loop; reachability from or to some unrelated cycle is not enough.

Use circular dependency findings as entry points, not as the final answer. After detecting cycles, inspect the highest-risk edges for blast-radius bug patterns: contract drift, hidden coupling, shared state pollution, boundary leaks, temporal coupling, and semantic duplication.

## Analysis Modes

- **Detection mode**: Check whether files, directories, packages, services, or layers participate in cycles. Use this when the user asks only for circular dependency status.
- **Risk review mode**: Use cycle and layer evidence to identify architecture risks and likely bug paths. Use this when the user asks about blast-radius risk, boundary drift, "change one thing and break many things", or bug risks from dependency analysis.
- **User impact mode**: Translate confirmed or likely bugs into user-visible behavior. Use this when the user asks what a finding means from a user's perspective.

## Workflow

1. Define the module boundary before analyzing: file, directory, package, library, service, or architectural layer. If the user names a broad module, choose the closest graph level (`file`, `directory`, `package`, or `layer`) and map broad selectors to source files.
2. Prefer the project's native dependency analyzer when it is already configured. Read `references/language-strategies.md` for ecosystem choices and resolver caveats.
3. When no native analyzer is available, run the bundled static detector from this skill directory:

```bash
python3 scripts/detect_cycles.py /path/to/project --module src/foo --ignore-tests --ignore-type-only --json
```

Repeat `--module` for multiple targets. Selectors may be paths, module names, basenames, or globs. Omit `--module` only when the user asks for all cycles. Use `--level directory`, `--level package`, or `--level layer` when the user is asking about architectural direction instead of a specific file loop.

For layer checks, provide a no-dependency JSON config or inline layer definitions:

```json
{
  "layers": {
    "domain": ["src/domain/**"],
    "app": ["src/app/**"],
    "infra": ["src/infra/**"]
  },
  "allowed": ["app -> domain", "infra -> domain"]
}
```

```bash
python3 scripts/detect_cycles.py /path/to/project --level layer --layer-config layers.json --json
python3 scripts/detect_cycles.py /path/to/project --level layer --layer domain=src/domain/** --layer infra=src/infra/** --allow-layer infra->domain --json
```

If `--level layer` is used without `--layer-config` or `--layer`, the detector uses root `layers.json` when present.

When checking a specific layer, `--module` may name the layer directly:

```bash
python3 scripts/detect_cycles.py /path/to/project --level layer --layer-config layers.json --module domain --json
```

4. Let the detector infer common project configuration first. It reads root `tsconfig.json` / `jsconfig.json` `compilerOptions.paths`, and treats Python `src/` layouts as package roots. If aliases are missing or generated elsewhere, pass them explicitly:

```bash
python3 scripts/detect_cycles.py /path/to/project --module src/app --alias @=src --json
```

Use `--no-auto-config` only when inferred configuration is known to be misleading.

5. Inspect each reported cycle path and the import edge evidence. Use the detector's `cycle_kind` (`runtime`, `type-only`, `dynamic`, or `mixed`) as the starting risk classification, then refine it for test-only, generated, or external context. Re-run without `--ignore-type-only` or `--ignore-tests` when those distinctions matter.
6. Report the answer with evidence, not just a yes/no:
- selected module boundary
- graph level and detected resolver configuration
- exact cycle path or "no cycle involving selected module"
- layer violations when `allowed` / `--allow-layer` rules are configured
- source file and line for each edge
   - caveats about unsupported languages, dynamic imports, aliases, barrels, or generated files
   - likely architectural risk and the smallest safe break point

## Continuation Guidance

After any Detection mode response, always offer the full follow-up flow, even when no cycles are found. Keep the offer short and concrete so the user can continue without writing a new prompt from scratch.

- If high-risk cycles, layer violations, or directory/package loops are found, offer to inspect the top dependency paths for concrete user-visible bugs using `references/bug-review-playbook.md`.
- If only low-risk type-only/test-only/local cycles are found, offer to check whether any shared contracts, boundary leaks, temporal coupling, or semantic duplication could still create blast-radius bugs.
- If no cycles are found, offer a non-cycle blast-radius scan focused on shared contracts, global/shared state, hidden coupling, import-time side effects, cache invalidation, duplicated semantics, and unclear error contracts.

Use this wording unless the user already asked for bug review:

```text
Next step: I can continue into the full blast-radius bug review: inspect the highest-risk dependency paths if any exist, then scan non-cycle risks such as shared contracts, hidden coupling, shared state, temporal coupling, and semantic duplication, and report concrete user-visible bugs separately from architecture risks.
```

## Follow-up Bug Review Workflow

When cycles, layer violations, or directory/package dependency loops are found and the user asks for a bug review, inspect only the highest-risk cycles first. If no cycles are found but the user continues into the full flow, run a non-cycle blast-radius scan using the same playbook patterns. Read `references/bug-review-playbook.md` before reviewing code for blast-radius bug patterns.

Prioritize:

1. `runtime` or `mixed` cycles over `type-only` cycles.
2. Directory, package, or layer cycles over small local file cycles.
3. Cross-context edges such as app/context/platform, UI/domain/infra, renderer/main/worker, client/server, or service/adapter boundaries.
4. Edges involving side effects, adapters, filesystem, persistence, process/session state, IPC, event buses, lifecycle/bootstrap, terminal/stream handling, caches, delete/write operations, or shared contracts.

For each high-risk cycle:

1. Read the source and target files for the key import edge and at least one caller on each side when behavior is unclear.
2. Determine whether the dependency path suggests contract drift, hidden coupling, shared state pollution, boundary leaks, temporal coupling, or semantic duplication.
3. Report only findings with concrete code evidence. Separate confirmed bugs from architectural risks and speculative concerns.
4. Explain the user-visible behavior for each confirmed or likely bug.
5. Include a verification idea that would reproduce or falsify the finding.
6. Do not modify code unless the user explicitly asks for a fix.

## Risk Ranking

- **High**: Runtime or mixed cycles crossing architecture boundaries, ownership boundaries, persistence, filesystem, IPC, process/session state, worker/main/renderer, lifecycle/bootstrap, caches, or delete/write semantics.
- **Medium**: Directory, package, or layer cycles that blur ownership, force bidirectional knowledge, or make a future refactor likely to touch multiple contexts.
- **Low**: Type-only cycles, test-only cycles, generated-code cycles, or local utility cycles without runtime side effects.

Inspect the top two to five high-risk paths for bug review unless the user asks for exhaustive analysis.

## Reporting Format

Start with a one-line conclusion:

```text
Conclusion: Small/Medium/Large check, code not modified. File-level runtime cycles: yes/no. Directory/package/layer cycles: yes/no.
```

Then include the relevant sections:

1. File-level runtime cycles.
2. Type-only, dynamic, or mixed cycles.
3. Directory/package/layer cycles and layer-rule violations.
4. Highest-risk architecture loops.
5. Bug-review candidates, if the user asks for bug review or blast-radius risk.
6. Confirmed findings, with severity, evidence, risk pattern, user-visible behavior, verification idea, and suggested fix direction.
7. Non-bug architecture risks, kept separate from confirmed bugs.
8. Verification, caveats, and the continuation guidance next step when the response stops after Detection mode.

Use this finding shape when reporting bugs:

```text
[P1/P2/P3] Title
Evidence: file:line
Risk pattern: Contract Drift / Hidden Coupling / Shared State Pollution / Boundary Leak / Temporal Coupling / Semantic Duplication
Why this follows from the dependency path:
User-visible behavior:
Verification idea:
Suggested fix direction:
```

## Bundled Detector

`scripts/detect_cycles.py` is a no-dependency, best-effort analyzer for Python and JavaScript/TypeScript:

- Python: parses `import`, `from ... import ...`, relative imports, package `__init__.py`, and `TYPE_CHECKING` imports.
- JS/TS: parses static `import`, `export ... from`, `require(...)`, dynamic `import(...)`, relative resolution, `index.*`, root `tsconfig` / `jsconfig` paths, and optional aliases.
- Graph levels: `file` by default, `directory` for folder ownership checks, `package` for Python package / JS directory ownership checks, and `layer` for configured architecture boundaries.
- Exit code `0`: no selected-module cycles. Exit code `2`: selected-module cycles found. Exit code `1`: invalid arguments.

Use `--json` when integrating with further tooling or when the final answer needs exact structured evidence.

## Professional Checks

- Do not declare "no cycle" from text search alone. Confirm with a graph/SCC result or a native analyzer.
- Distinguish "module is in a cycle" from "module depends on something that is in a cycle."
- Treat type-only and test-only cycles as lower risk, but still report them if they can affect builds, bundling, or code generation.
- If native tooling and the bundled script disagree, compare resolver settings first: `tsconfig` paths, package exports, Python path, monorepo workspace aliases, build-generated sources, and case sensitivity.
- For code review findings, include the smallest concrete import edge that can be inverted, moved behind an interface, split into a neutral module, or converted to a type-only dependency.
