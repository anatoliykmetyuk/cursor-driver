"""Unit tests for :class:`cursor_driver.agent.CursorAgent` (no live agent)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_driver.agent import CursorAgent
from cursor_driver.tui_ops import BUSY_MARKER as B
from cursor_driver.tui_ops import FOOTER_MARKER as F

from .test_tui_ops import MockPane


def test_require_pane_methods_before_start_raise(tmp_path: Path) -> None:
    agent = CursorAgent(tmp_path, "composer-2", kill_session=True)
    with pytest.raises(RuntimeError, match="not started"):
        agent.is_ready()
    with pytest.raises(RuntimeError, match="not started"):
        agent.is_busy()
    with pytest.raises(RuntimeError, match="not started"):
        agent.is_trust_prompt()
    with pytest.raises(RuntimeError, match="not started"):
        agent.await_ready(timeout_s=1.0)
    with pytest.raises(RuntimeError, match="not started"):
        agent.send_prompt("hi")
    agent.stop()


def test_stop_is_safe_before_start_and_clears_pane(tmp_path: Path) -> None:
    agent = CursorAgent(tmp_path, "composer-2", kill_session=False)
    agent.stop()
    assert agent.pane is None
    pane = MockPane([[F]])
    agent.pane = pane
    agent.stop()
    assert agent.pane is None


def test_start_returns_127_when_agent_not_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("cursor_driver.agent.shutil.which", lambda _: None)
    agent = CursorAgent(tmp_path, "composer-2", kill_session=True)
    assert agent.start() == 127
    assert agent.pane is None


def test_initializer_stores_attributes(tmp_path: Path) -> None:
    agent = CursorAgent(
        tmp_path,
        "composer-2",
        tmux_socket="s",
        label="l",
        quiet=True,
        kill_session=False,
    )
    assert agent.workspace == tmp_path
    assert agent.model == "composer-2"
    assert agent.tmux_socket == "s"
    assert agent.label == "l"
    assert agent.quiet is True
    assert agent.kill_session is False


def test_send_prompt_ordering_after_start(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("cursor_driver.agent.time.sleep", lambda _s: None)
    pane = MockPane([[F], [f"{F}\n{B}"]])
    agent = CursorAgent(tmp_path, "composer-2", kill_session=False)
    agent.pane = pane  # simulate successful start without tmux
    agent.send_prompt("hello world", prompt_as_file=False)
    assert pane.send_keys_calls[0] == ("hello world", False)
    assert pane.send_keys_calls[1] == ("", True)
