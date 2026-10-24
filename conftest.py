"""Pytest configuration: make the project importable as ``src.canalcast``.

The test suite imports the loader as ``from src.canalcast.loader import ...``
(see ``tests/test_loader.py``). ``src`` is an implicit namespace package with no
``__init__.py``; for that import to resolve, the workspace root (the directory
holding this file) must be on ``sys.path``. Inserting it here guarantees the
import works regardless of the directory pytest is invoked from.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
