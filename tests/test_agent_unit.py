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


def test_send_prompt_as_file_creates_temp_and_sends_read_instruction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``prompt_as_file=True`` writes UTF-8 to workspace; send_keys uses the read-file line."""
    monkeypatch.setattr("cursor_driver.agent.time.sleep", lambda _s: None)
    pane = MockPane([[F], [F], [f"{F}\n{B}"]])
    agent = CursorAgent(tmp_path, "composer-2", kill_session=False)
    agent.pane = pane
    body = "some long text with\nnewlines and unicode: é"
    agent.send_prompt(body, prompt_as_file=True)

    matches = list(tmp_path.glob("cursor-driver-prompt-*.md"))
    assert len(matches) == 1
    prompt_path = matches[0]
    assert prompt_path.read_text(encoding="utf-8") == body
    assert agent._prompt_paths == [prompt_path]

    assert pane.send_keys_calls[0][0] == f"Read and follow the instructions in {prompt_path}"
    assert pane.send_keys_calls[0][1] is False
    assert pane.send_keys_calls[1] == ("", True)


def test_send_prompt_as_file_cleanup_removes_tracked_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("cursor_driver.agent.time.sleep", lambda _s: None)
    pane = MockPane(
        [
            [F],
            [F],
            [f"{F}\n{B}"],
            [F],
            [F],
            [f"{F}\n{B}"],
        ]
    )
    agent = CursorAgent(tmp_path, "composer-2", kill_session=False)
    agent.pane = pane
    agent.send_prompt("first", prompt_as_file=True)
    agent.send_prompt("second", prompt_as_file=True)
    paths = list(tmp_path.glob("cursor-driver-prompt-*.md"))
    assert len(paths) == 2
    assert {p.read_text(encoding="utf-8") for p in paths} == {"first", "second"}

    agent.stop()

    assert list(tmp_path.glob("cursor-driver-prompt-*.md")) == []
    assert agent._prompt_paths == []
