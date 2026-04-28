from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "detecting-circular-dependencies"
    / "scripts"
    / "detect_cycles.py"
)


def load_detector():
    spec = importlib.util.spec_from_file_location("detect_cycles", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def analyze(root: Path, *args: str):
    detector = load_detector()
    namespace = detector.parse_args([str(root), *args])
    return detector.analyze(namespace)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class DetectCyclesTests(unittest.TestCase):
    def test_reads_tsconfig_paths_for_alias_cycles(self) -> None:
        with self.subTest():
            from tempfile import TemporaryDirectory

            with TemporaryDirectory() as directory:
                tmp_path = Path(directory)
                write(
                    tmp_path / "tsconfig.json",
                    """
                    {
                      "compilerOptions": {
                        "baseUrl": ".",
                        "paths": {
                          "@/*": ["src/*"]
                        }
                      }
                    }
                    """,
                )
                write(tmp_path / "src" / "a.ts", 'import { b } from "@/b";\nexport const a = b;\n')
                write(tmp_path / "src" / "b.ts", 'import { a } from "@/a";\nexport const b = a;\n')

                payload, exit_code = analyze(tmp_path)

                self.assertEqual(exit_code, 2)
                self.assertIs(payload["cycles_found"], True)
                self.assertEqual(payload["cycles"][0]["cycle_kind"], "runtime")
                self.assertEqual(payload["cycles"][0]["path"], ["src/a.ts", "src/b.ts", "src/a.ts"])
                self.assertEqual(payload["cycles"][0]["edges"][0]["specifier"], "@/b")

    def test_resolves_python_src_layout_package_imports(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            write(
                tmp_path / "pyproject.toml",
                """
                [project]
                name = "demo"
                """,
            )
            write(tmp_path / "src" / "pkg" / "__init__.py", "")
            write(tmp_path / "src" / "pkg" / "a.py", "from pkg import b\n")
            write(tmp_path / "src" / "pkg" / "b.py", "from pkg import a\n")

            payload, exit_code = analyze(tmp_path)

            self.assertEqual(exit_code, 2)
            self.assertIs(payload["cycles_found"], True)
            self.assertEqual(payload["cycles"][0]["members"], ["src/pkg/a.py", "src/pkg/b.py"])
            self.assertEqual(payload["cycles"][0]["cycle_kind"], "runtime")

    def test_type_only_cycle_is_classified_and_filterable(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            write(tmp_path / "src" / "a.ts", 'import type { B } from "./b";\nexport type A = B;\n')
            write(tmp_path / "src" / "b.ts", 'import type { A } from "./a";\nexport type B = A;\n')

            payload, exit_code = analyze(tmp_path)

            self.assertEqual(exit_code, 2)
            self.assertIs(payload["cycles_found"], True)
            self.assertEqual(payload["cycles"][0]["cycle_kind"], "type-only")

            filtered_payload, filtered_exit_code = analyze(tmp_path, "--ignore-type-only")
            self.assertEqual(filtered_exit_code, 0)
            self.assertIs(filtered_payload["cycles_found"], False)

    def test_directory_level_reports_aggregated_cycle(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            write(tmp_path / "src" / "domain" / "model.ts", 'import "../infra/db";\n')
            write(tmp_path / "src" / "infra" / "db.ts", 'import "../domain/model";\n')

            payload, exit_code = analyze(tmp_path, "--level", "directory", "--module", "src/domain")

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["graph_level"], "directory")
            self.assertEqual(payload["cycles"][0]["path"], ["src/domain", "src/infra", "src/domain"])
            self.assertEqual(payload["cycles"][0]["members"], ["src/domain", "src/infra"])
            self.assertEqual(payload["cycles"][0]["edges"][0]["from_file"], "src/domain/model.ts")

    def test_layer_level_reports_configured_layer_cycle(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            write(
                tmp_path / "layers.json",
                json.dumps(
                    {
                        "layers": {
                            "domain": ["src/domain/**"],
                            "application": ["src/app/**"],
                            "infrastructure": ["src/infra/**"],
                        }
                    }
                ),
            )
            write(tmp_path / "src" / "domain" / "model.ts", 'import "../infra/db";\n')
            write(tmp_path / "src" / "infra" / "db.ts", 'import "../domain/model";\n')
            write(tmp_path / "src" / "app" / "use.ts", 'import "../domain/model";\n')

            payload, exit_code = analyze(
                tmp_path,
                "--level",
                "layer",
                "--layer-config",
                "layers.json",
                "--module",
                "src/domain",
            )

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["graph_level"], "layer")
            self.assertEqual(
                payload["layers"],
                [
                    {"name": "domain", "patterns": ["src/domain/**"], "source": "layers.json"},
                    {"name": "application", "patterns": ["src/app/**"], "source": "layers.json"},
                    {"name": "infrastructure", "patterns": ["src/infra/**"], "source": "layers.json"},
                ],
            )
            self.assertEqual(payload["cycles"][0]["path"], ["domain", "infrastructure", "domain"])
            self.assertEqual(payload["cycles"][0]["members"], ["domain", "infrastructure"])
            self.assertEqual(payload["cycles"][0]["edges"][0]["from"], "domain")
            self.assertEqual(payload["cycles"][0]["edges"][0]["to"], "infrastructure")
            self.assertEqual(payload["cycles"][0]["edges"][0]["from_file"], "src/domain/model.ts")

    def test_layer_level_accepts_cli_layer_definitions(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            write(tmp_path / "src" / "domain" / "model.ts", 'import "../infra/db";\n')
            write(tmp_path / "src" / "infra" / "db.ts", 'import "../domain/model";\n')

            payload, exit_code = analyze(
                tmp_path,
                "--level",
                "layer",
                "--layer",
                "domain=src/domain/**",
                "--layer",
                "infrastructure=src/infra/**",
            )

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["cycles"][0]["path"], ["domain", "infrastructure", "domain"])

    def test_layer_level_allows_module_selector_to_name_layer(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            write(tmp_path / "src" / "domain" / "model.ts", 'import "../infra/db";\n')
            write(tmp_path / "src" / "infra" / "db.ts", 'import "../domain/model";\n')

            payload, exit_code = analyze(
                tmp_path,
                "--level",
                "layer",
                "--layer",
                "domain=src/domain/**",
                "--layer",
                "infrastructure=src/infra/**",
                "--module",
                "domain",
            )

            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["target_modules"], ["domain"])
            self.assertEqual(payload["target_nodes"], ["domain"])
            self.assertEqual(payload["cycles"][0]["path"], ["domain", "infrastructure", "domain"])
            self.assertEqual(payload["warnings"], [])

    def test_layer_level_reports_disallowed_layer_dependency(self) -> None:
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            write(
                tmp_path / "layers.json",
                json.dumps(
                    {
                        "layers": {
                            "domain": ["src/domain/**"],
                            "application": ["src/app/**"],
                            "infrastructure": ["src/infra/**"],
                        },
                        "allowed": ["application -> domain", "infrastructure -> domain"],
                    }
                ),
            )
            write(tmp_path / "src" / "domain" / "model.ts", 'import "../infra/db";\n')
            write(tmp_path / "src" / "infra" / "db.ts", "export const db = {};\n")

            payload, exit_code = analyze(tmp_path, "--level", "layer", "--layer-config", "layers.json")

            self.assertEqual(exit_code, 2)
            self.assertIs(payload["cycles_found"], False)
            self.assertIs(payload["layer_violations_found"], True)
            self.assertEqual(
                payload["allowed_layer_dependencies"],
                [
                    {"from": "application", "to": "domain"},
                    {"from": "infrastructure", "to": "domain"},
                ],
            )
            self.assertEqual(payload["layer_violations"][0]["from"], "domain")
            self.assertEqual(payload["layer_violations"][0]["to"], "infrastructure")
            self.assertEqual(payload["layer_violations"][0]["from_file"], "src/domain/model.ts")


if __name__ == "__main__":
    unittest.main()
