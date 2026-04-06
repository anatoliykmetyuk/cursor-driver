"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import os
import shutil
import uuid

import pytest


@pytest.fixture
def integration_enabled() -> bool:
    return os.environ.get("CURSOR_DRIVER_INTEGRATION", "").strip() in (
        "1",
        "true",
        "yes",
    )


@pytest.fixture
def has_agent_bin() -> bool:
    return shutil.which("agent") is not None


@pytest.fixture
def has_tmux() -> bool:
    return shutil.which("tmux") is not None


@pytest.fixture
def unique_session_ids() -> tuple[str, str]:
    """Distinct tmux socket name and session label per test (parallel-safe)."""
    u = uuid.uuid4().hex[:12]
    return f"cd-test-{u}", f"cd-{u}"


@pytest.fixture(autouse=True)
def _gate_integration_tests(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("integration") is None:
        return
    if os.environ.get("CURSOR_DRIVER_INTEGRATION", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        pytest.skip("Set CURSOR_DRIVER_INTEGRATION=1 to run live agent tests")
    if shutil.which("agent") is None:
        pytest.skip("Cursor `agent` CLI not on PATH")
    if shutil.which("tmux") is None:
        pytest.skip("tmux not on PATH")
