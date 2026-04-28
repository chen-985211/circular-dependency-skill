---
name: detecting-circular-dependencies
description: Use when checking whether selected code modules, packages, files, services, layers, or imports participate in circular dependencies in a local project, especially before refactors, architecture cleanup, code review, or when import/build/runtime behavior suggests dependency loops.
---

# Detecting Circular Dependencies

## Core Principle

Treat circular dependency analysis as graph analysis over real internal import edges. A selected module participates in a circular dependency only when it belongs to a strongly connected component, including a direct self-loop; reachability from or to some unrelated cycle is not enough.

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
