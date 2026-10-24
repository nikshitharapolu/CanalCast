"""No-I/O boundary test for the CanalCast Calculation_Core (Task 8.1).

The pure calculation modules must be free of file and network I/O so that the
calculation layer stays deterministic and testable in isolation: only the
Data_Loader (``loader.py``) is permitted to touch the filesystem.

This test parses each core module's source with :mod:`ast` and asserts that it
imports none of a forbidden set of I/O / network library roots, and that it
never calls the builtin ``open``. Parsing the AST (rather than importing the
module or using a textual scan alone) keeps the check robust against comments,
strings, and import aliasing.

Supports Requirements: 1.3, 1.7, 19.4.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Pure Calculation_Core modules that MUST NOT perform file or network I/O.
# ``loader.py`` is deliberately excluded: it is the one module allowed to read
# files and therefore legitimately imports pandas/csv/etc.
CORE_MODULES = [
    "calculations",
    "comparison",
    "results",
    "models",
    "explain",
]

# Module roots whose presence indicates file or network I/O.
FORBIDDEN_IMPORTS = {
    "os",
    "io",
    "socket",
    "subprocess",
    "urllib",
    "requests",
    "http",
    "pathlib",
    "pandas",
    "csv",
    "json",
    "shutil",
    "sqlite3",
    "aiohttp",
    "httpx",
}

_CANALCAST_DIR = Path(__file__).resolve().parents[1] / "src" / "canalcast"


def _module_path(name: str) -> Path:
    return _CANALCAST_DIR / f"{name}.py"


def _collect_imported_roots(tree: ast.AST) -> list[tuple[str, int]]:
    """Return (root_module, lineno) pairs for every import in the tree.

    Relative imports (``from .models import ...``) have ``level > 0`` and carry
    no absolute root to forbid, so they are skipped entirely.
    """
    roots: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                roots.append((root, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # Relative import: no absolute module root to check.
            if node.level and node.level > 0:
                continue
            if node.module:
                root = node.module.split(".", 1)[0]
                roots.append((root, node.lineno))
    return roots


def _calls_open(tree: ast.AST) -> list[int]:
    """Return line numbers where the builtin ``open`` is called directly."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "open":
                lines.append(node.lineno)
    return lines


@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_core_module_has_no_io_imports(module_name: str) -> None:
    """Each core module imports none of the forbidden I/O/network libraries."""
    path = _module_path(module_name)
    assert path.exists(), f"Expected core module not found: {path}"

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    offenders = [
        (root, lineno)
        for root, lineno in _collect_imported_roots(tree)
        if root in FORBIDDEN_IMPORTS
    ]

    assert not offenders, (
        f"Calculation_Core module '{module_name}.py' performs forbidden I/O: "
        + ", ".join(
            f"imports '{root}' (line {lineno})" for root, lineno in offenders
        )
        + ". Only loader.py may touch the filesystem (Requirements 1.3, 1.7, 19.4)."
    )


@pytest.mark.parametrize("module_name", CORE_MODULES)
def test_core_module_does_not_call_open(module_name: str) -> None:
    """Each core module never calls the builtin ``open``.

    This is checked both via the AST (a ``Call`` whose func is ``Name('open')``)
    and via a textual guard for ``open(`` to catch any form the AST walk misses.
    """
    path = _module_path(module_name)
    assert path.exists(), f"Expected core module not found: {path}"

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    open_call_lines = _calls_open(tree)
    assert not open_call_lines, (
        f"Calculation_Core module '{module_name}.py' calls the builtin open() at "
        f"line(s) {open_call_lines}. Core modules must not perform file I/O "
        f"(Requirements 1.3, 1.7, 19.4)."
    )

    assert "open(" not in source, (
        f"Calculation_Core module '{module_name}.py' references 'open(' in its "
        f"source. Core modules must not perform file I/O "
        f"(Requirements 1.3, 1.7, 19.4)."
    )
