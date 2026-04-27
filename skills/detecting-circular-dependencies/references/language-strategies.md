# Language Strategies

Use this reference after the target module and project language are known.

## JavaScript and TypeScript

Prefer existing tools when configured: `madge`, `dependency-cruiser`, Nx project graph, Turborepo package graph, or framework-specific graph commands. Always account for `tsconfig.paths`, package `exports`, barrel files, generated route files, and `import type`.

The bundled detector is useful for quick local checks over relative imports:

```bash
python3 scripts/detect_cycles.py . --module src/features/billing --alias @=src --ignore-type-only
```

If a cycle disappears with `--ignore-type-only`, report it as type-only unless the project transpiler or bundler still treats it as runtime.

## Python

Prefer configured architecture tools such as `import-linter`, `grimp`, or `pydeps` when present. Check package roots, editable installs, namespace packages, and imports guarded by `if TYPE_CHECKING`.

The bundled detector handles common package-relative imports:

```bash
python3 scripts/detect_cycles.py . --module my_package.billing --ignore-tests --ignore-type-only
```

For runtime failures, confirm with the exact entry point or test that imports the module; Python can expose partial-initialization cycles that static analysis only hints at.

## Go

Use the Go toolchain first. Go rejects package import cycles at build time, so `go test ./...` or `go list -deps ./...` is usually authoritative for package cycles. For layered architecture cycles that do not violate package imports, inspect package ownership and interfaces separately.

## Java and Kotlin

Use existing build and architecture tooling: Gradle/Maven dependency graphs, `jdeps`, ArchUnit, or Detekt rules. Clarify whether the user means package-level, class-level, module-level, or build-artifact cycles; those are different graphs.

## .NET

Use solution/project references for build-level cycles and architecture tooling for namespace/class cycles. `dotnet list <project> reference` helps with project edges, but namespace cycles require static analysis or architecture tests.

## Monorepos and Mixed Stacks

First decide the graph level: workspace package, source module, generated artifact, or runtime service. Use package-manager workspace metadata for package cycles and language-specific analyzers for source cycles. Do not mix levels in one conclusion without saying so.
