# Circular Dependency Skill

A Codex skill for detecting circular dependencies in local Python and JavaScript/TypeScript projects.

The skill combines a concise Codex workflow with a deterministic, no-dependency static analyzer. Codex uses the workflow to choose the right project boundary and explain the result; the bundled script builds an internal import graph and detects cycles with strongly connected components.

## What It Detects

- File-level cycles, such as `src/a.ts -> src/b.ts -> src/a.ts`
- Directory-level cycles for ownership or feature boundaries
- Package-level cycles for Python packages and JS/TS directory ownership
- Configured architecture-layer cycles, such as `domain -> infrastructure -> domain`
- Optional architecture-rule violations, such as `domain -> infrastructure` when that direction is not allowed
- Runtime, type-only, dynamic, and mixed cycles

## Language Support

The bundled detector supports best-effort static analysis for:

- Python: `import`, `from ... import ...`, relative imports, package `__init__.py`, and imports guarded by `TYPE_CHECKING`
- JavaScript/TypeScript: static `import`, `export ... from`, `require(...)`, dynamic `import(...)`, relative resolution, `index.*`, and root `tsconfig.json` / `jsconfig.json` path aliases

For other ecosystems, the skill guides Codex to prefer native tooling first, such as Go build checks, Java/Kotlin architecture tooling, or .NET project-reference analyzers.

## Install For Codex

Ask Codex to install the skill from this repository:

```text
Install the detecting-circular-dependencies skill from https://github.com/chen-985211/circular-dependency-skill/tree/main/skills/detecting-circular-dependencies
```

Or install it manually:

```bash
git clone https://github.com/chen-985211/circular-dependency-skill.git /tmp/circular-dependency-skill
mkdir -p ~/.codex/skills
cp -R /tmp/circular-dependency-skill/skills/detecting-circular-dependencies ~/.codex/skills/
```

Restart Codex after installing or updating the skill so the skill metadata is picked up.

## Use In Codex

Example prompts:

```text
Use $detecting-circular-dependencies to check this project for circular dependencies.
```

```text
Use $detecting-circular-dependencies to check whether src/domain participates in any cycles.
```

```text
Use $detecting-circular-dependencies to check architecture-layer cycles using layers.json.
```

Codex should report the selected boundary, graph level, exact cycle path, import-edge evidence, source file and line, caveats, and a small suggested breakpoint.

## Run The Detector Directly

From the skill directory:

```bash
python3 scripts/detect_cycles.py /path/to/project --json
```

Check a specific module or directory:

```bash
python3 scripts/detect_cycles.py /path/to/project --module src/domain --ignore-tests --ignore-type-only --json
```

Use a coarser graph level:

```bash
python3 scripts/detect_cycles.py /path/to/project --level directory --module src/domain --json
python3 scripts/detect_cycles.py /path/to/project --level package --module my_package.billing --json
```

Pass JS/TS aliases when they are not declared in root config:

```bash
python3 scripts/detect_cycles.py /path/to/project --alias @=src --json
```

## Layer Checks

Layer checks map files to architecture layers with path globs.

Create `layers.json`:

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

Run:

```bash
python3 scripts/detect_cycles.py /path/to/project --level layer --layer-config layers.json --json
```

You can also define layers inline:

```bash
python3 scripts/detect_cycles.py /path/to/project \
  --level layer \
  --layer domain=src/domain/** \
  --layer infra=src/infra/** \
  --allow-layer infra->domain \
  --json
```

When `--level layer` is used without `--layer-config` or `--layer`, the detector uses a root `layers.json` file if one exists. Files that match no configured layer are reported in `unmatched_files` and excluded from the layer graph.

## Output

JSON output includes:

- `cycles_found`: whether selected modules participate in a cycle
- `cycles`: cycle paths, members, edge evidence, and `cycle_kind`
- `cycle_kind`: `runtime`, `type-only`, `dynamic`, or `mixed`
- `graph_level`: `file`, `directory`, `package`, or `layer`
- `target_files` and `target_nodes`: the selected analysis target
- `js_aliases` and `python_source_roots`: inferred resolver context
- `layers`, `allowed_layer_dependencies`, `layer_violations`, and `unmatched_files` for layer checks
- `warnings`: skipped files or unmatched selectors

Exit codes:

- `0`: no selected-module cycles or layer-rule violations found
- `2`: selected-module cycles or layer-rule violations found
- `1`: invalid arguments or configuration

## Development

Run the test suite:

```bash
python3 -B -m unittest discover -v
```

Validate the skill structure:

```bash
.venv/bin/python -B /Users/nature/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/detecting-circular-dependencies
```

Run a self-check on this repository:

```bash
python3 -B skills/detecting-circular-dependencies/scripts/detect_cycles.py . --ignore-tests --ignore-type-only --json
```

