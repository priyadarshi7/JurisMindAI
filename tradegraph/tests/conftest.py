"""Auto-marks tests by directory so `pytest -m unit` / `-m integration`
(as used in .github/workflows/ci.yml) work without decorating every test
function individually.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest


def pytest_collection_modifyitems(items: Sequence[pytest.Item]) -> None:
    for item in items:
        path = str(item.fspath)
        if "/tests/unit/" in path.replace("\\", "/"):
            item.add_marker(pytest.mark.unit)
        elif "/tests/integration/" in path.replace("\\", "/"):
            item.add_marker(pytest.mark.integration)
