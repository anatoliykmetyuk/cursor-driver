"""Live integration tests: real ``agent`` + tmux (opt-in via env)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import libtmux
import pytest

from cursor_driver.agent import CursorAgent

MODEL = os.environ.get("CURSOR_DRIVER_MODEL", "composer-2")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.timeout(900),
]


def _kill_session(socket_name: str, session_name: str) -> None:
    try:
        server = libtmux.Server(socket_name=socket_name)
        s = server.sessions.get(session_name=session_name)
        if s is not None:
            s.kill()
    except Exception:
        pass


def test_I1_cold_start_await_ready(
    tmp_path: Path, unique_session_ids: tuple[str, str]
) -> None:
    soc, label = unique_session_ids
    agent = CursorAgent(
        tmp_path,
        MODEL,
        tmux_socket=soc,
        label=label,
        quiet=True,
        kill_session=False,
    )
    try:
        assert agent.start(prompt=None) == 0
        assert agent.pane is not None
        agent.await_ready(timeout_s=900)
        assert agent.is_ready()
        assert not agent.is_trust_prompt()
    finally:
        _kill_session(soc, label)


def test_I2_optional_trust_phase_recorded(
    tmp_path: Path, unique_session_ids: tuple[str, str]
) -> None:
    soc, label = unique_session_ids
    agent = CursorAgent(
        tmp_path,
        MODEL,
        tmux_socket=soc,
        label=label,
        quiet=True,
        kill_session=False,
    )
    try:
        assert agent.start(prompt=None) == 0
        assert agent.pane is not None
        _ = agent.is_trust_prompt()
        agent.await_ready(timeout_s=900)
        assert agent.is_ready()
    finally:
        _kill_session(soc, label)


def test_I3_start_with_prompt_one_shot(tmp_path: Path, unique_session_ids: tuple[str, str]) -> None:
    soc, label = unique_session_ids
    proof = tmp_path / "proof_integration.txt"
    instruction = (
        f"Create a file at exactly this path with UTF-8 content OK:\\n{proof}\\n"
        "Reply with a single word DONE when finished."
    )
    agent = CursorAgent(
        tmp_path,
        MODEL,
        tmux_socket=soc,
        label=label,
        quiet=True,
        kill_session=True,
    )
    rc = agent.start(prompt=instruction)
    assert rc == 0
    if proof.exists():
        text = proof.read_text(encoding="utf-8").strip()
        assert "OK" in text or text == "OK"


@pytest.mark.parametrize("turns", [1, 2])
def test_multi_turn_ready_busy_done(
    tmp_path: Path,
    unique_session_ids: tuple[str, str],
    turns: int,
) -> None:
    soc, label = unique_session_ids
    log = tmp_path / "turn_log.txt"
    agent = CursorAgent(
        tmp_path,
        MODEL,
        tmux_socket=soc,
        label=label,
        quiet=True,
        kill_session=False,
    )
    try:
        assert agent.start(prompt=None) == 0
        agent.await_ready(timeout_s=900)
        for t in range(turns):
            assert agent.is_ready()
            token = uuid.uuid4().hex[:8]
            agent.send_prompt(
                f"Append exactly one line to {log}: TURN {t} {token}\\n"
                "Then stop. Reply DONE.",
                timeout_s=900,
            )
            agent.await_done(timeout_s=900)
            agent.await_ready(timeout_s=900)
            assert agent.is_ready()
            if log.exists():
                content = log.read_text(encoding="utf-8")
                assert token in content
    finally:
        _kill_session(soc, label)


def test_K1_kill_session_true_session_removed(
    tmp_path: Path, unique_session_ids: tuple[str, str]
) -> None:
    soc, label = unique_session_ids
    agent = CursorAgent(
        tmp_path,
        MODEL,
        tmux_socket=soc,
        label=label,
        quiet=True,
        kill_session=True,
    )
    assert agent.start(prompt=None) == 0
    server = libtmux.Server(socket_name=soc)
    assert server.sessions.get(session_name=label, default=None) is None


def test_K2_kill_session_false_session_survives(
    tmp_path: Path, unique_session_ids: tuple[str, str]
) -> None:
    soc, label = unique_session_ids
    agent = CursorAgent(
        tmp_path,
        MODEL,
        tmux_socket=soc,
        label=label,
        quiet=True,
        kill_session=False,
    )
    try:
        assert agent.start(prompt=None) == 0
        server = libtmux.Server(socket_name=soc)
        assert server.sessions.get(session_name=label) is not None
    finally:
        _kill_session(soc, label)


def test_quiet_suppresses_driver_prints(
    tmp_path: Path, unique_session_ids: tuple[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    soc, label = unique_session_ids
    agent = CursorAgent(
        tmp_path,
        MODEL,
        tmux_socket=soc,
        label=label,
        quiet=True,
        kill_session=True,
    )
    rc = agent.start(prompt=None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "starting agent" not in out
    assert "attach with" not in out
