# Circular Dependency Skill

A Codex skill and standalone static analyzer for finding circular dependencies in local Python and JavaScript/TypeScript projects.

The skill tells Codex how to choose the right analysis boundary and how to report evidence. The bundled detector builds an internal import graph and finds cycles with strongly connected components, so results are based on graph analysis rather than text search.

## Features

- Detect file-level cycles, such as `src/a.ts -> src/b.ts -> src/a.ts`
- Aggregate dependencies at directory and package levels
- Check configured architecture layers, such as `domain -> infrastructure -> domain`
- Report architecture-rule violations, such as `domain -> infrastructure` when that direction is not allowed
- Classify cycles as `runtime`, `type-only`, `dynamic`, or `mixed`
- Include source file, line number, import specifier, and a suggested breakpoint for each reported edge

## Requirements

- Python 3.9 or newer
- No third-party Python dependencies for the detector itself
- Codex only if you want to install and use the repository as a Codex skill

## Repository Layout

```text
skills/detecting-circular-dependencies/
  SKILL.md
  agents/openai.yaml
  references/language-strategies.md
  scripts/detect_cycles.py
tests/
  test_detect_cycles.py
```

## Install The Codex Skill

The skill folder is:

```text
skills/detecting-circular-dependencies
```

### Option 1: Ask Codex To Install It

In Codex, ask:

```text
Install the detecting-circular-dependencies skill from https://github.com/chen-985211/circular-dependency-skill/tree/main/skills/detecting-circular-dependencies
```

Restart Codex after installation so the new skill metadata is loaded.

### Option 2: Install Manually

```bash
git clone https://github.com/chen-985211/circular-dependency-skill.git
cd circular-dependency-skill

SKILLS_DIR="${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "$SKILLS_DIR"
cp -R skills/detecting-circular-dependencies "$SKILLS_DIR/"
```

If you are updating an existing install, remove or replace the old `detecting-circular-dependencies` directory first, then restart Codex.

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

Codex should report the selected boundary, graph level, exact cycle path, source file and line for each edge, caveats, risk level, and a small suggested breakpoint.

## Run The Detector Directly

From the repository root:

```bash
python3 skills/detecting-circular-dependencies/scripts/detect_cycles.py /path/to/project --json
```

Check a specific target:

```bash
python3 skills/detecting-circular-dependencies/scripts/detect_cycles.py /path/to/project \
  --module src/domain \
  --ignore-tests \
  --ignore-type-only \
  --json
```

Use a coarser graph level:

```bash
python3 skills/detecting-circular-dependencies/scripts/detect_cycles.py /path/to/project \
  --level directory \
  --module src/domain \
  --json

python3 skills/detecting-circular-dependencies/scripts/detect_cycles.py /path/to/project \
  --level package \
  --module my_package.billing \
  --json
```

Pass JS/TS aliases manually when they are not declared in root `tsconfig.json` or `jsconfig.json`:

```bash
python3 skills/detecting-circular-dependencies/scripts/detect_cycles.py /path/to/project \
  --alias @=src \
  --json
```

## Layer Checks

Layer checks map files to architecture layers with path globs.

Create `layers.json` in the target project:

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
python3 skills/detecting-circular-dependencies/scripts/detect_cycles.py /path/to/project \
  --level layer \
  --layer-config layers.json \
  --json
```

You can also define layers inline:

```bash
python3 skills/detecting-circular-dependencies/scripts/detect_cycles.py /path/to/project \
  --level layer \
  --layer domain=src/domain/** \
  --layer infra=src/infra/** \
  --allow-layer infra->domain \
  --json
```

When `--level layer` is used without `--layer-config` or `--layer`, the detector uses `/path/to/project/layers.json` if it exists. Files that match no configured layer are reported in `unmatched_files` and excluded from the layer graph.

## Supported Import Resolution

Python:

- `import ...`
- `from ... import ...`
- relative imports
- package `__init__.py`
- imports guarded by `TYPE_CHECKING`
- common top-level `src/` layout

JavaScript and TypeScript:

- static `import`
- `export ... from`
- `require(...)`
- dynamic `import(...)`
- relative resolution
- `index.*`
- root `tsconfig.json` / `jsconfig.json` path aliases

This detector is intentionally best-effort. For ecosystems with strong native dependency tooling, use the native analyzer first and use this skill as a fallback or evidence formatter.

## JSON Output

Important fields:

- `cycles_found`: whether selected targets participate in a cycle
- `cycles`: cycle paths, members, edge evidence, and `cycle_kind`
- `cycle_kind`: `runtime`, `type-only`, `dynamic`, or `mixed`
- `graph_level`: `file`, `directory`, `package`, or `layer`
- `target_files` and `target_nodes`: selected analysis targets
- `js_aliases` and `python_source_roots`: inferred resolver context
- `layers`, `allowed_layer_dependencies`, `layer_violations`, and `unmatched_files`: layer-check context
- `warnings`: skipped files or unmatched selectors

Exit codes:

- `0`: no selected-target cycles or layer-rule violations found
- `2`: selected-target cycles or layer-rule violations found
- `1`: invalid arguments or configuration

## Development

Run the test suite:

```bash
python3 -B -m unittest discover -v
```

Run a self-check on this repository:

```bash
python3 -B skills/detecting-circular-dependencies/scripts/detect_cycles.py . \
  --ignore-tests \
  --ignore-type-only \
  --json
```

If you are developing inside Codex and have the `skill-creator` system skill available, you can also run its `quick_validate.py` script against `skills/detecting-circular-dependencies`.

