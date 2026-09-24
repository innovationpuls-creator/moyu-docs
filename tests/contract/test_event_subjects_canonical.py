"""Arch 04 / doc 28 §25: registry event subjects === canonical code constants
(drift guard between contracts/registry.yaml and app_infra.events.subjects)."""

from __future__ import annotations

import re

import pytest
import yaml
from app_infra.events.subjects import EVENT_SUBJECTS, RESERVED_PREFIXES

_PATTERN = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9-]+)*$")

REGISTRY_SUBJECTS: dict[str, str] = {}


@pytest.fixture(scope="module", autouse=True)
def _load_registry() -> None:
    data = yaml.safe_load(open("contracts/registry.yaml"))
    contracts = data["contracts"]
    for entry in contracts if isinstance(contracts, list) else contracts.values():
        subject = entry.get("eventSubject")
        if subject:
            REGISTRY_SUBJECTS[entry["logicalName"]] = subject


def test_every_registry_subject_has_a_code_constant() -> None:
    code_values = set(EVENT_SUBJECTS.values())
    for logical_name, subject in REGISTRY_SUBJECTS.items():
        assert subject in code_values, (
            f"{logical_name} subject {subject} missing from EVENT_SUBJECTS"
        )


def test_code_constants_never_drift_into_unknown_subjects() -> None:
    registry_values = set(REGISTRY_SUBJECTS.values())
    known_wire_subjects = {"resource.checkpoint", "rt.broadcast"}
    for key, subject in EVENT_SUBJECTS.items():
        assert subject in registry_values or subject in known_wire_subjects, (
            f"{key} constant {subject} not in registry and not a known wire subject"
        )


def test_subjects_match_canonical_pattern_and_not_reserved() -> None:
    for subject in EVENT_SUBJECTS.values():
        assert _PATTERN.match(subject), f"pattern violation: {subject}"
        assert not subject.startswith("dom."), f"reserved prefix: {subject}"
    for prefix in RESERVED_PREFIXES:
        assert _PATTERN.match(prefix) or prefix.count(".") >= 1
