from __future__ import annotations

import sys
from pathlib import Path

# Make the shared test-fakes package importable from test modules under
# packages/py/core/tests (tests are not part of the installed app-core wheel).
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
