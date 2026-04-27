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


def module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def build_python_module_map(files: Iterable[Path], root: Path) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in files:
        if path.suffix == ".py":
            name = module_name(path, root)
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


def python_package_prefix(path: Path, root: Path) -> list[str]:
    parts = module_name(path, root).split(".") if module_name(path, root) else []
    if path.name == "__init__.py":
        return parts
    return parts[:-1]


def relative_python_base(path: Path, root: Path, level: int, module: str | None) -> str:
    package = python_package_prefix(path, root)
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
                relative_python_base(path, root, node.level, node.module)
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


def parse_aliases(values: list[str]) -> list[tuple[str, Path]]:
    aliases: list[tuple[str, Path]] = []
    for value in values:
        if "=" not in value:
            raise ValueError(f"Alias must use prefix=path syntax: {value}")
        prefix, target = value.split("=", 1)
        aliases.append((prefix, Path(target)))
    return aliases


def resolve_js_specifier(specifier: str, source: Path, root: Path, aliases: list[tuple[str, Path]]) -> Path | None:
    if specifier.startswith("."):
        base = (source.parent / specifier).resolve()
    else:
        base = None
        for prefix, target in aliases:
            if specifier == prefix or specifier.startswith(prefix.rstrip("/") + "/"):
                suffix = specifier[len(prefix) :].lstrip("/")
                base = (root / target / suffix).resolve()
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
    aliases: list[tuple[str, Path]],
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
        kind = "type" if match.group("import_type") or match.group("export_type") else "runtime"
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


def serialize_edge(edge: Edge, root: Path) -> dict[str, object]:
    return {
        "from": posix_rel(edge.source, root),
        "to": posix_rel(edge.target, root),
        "line": edge.line,
        "specifier": edge.specifier,
        "kind": edge.kind,
        "language": edge.language,
    }


def analyze(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    root = Path(args.root).resolve()
    warnings: list[str] = []
    extensions = {ext if ext.startswith(".") else f".{ext}" for ext in args.extensions}
    aliases = parse_aliases(args.alias)
    files = iter_source_files(root, extensions, args.ignore_tests)
    python_modules = build_python_module_map(files, root)

    edges: list[Edge] = []
    for path in files:
        if path.suffix in PY_EXTS:
            edges.extend(parse_python_edges(path, root, python_modules, warnings))
        elif path.suffix in JS_EXTS:
            edges.extend(parse_js_edges(path, root, aliases, warnings))

    graph = build_graph(files, edges, args.ignore_type_only)
    targets = select_targets(args.module, files, root, warnings)
    pairs = edge_index(edges, args.ignore_type_only)
    cycles = []

    for component in strongly_connected_components(graph):
        has_cycle = len(component) > 1 or any(node in graph[node] for node in component)
        if not has_cycle or not (component & targets):
            continue
        start = sorted(component & targets or component)[0]
        path = find_cycle_path(start, component, graph)
        cycle_edges = []
        for source, target in zip(path, path[1:]):
            candidates = pairs.get((source, target), [])
            if candidates:
                preferred = next((edge for edge in candidates if edge.kind != "type"), candidates[0])
                cycle_edges.append(serialize_edge(preferred, root))
        cycles.append(
            {
                "members": [posix_rel(path, root) for path in sorted(component)],
                "path": [posix_rel(path, root) for path in path],
                "edges": cycle_edges,
            }
        )

    cycles = cycles[: args.max_cycles]
    payload = {
        "root": str(root),
        "analyzed_files": len(files),
        "analyzed_edges": sum(len(targets) for targets in graph.values()),
        "target_modules": args.module,
        "target_files": [posix_rel(path, root) for path in sorted(targets)],
        "cycles_found": bool(cycles),
        "cycles": cycles,
        "warnings": warnings,
    }
    return payload, 2 if cycles else 0


def print_text(payload: dict[str, object]) -> None:
    target_label = ", ".join(payload["target_modules"]) if payload["target_modules"] else "all modules"
    print(f"Root: {payload['root']}")
    print(f"Analyzed: {payload['analyzed_files']} files, {payload['analyzed_edges']} internal edges")
    print(f"Targets: {target_label}")
    for warning in payload["warnings"]:
        print(f"Warning: {warning}", file=sys.stderr)

    if not payload["cycles_found"]:
        print("No circular dependencies found involving the selected modules.")
        return

    print("Circular dependencies found:")
    for index, cycle in enumerate(payload["cycles"], start=1):
        print(f"\n{index}. {' -> '.join(cycle['path'])}")
        for edge in cycle["edges"]:
            print(
                f"   {edge['from']}:{edge['line']} -> {edge['to']} "
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
    parser.add_argument("--alias", action="append", default=[], help="JS/TS import alias as prefix=path, e.g. @=src.")
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
