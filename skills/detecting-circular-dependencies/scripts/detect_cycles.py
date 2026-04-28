#!/usr/bin/env python3
"""Best-effort module cycle detector for Python and JavaScript/TypeScript projects."""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PY_EXTS = {".py"}
JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
DEFAULT_EXTS = PY_EXTS | JS_EXTS
EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "venv",
}
JS_RESOLVE_EXTS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]

JS_IMPORT_RE = re.compile(
    r"""
    (?P<import_type>import\s+type\s+(?:[^'"]+\s+from\s+)?['"](?P<import_type_spec>[^'"]+)['"])
    |(?P<import_stmt>import\s+(?:[^'"]+\s+from\s+)?['"](?P<import_spec>[^'"]+)['"])
    |(?P<export_type>export\s+type\s+[^'"]*\s+from\s+['"](?P<export_type_spec>[^'"]+)['"])
    |(?P<export_stmt>export\s+[^'"]*\s+from\s+['"](?P<export_spec>[^'"]+)['"])
    |(?P<require_stmt>require\s*\(\s*['"](?P<require_spec>[^'"]+)['"]\s*\))
    |(?P<dynamic_stmt>import\s*\(\s*['"](?P<dynamic_spec>[^'"]+)['"]\s*\))
    """,
    re.MULTILINE | re.VERBOSE,
)


@dataclass(frozen=True)
class Edge:
    source: Path
    target: Path
    line: int
    specifier: str
    kind: str
    language: str


@dataclass(frozen=True)
class Alias:
    prefix: str
    target: Path
    source: str


@dataclass(frozen=True)
class Layer:
    name: str
    patterns: tuple[str, ...]
    source: str


def posix_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_test_path(path: Path, root: Path) -> bool:
    rel = "/" + posix_rel(path, root).lower()
    name = path.name.lower()
    return (
        "/tests/" in rel
        or "/test/" in rel
        or "/__tests__/" in rel
        or ".test." in name
        or ".spec." in name
        or name.startswith("test_")
    )


def iter_source_files(root: Path, exts: set[str], ignore_tests: bool) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in EXCLUDED_DIRS]
        directory = Path(dirpath)
        for filename in filenames:
            path = directory / filename
            if path.suffix not in exts:
                continue
            if ignore_tests and is_test_path(path, root):
                continue
            files.append(path.resolve())
    return sorted(files)


def module_name(path: Path, module_root: Path) -> str:
    rel = path.relative_to(module_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def discover_python_roots(root: Path, files: Iterable[Path]) -> list[Path]:
    roots: list[Path] = []
    src = (root / "src").resolve()
    if src.exists() and any(path.suffix == ".py" and path.is_relative_to(src) for path in files):
        roots.append(src)
    roots.append(root)
    return roots


def python_root_for(path: Path, source_roots: list[Path]) -> Path:
    for source_root in source_roots:
        if path.is_relative_to(source_root):
            return source_root
    return source_roots[-1]


def build_python_module_map(files: Iterable[Path], source_roots: list[Path]) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in files:
        if path.suffix == ".py":
            name = module_name(path, python_root_for(path, source_roots))
            if name:
                modules[name] = path
    return modules


def resolve_python_module(name: str, modules: dict[str, Path]) -> Path | None:
    if name in modules:
        return modules[name]
    parts = name.split(".")
    for end in range(len(parts) - 1, 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in modules:
            return modules[candidate]
    return None


def python_package_prefix(path: Path, source_roots: list[Path]) -> list[str]:
    name = module_name(path, python_root_for(path, source_roots))
    parts = name.split(".") if name else []
    if path.name == "__init__.py":
        return parts
    return parts[:-1]


def relative_python_base(path: Path, source_roots: list[Path], level: int, module: str | None) -> str:
    package = python_package_prefix(path, source_roots)
    if level > 1:
        package = package[: -(level - 1)] if level - 1 <= len(package) else []
    suffix = module.split(".") if module else []
    return ".".join(package + suffix)


def is_type_checking_test(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def is_under_type_checking(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.If) and is_type_checking_test(current.test):
            return True
    return False


def parse_python_edges(
    path: Path,
    root: Path,
    source_roots: list[Path],
    modules: dict[str, Path],
    warnings: list[str],
) -> list[Edge]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError) as exc:
        warnings.append(f"Skipped {posix_rel(path, root)}: {exc}")
        return []

    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    edges: list[Edge] = []

    for node in ast.walk(tree):
        targets: list[tuple[Path, str]] = []
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = resolve_python_module(alias.name, modules)
                if target:
                    targets.append((target, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            base = (
                relative_python_base(path, source_roots, node.level, node.module)
                if node.level
                else node.module or ""
            )
            alias_targets = []
            for alias in node.names:
                if alias.name == "*":
                    continue
                candidate = f"{base}.{alias.name}" if base else alias.name
                target = resolve_python_module(candidate, modules)
                if target:
                    alias_targets.append((target, candidate))

            exact = resolve_python_module(base, modules) if base else None
            targets.extend(alias_targets or ([(exact, base)] if exact else []))
        else:
            continue

        kind = "type" if is_under_type_checking(node, parents) else "runtime"
        for target, specifier in targets:
            edges.append(Edge(path, target, node.lineno, specifier, kind, "python"))

    return edges


def line_number_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def parse_aliases(values: list[str]) -> list[Alias]:
    aliases: list[Alias] = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"Alias must use prefix=path syntax: {value}")
        prefix, target = value.split("=", 1)
        aliases.append(Alias(prefix, Path(target), "cli"))
    return aliases


def path_prefix_from_tsconfig(pattern: str) -> str:
    return pattern[:-2] if pattern.endswith("/*") else pattern.rstrip("*").rstrip("/")


def target_from_tsconfig_path(pattern: str) -> Path:
    target = pattern[:-2] if pattern.endswith("/*") else pattern.rstrip("*").rstrip("/")
    return Path(target or ".")


def load_js_config_aliases(root: Path, warnings: list[str]) -> list[Alias]:
    aliases: list[Alias] = []
    for filename in ("tsconfig.json", "jsconfig.json"):
        config_path = root / filename
        if not config_path.exists():
            continue
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            warnings.append(f"Skipped {filename}: {exc}")
            continue
        compiler_options = data.get("compilerOptions", {})
        base_url = Path(compiler_options.get("baseUrl", "."))
        paths = compiler_options.get("paths", {})
        if not isinstance(paths, dict):
            continue
        for raw_prefix, raw_targets in paths.items():
            if not isinstance(raw_prefix, str) or not isinstance(raw_targets, list) or not raw_targets:
                continue
            first_target = raw_targets[0]
            if not isinstance(first_target, str):
                continue
            aliases.append(
                Alias(
                    path_prefix_from_tsconfig(raw_prefix),
                    base_url / target_from_tsconfig_path(first_target),
                    filename,
                )
            )
    return aliases


def parse_layer_values(values: list[str]) -> list[Layer]:
    layers: list[Layer] = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"Layer must use name=glob[,glob] syntax: {value}")
        name, patterns_text = value.split("=", 1)
        name = name.strip()
        patterns = tuple(pattern.strip() for pattern in patterns_text.split(",") if pattern.strip())
        if not name or not patterns:
            raise ValueError(f"Layer must include a name and at least one glob: {value}")
        layers.append(Layer(name, patterns, "cli"))
    return layers


def parse_allowed_dependency(value: str) -> tuple[str, str]:
    if "->" in value:
        source, target = value.split("->", 1)
    elif "=" in value:
        source, target = value.split("=", 1)
    else:
        raise ValueError(f"Allowed layer dependency must use source->target syntax: {value}")
    source = source.strip()
    target = target.strip()
    if not source or not target:
        raise ValueError(f"Allowed layer dependency must include source and target: {value}")
    return source, target


def parse_allowed_values(values: list[str]) -> set[tuple[str, str]]:
    return {parse_allowed_dependency(value) for value in values}


def layers_from_mapping(data: object, source: str) -> list[Layer]:
    if not isinstance(data, dict):
        raise ValueError(f"Layer config must be a JSON object: {source}")
    raw_layers = data.get("layers")
    if isinstance(raw_layers, dict):
        layers = []
        for name, patterns in raw_layers.items():
            if isinstance(patterns, str):
                layer_patterns = (patterns,)
            elif isinstance(patterns, list) and all(isinstance(pattern, str) for pattern in patterns):
                layer_patterns = tuple(patterns)
            else:
                raise ValueError(f"Layer '{name}' must use a string or list of string globs: {source}")
            layers.append(Layer(str(name), layer_patterns, source))
        return layers
    if isinstance(raw_layers, list):
        layers = []
        for entry in raw_layers:
            if not isinstance(entry, dict):
                raise ValueError(f"Layer entries must be objects: {source}")
            name = entry.get("name")
            patterns = entry.get("patterns")
            if not isinstance(name, str):
                raise ValueError(f"Layer entry is missing a string name: {source}")
            if isinstance(patterns, str):
                layer_patterns = (patterns,)
            elif isinstance(patterns, list) and all(isinstance(pattern, str) for pattern in patterns):
                layer_patterns = tuple(patterns)
            else:
                raise ValueError(f"Layer '{name}' must use a string or list of string globs: {source}")
            layers.append(Layer(name, layer_patterns, source))
        return layers
    raise ValueError(f"Layer config must contain a 'layers' object or list: {source}")


def allowed_from_mapping(data: object, source: str) -> set[tuple[str, str]] | None:
    if not isinstance(data, dict) or "allowed" not in data:
        return None
    raw_allowed = data["allowed"]
    if not isinstance(raw_allowed, list):
        raise ValueError(f"Layer config 'allowed' must be a list: {source}")
    allowed = set()
    for entry in raw_allowed:
        if isinstance(entry, str):
            allowed.add(parse_allowed_dependency(entry))
        elif isinstance(entry, dict):
            source_layer = entry.get("from")
            target_layer = entry.get("to")
            if not isinstance(source_layer, str) or not isinstance(target_layer, str):
                raise ValueError(f"Layer config allowed entries need string 'from' and 'to': {source}")
            allowed.add((source_layer, target_layer))
        else:
            raise ValueError(f"Layer config allowed entries must be strings or objects: {source}")
    return allowed


def load_layer_config(root: Path, value: str) -> list[Layer]:
    config_path = (root / value).resolve() if not Path(value).is_absolute() else Path(value)
    source = posix_rel(config_path, root) if config_path.is_relative_to(root) else str(config_path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Layer config not found: {value}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid layer config JSON in {value}: {exc}") from None
    return layers_from_mapping(data, source)


def load_allowed_config(root: Path, value: str) -> set[tuple[str, str]] | None:
    config_path = (root / value).resolve() if not Path(value).is_absolute() else Path(value)
    source = posix_rel(config_path, root) if config_path.is_relative_to(root) else str(config_path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"Layer config not found: {value}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid layer config JSON in {value}: {exc}") from None
    return allowed_from_mapping(data, source)


def load_layers(root: Path, layer_config: str | None, layer_values: list[str], level: str) -> list[Layer]:
    layers: list[Layer] = []
    if layer_config:
        layers.extend(load_layer_config(root, layer_config))
    layers.extend(parse_layer_values(layer_values))
    if level == "layer" and not layers:
        default_config = root / "layers.json"
        if default_config.exists():
            layers.extend(load_layer_config(root, "layers.json"))
    if level == "layer" and not layers:
        raise ValueError("Layer level requires --layer-config, --layer, or a root layers.json file.")
    return layers


def load_allowed_dependencies(
    root: Path,
    layer_config: str | None,
    allowed_values: list[str],
    level: str,
) -> set[tuple[str, str]] | None:
    allowed = set()
    found_policy = False
    if layer_config:
        config_allowed = load_allowed_config(root, layer_config)
        if config_allowed is not None:
            allowed.update(config_allowed)
            found_policy = True
    elif level == "layer" and (root / "layers.json").exists():
        config_allowed = load_allowed_config(root, "layers.json")
        if config_allowed is not None:
            allowed.update(config_allowed)
            found_policy = True
    if allowed_values:
        allowed.update(parse_allowed_values(allowed_values))
        found_policy = True
    return allowed if found_policy else None


def split_layer_selectors(selectors: list[str], layers: list[Layer]) -> tuple[list[str], set[str]]:
    path_selectors = []
    layer_targets = set()
    layer_names = [layer.name for layer in layers]
    for selector in selectors:
        matches = {name for name in layer_names if selector == name or fnmatch.fnmatch(name, selector)}
        if matches:
            layer_targets.update(matches)
        else:
            path_selectors.append(selector)
    return path_selectors, layer_targets


def resolve_js_specifier(specifier: str, source: Path, root: Path, aliases: list[Alias]) -> Path | None:
    if specifier.startswith("."):
        base = (source.parent / specifier).resolve()
    else:
        base = None
        for alias in aliases:
            if specifier == alias.prefix or specifier.startswith(alias.prefix.rstrip("/") + "/"):
                suffix = specifier[len(alias.prefix) :].lstrip("/")
                base = (root / alias.target / suffix).resolve()
                break
        if base is None:
            return None

    candidates = []
    if base.suffix:
        candidates.append(base)
        if base.suffix == ".js":
            candidates.extend([base.with_suffix(".ts"), base.with_suffix(".tsx")])
        if base.suffix == ".jsx":
            candidates.append(base.with_suffix(".tsx"))
    else:
        candidates.extend(base.with_suffix(ext) for ext in JS_RESOLVE_EXTS)
        candidates.extend(base / f"index{ext}" for ext in JS_RESOLVE_EXTS)

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def parse_js_edges(
    path: Path,
    root: Path,
    aliases: list[Alias],
    warnings: list[str],
) -> list[Edge]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        warnings.append(f"Skipped {posix_rel(path, root)}: {exc}")
        return []

    edges: list[Edge] = []
    for match in JS_IMPORT_RE.finditer(text):
        specifier = (
            match.group("import_type_spec")
            or match.group("import_spec")
            or match.group("export_type_spec")
            or match.group("export_spec")
            or match.group("require_spec")
            or match.group("dynamic_spec")
        )
        if not specifier:
            continue
        target = resolve_js_specifier(specifier, path, root, aliases)
        if not target:
            continue
        if match.group("import_type") or match.group("export_type"):
            kind = "type"
        elif match.group("dynamic_stmt"):
            kind = "dynamic"
        else:
            kind = "runtime"
        edges.append(
            Edge(
                path,
                target,
                line_number_for_offset(text, match.start()),
                specifier,
                kind,
                "javascript",
            )
        )
    return edges


def selector_candidates(path: Path, root: Path) -> set[str]:
    rel = posix_rel(path, root)
    no_ext = Path(rel).with_suffix("").as_posix()
    dotted = no_ext.replace("/", ".")
    candidates = {rel, no_ext, dotted, path.name, path.stem}
    for suffix in ("/index", ".__init__", "/__init__"):
        if no_ext.endswith(suffix):
            base = no_ext[: -len(suffix)]
            candidates.add(base)
            candidates.add(base.replace("/", "."))
    return candidates


def select_targets(selectors: list[str], files: list[Path], root: Path, warnings: list[str]) -> set[Path]:
    if not selectors:
        return set(files)

    selected: set[Path] = set()
    for raw_selector in selectors:
        selector = raw_selector.strip()
        path_candidate = (root / selector).resolve()
        before = set(selected)
        if path_candidate.exists():
            if path_candidate.is_dir():
                selected.update(path for path in files if path.is_relative_to(path_candidate))
            elif path_candidate in files:
                selected.add(path_candidate)
        else:
            for path in files:
                candidates = selector_candidates(path, root)
                if selector in candidates or any(fnmatch.fnmatch(candidate, selector) for candidate in candidates):
                    selected.add(path)
        if selected == before:
            warnings.append(f"No source files matched target selector: {selector}")
    return selected


def build_graph(files: list[Path], edges: list[Edge], ignore_type_only: bool) -> dict[Path, set[Path]]:
    graph = {path: set() for path in files}
    for edge in edges:
        if ignore_type_only and edge.kind == "type":
            continue
        if edge.source in graph and edge.target in graph:
            graph[edge.source].add(edge.target)
    return graph


def package_label(path: Path, root: Path, source_roots: list[Path]) -> str:
    if path.suffix == ".py":
        name = module_name(path, python_root_for(path, source_roots))
        parts = name.split(".") if name else []
        if path.name != "__init__.py" and parts:
            parts = parts[:-1]
        return ".".join(parts) or "."
    return path.parent.relative_to(root).as_posix() or "."


def pattern_matches_path(pattern: str, rel_path: str) -> bool:
    if fnmatch.fnmatch(rel_path, pattern):
        return True
    has_glob = any(char in pattern for char in "*?[")
    normalized = pattern.rstrip("/")
    return not has_glob and (rel_path == normalized or rel_path.startswith(normalized + "/"))


def layer_label(path: Path, root: Path, layers: list[Layer]) -> str | None:
    rel = posix_rel(path, root)
    for layer in layers:
        if any(pattern_matches_path(pattern, rel) for pattern in layer.patterns):
            return layer.name
    return None


def node_label(path: Path, root: Path, level: str, source_roots: list[Path], layers: list[Layer]) -> str | None:
    if level == "file":
        return posix_rel(path, root)
    if level == "directory":
        return path.parent.relative_to(root).as_posix() or "."
    if level == "package":
        return package_label(path, root, source_roots)
    if level == "layer":
        return layer_label(path, root, layers)
    raise ValueError(f"Unsupported graph level: {level}")


def build_level_graph(
    files: list[Path],
    edges: list[Edge],
    root: Path,
    level: str,
    source_roots: list[Path],
    layers: list[Layer],
    ignore_type_only: bool,
) -> tuple[dict[str, set[str]], dict[tuple[str, str], list[Edge]], dict[Path, str]]:
    path_labels = {}
    for path in files:
        label = node_label(path, root, level, source_roots, layers)
        if label:
            path_labels[path] = label
    graph = {layer.name: set() for layer in layers} if level == "layer" else {label: set() for label in path_labels.values()}
    evidence: dict[tuple[str, str], list[Edge]] = defaultdict(list)
    for edge in edges:
        if ignore_type_only and edge.kind == "type":
            continue
        if edge.source not in path_labels or edge.target not in path_labels:
            continue
        source_label = path_labels[edge.source]
        target_label = path_labels[edge.target]
        if level != "file" and source_label == target_label:
            continue
        graph[source_label].add(target_label)
        evidence[(source_label, target_label)].append(edge)
    return graph, evidence, path_labels


def strongly_connected_components(graph: dict[Path, set[Path]]) -> list[set[Path]]:
    index = 0
    stack: list[Path] = []
    indices: dict[Path, int] = {}
    lowlinks: dict[Path, int] = {}
    on_stack: set[Path] = set()
    components: list[set[Path]] = []

    def visit(node: Path) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in graph[node]:
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])

        if lowlinks[node] == indices[node]:
            component = set()
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.add(member)
                if member == node:
                    break
            components.append(component)

    for node in graph:
        if node not in indices:
            visit(node)
    return components


def find_cycle_path(start: Path, component: set[Path], graph: dict[Path, set[Path]]) -> list[Path]:
    if start in graph[start]:
        return [start, start]

    path: list[Path] = []
    visited: set[Path] = set()

    def dfs(node: Path) -> list[Path] | None:
        path.append(node)
        visited.add(node)
        for neighbor in sorted(graph[node]):
            if neighbor not in component:
                continue
            if neighbor == start and len(path) > 1:
                return path + [start]
            if neighbor not in visited:
                result = dfs(neighbor)
                if result:
                    return result
        visited.remove(node)
        path.pop()
        return None

    return dfs(start) or sorted(component)


def edge_index(edges: list[Edge], ignore_type_only: bool) -> dict[tuple[Path, Path], list[Edge]]:
    pairs: dict[tuple[Path, Path], list[Edge]] = defaultdict(list)
    for edge in edges:
        if ignore_type_only and edge.kind == "type":
            continue
        pairs[(edge.source, edge.target)].append(edge)
    return pairs


def classify_cycle(edges: list[Edge]) -> str:
    kinds = {edge.kind for edge in edges}
    if kinds == {"type"}:
        return "type-only"
    if "runtime" in kinds:
        return "runtime"
    if "dynamic" in kinds:
        return "dynamic"
    return "mixed"


def suggested_breakpoint(edge: Edge) -> str:
    if edge.kind == "type":
        return "Keep this edge type-only or move shared type declarations to a neutral module."
    if edge.language == "javascript" and edge.specifier.startswith("."):
        return "Move shared runtime code to a neutral module or invert this import through a narrower interface."
    if edge.language == "python":
        return "Move shared runtime code to a lower-level module or import lazily at the call site if appropriate."
    return "Break this edge by extracting shared behavior or depending on an interface owned by the lower-level module."


def serialize_edge(edge: Edge, root: Path, source_label: str, target_label: str) -> dict[str, object]:
    return {
        "from": source_label,
        "to": target_label,
        "from_file": posix_rel(edge.source, root),
        "to_file": posix_rel(edge.target, root),
        "line": edge.line,
        "specifier": edge.specifier,
        "kind": edge.kind,
        "language": edge.language,
        "suggested_breakpoint": suggested_breakpoint(edge),
    }


def analyze(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    root = Path(args.root).resolve()
    warnings: list[str] = []
    extensions = {ext if ext.startswith(".") else f".{ext}" for ext in args.extensions}
    files = iter_source_files(root, extensions, args.ignore_tests)
    source_roots = discover_python_roots(root, files)
    python_modules = build_python_module_map(files, source_roots)
    aliases = []
    if not args.no_auto_config:
        aliases.extend(load_js_config_aliases(root, warnings))
    aliases.extend(parse_aliases(args.alias))
    layers = load_layers(root, args.layer_config, args.layer, args.level)
    allowed_layer_dependencies = load_allowed_dependencies(
        root,
        args.layer_config,
        args.allow_layer,
        args.level,
    )

    edges: list[Edge] = []
    for path in files:
        if path.suffix in PY_EXTS:
            edges.extend(parse_python_edges(path, root, source_roots, python_modules, warnings))
        elif path.suffix in JS_EXTS:
            edges.extend(parse_js_edges(path, root, aliases, warnings))

    path_module_selectors = args.module
    layer_target_nodes: set[str] = set()
    if args.level == "layer":
        path_module_selectors, layer_target_nodes = split_layer_selectors(args.module, layers)
    targets = (
        set()
        if args.level == "layer" and args.module and not path_module_selectors
        else select_targets(path_module_selectors, files, root, warnings)
    )
    graph, pairs, path_labels = build_level_graph(
        files,
        edges,
        root,
        args.level,
        source_roots,
        layers,
        args.ignore_type_only,
    )
    target_nodes = {path_labels[path] for path in targets if path in path_labels} | layer_target_nodes
    layer_violations = []
    if args.level == "layer" and allowed_layer_dependencies is not None:
        for source, target in sorted(pairs):
            if (source, target) in allowed_layer_dependencies:
                continue
            candidates = pairs[(source, target)]
            preferred = next((edge for edge in candidates if edge.kind != "type"), candidates[0])
            layer_violations.append(serialize_edge(preferred, root, source, target))
    cycles = []

    for component in strongly_connected_components(graph):
        has_cycle = len(component) > 1 or any(node in graph[node] for node in component)
        if not has_cycle or not (component & target_nodes):
            continue
        start = sorted(component & target_nodes or component)[0]
        path = find_cycle_path(start, component, graph)
        cycle_edges = []
        raw_cycle_edges = []
        for source, target in zip(path, path[1:]):
            candidates = pairs.get((source, target), [])
            if candidates:
                preferred = next((edge for edge in candidates if edge.kind != "type"), candidates[0])
                raw_cycle_edges.append(preferred)
                cycle_edges.append(serialize_edge(preferred, root, source, target))
        cycles.append(
            {
                "cycle_kind": classify_cycle(raw_cycle_edges),
                "members": sorted(component),
                "path": path,
                "edges": cycle_edges,
            }
        )

    cycles = cycles[: args.max_cycles]
    payload = {
        "root": str(root),
        "graph_level": args.level,
        "analyzed_files": len(files),
        "analyzed_edges": sum(len(targets) for targets in graph.values()),
        "target_modules": args.module,
        "target_files": [posix_rel(path, root) for path in sorted(targets)],
        "target_nodes": sorted(target_nodes),
        "python_source_roots": [posix_rel(path, root) for path in source_roots if path != root],
        "js_aliases": [
            {"prefix": alias.prefix, "target": alias.target.as_posix(), "source": alias.source}
            for alias in aliases
        ],
        "layers": [
            {"name": layer.name, "patterns": list(layer.patterns), "source": layer.source}
            for layer in layers
        ],
        "allowed_layer_dependencies": [
            {"from": source, "to": target}
            for source, target in sorted(allowed_layer_dependencies or set())
        ],
        "layer_violations_found": bool(layer_violations),
        "layer_violations": layer_violations,
        "unmatched_files": [
            posix_rel(path, root)
            for path in sorted(files)
            if args.level == "layer" and path not in path_labels
        ],
        "cycles_found": bool(cycles),
        "cycles": cycles,
        "warnings": warnings,
    }
    return payload, 2 if cycles or layer_violations else 0


def print_text(payload: dict[str, object]) -> None:
    target_label = ", ".join(payload["target_modules"]) if payload["target_modules"] else "all modules"
    print(f"Root: {payload['root']}")
    print(
        f"Analyzed: {payload['analyzed_files']} files, "
        f"{payload['analyzed_edges']} internal edges at {payload['graph_level']} level"
    )
    print(f"Targets: {target_label}")
    for warning in payload["warnings"]:
        print(f"Warning: {warning}", file=sys.stderr)

    if not payload["cycles_found"]:
        print("No circular dependencies found involving the selected modules.")
        return

    print("Circular dependencies found:")
    for index, cycle in enumerate(payload["cycles"], start=1):
        print(f"\n{index}. [{cycle['cycle_kind']}] {' -> '.join(cycle['path'])}")
        for edge in cycle["edges"]:
            print(
                f"   {edge['from_file']}:{edge['line']} -> {edge['to_file']} "
                f"({edge['kind']} {edge['language']} import: {edge['specifier']})"
            )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect internal module cycles involving selected Python or JS/TS modules."
    )
    parser.add_argument("root", nargs="?", default=".", help="Project root to analyze.")
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        help="Target module/path/glob to check. Repeat to check multiple modules. Omit to report all cycles.",
    )
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=sorted(DEFAULT_EXTS),
        help="File extensions to parse. Default: Python and JS/TS source extensions.",
    )
    parser.add_argument(
        "--level",
        choices=("file", "directory", "package", "layer"),
        default="file",
        help="Graph level to analyze. Default: file.",
    )
    parser.add_argument(
        "--layer-config",
        help="JSON layer config path. Supports {'layers': {'name': ['glob']}} or a list of layer objects.",
    )
    parser.add_argument(
        "--layer",
        action="append",
        default=[],
        help="Layer definition as name=glob[,glob]. Repeat to define multiple layers.",
    )
    parser.add_argument(
        "--allow-layer",
        action="append",
        default=[],
        help="Allowed layer dependency as source->target. Repeat to define multiple allowed directions.",
    )
    parser.add_argument("--alias", action="append", default=[], help="JS/TS import alias as prefix=path, e.g. @=src.")
    parser.add_argument(
        "--no-auto-config",
        action="store_true",
        help="Do not infer JS/TS aliases or Python source roots from local project conventions.",
    )
    parser.add_argument("--ignore-tests", action="store_true", help="Exclude common test file and directory patterns.")
    parser.add_argument("--ignore-type-only", action="store_true", help="Ignore Python TYPE_CHECKING and TS import type edges.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--max-cycles", type=int, default=20, help="Maximum number of cycles to report.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    try:
        args = parse_args(argv)
        payload, exit_code = analyze(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print_text(payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
