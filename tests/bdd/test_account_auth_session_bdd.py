"""Phase 9 Task 29: BDD acceptance suite (plan Task 29).

Binds the 55 non-browser scenarios of
``docs/behavior/features/account-auth-session.feature`` to the step
definitions in ``tests/bdd/step_defs/test_auth_steps.py``.

pytest-bdd 8.x (installed) removed the pre-8 ``filter_`` tag-expression
argument and routes Gherkin tags through pytest markers instead (9 scenarios
carry the ``@browser`` tag; they are deselected by
``tests/bdd/conftest.py::pytest_collection_modifyitems``, which emulates
``filter_="not browser"``). Plain ``pytest tests/bdd`` therefore collects
exactly the 55 backend scenarios.
"""

from __future__ import annotations

from pytest_bdd import scenarios

from tests.bdd.step_defs.test_auth_steps import *  # noqa: F403  (step registry)

# Load all 55 non-browser scenarios from the feature file.
scenarios("../../docs/behavior/features/account-auth-session.feature")
