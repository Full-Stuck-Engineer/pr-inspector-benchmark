"""Guards the Clean Architecture dependency rule for the benchmark package.

Dependencies point inward only: domain imports nothing but the standard library, and
application imports the domain only.
"""

import ast
import sys
from pathlib import Path

PACKAGE = "pr_inspector_benchmark"
SRC = Path(__file__).resolve().parents[1] / "src" / PACKAGE


def find_violations(layer_dir: Path, allowed_layers: set[str]) -> list[str]:
    """List imports in ``layer_dir`` that leave the standard library and ``allowed_layers``."""
    violations: list[str] = []
    for path in sorted(layer_dir.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level:
                # `from .x import y` stays in the layer; `from ..x import y` leaves it.
                if node.level > 1:
                    violations.append(f"{path.name}: relative import leaves the layer")
                continue

            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                continue

            for module in modules:
                top, _, rest = module.partition(".")
                if top == PACKAGE:
                    layer = rest.partition(".")[0]
                    if layer not in allowed_layers:
                        violations.append(f"{path.name}: {module}")
                elif top not in sys.stdlib_module_names:
                    violations.append(f"{path.name}: {module}")
    return violations


def test_domain_imports_only_the_standard_library_and_itself():
    assert find_violations(SRC / "domain", {"domain"}) == []


def test_application_imports_only_the_domain_and_itself():
    assert find_violations(SRC / "application", {"domain", "application"}) == []


def test_checker_flags_third_party_and_outward_imports(tmp_path: Path):
    # Without this the two tests above pass vacuously while the layers are still empty.
    (tmp_path / "bad.py").write_text(
        "import requests\n"
        f"from {PACKAGE}.infrastructure import loader\n"
        "from ..interface import cli\n",
        encoding="utf-8",
    )

    found = find_violations(tmp_path, {"domain"})

    assert found == [
        "bad.py: requests",
        f"bad.py: {PACKAGE}.infrastructure",
        "bad.py: relative import leaves the layer",
    ]


def test_checker_accepts_standard_library_and_allowed_layers(tmp_path: Path):
    (tmp_path / "good.py").write_text(
        f"import json\nfrom pathlib import Path\nfrom {PACKAGE}.domain import entities\n",
        encoding="utf-8",
    )

    assert find_violations(tmp_path, {"domain"}) == []
