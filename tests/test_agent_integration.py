"""Live integration tests: real ``agent`` + tmux (opt-in via env)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import libtmux
import pytest

from cursor_driver.agent import CursorAgent

MODEL = os.environ.get("CURSOR_DRIVER_MODEL", "composer-2-fast")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.timeout(900),
]


def test_I1_cold_start_await_ready(tmp_path: Path, unique_session_ids: tuple[str, str]) -> None:
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
        agent.stop()


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
        agent.stop()


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
                f"Append exactly one line to {log}: TURN {t} {token}\\nThen stop. Reply DONE.",
                timeout_s=900,
            )
            agent.await_done(timeout_s=900)
            agent.await_ready(timeout_s=900)
            assert agent.is_ready()
            if log.exists():
                content = log.read_text(encoding="utf-8")
                assert token in content
    finally:
        agent.stop()


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
        agent.stop()


def test_K3_stop_kills_session_when_kill_session_false(
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
    assert agent.start(prompt=None) == 0
    assert agent.pane is not None
    agent.stop()
    assert agent.pane is None
    server = libtmux.Server(socket_name=soc)
    assert server.sessions.get(session_name=label, default=None) is None


def test_send_prompt_as_file_single_followup(
    tmp_path: Path, unique_session_ids: tuple[str, str]
) -> None:
    soc, label = unique_session_ids
    token = uuid.uuid4().hex[:12]
    proof = tmp_path / f"proof_file_mode_{token}.txt"
    instruction = (
        f"Create a UTF-8 file at exactly this path with content: OK-{token}\\n"
        f"{proof}\\n"
        "Reply DONE when finished."
    )
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
        agent.send_prompt(instruction, timeout_s=900, prompt_as_file=True)
        agent.await_done(timeout_s=900)
        agent.await_ready(timeout_s=900)
    finally:
        agent.stop()

    assert proof.exists()
    text = proof.read_text(encoding="utf-8").strip()
    assert f"OK-{token}" in text or text == f"OK-{token}"


def test_send_prompt_as_file_multi_chunk(
    tmp_path: Path, unique_session_ids: tuple[str, str]
) -> None:
    """Three follow-up chunks appending distinct tokens — harness chunking pattern."""
    soc, label = unique_session_ids
    log = tmp_path / "chunk_log.txt"
    tokens = [uuid.uuid4().hex[:10] for _ in range(3)]
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
        for i, tok in enumerate(tokens):
            agent.send_prompt(
                (f"Append exactly one line to {log}: CHUNK{i} {tok}\\nThen stop. Reply DONE."),
                timeout_s=900,
                prompt_as_file=True,
            )
            agent.await_done(timeout_s=900)
            agent.await_ready(timeout_s=900)
    finally:
        agent.stop()

    assert log.exists()
    body = log.read_text(encoding="utf-8")
    for i, tok in enumerate(tokens):
        assert f"CHUNK{i}" in body and tok in body
    for i in range(len(tokens) - 1):
        assert body.find(tokens[i]) < body.find(tokens[i + 1])


def test_send_prompt_as_file_long_prompt(
    tmp_path: Path, unique_session_ids: tuple[str, str]
) -> None:
    soc, label = unique_session_ids
    u = uuid.uuid4().hex[:8]
    a = tmp_path / f"long_a_{u}.txt"
    b = tmp_path / f"long_b_{u}.txt"
    c = tmp_path / f"long_c_{u}.txt"
    filler = "\n".join([f"Context line {n} — ignore this paragraph." for n in range(28)])
    instruction = f"""Follow every step below. Reply DONE when all files exist.

{filler}

Step 1: Write exactly the text ALPHA-{u} (no newline) to file:
{a}

Step 2: Write exactly the text BETA-{u} (no newline) to file:
{b}

Step 3: Write exactly the text GAMMA-{u} (no newline) to file:
{c}
"""
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
        agent.send_prompt(instruction, timeout_s=900, prompt_as_file=True)
        agent.await_done(timeout_s=900)
    finally:
        agent.stop()

    assert a.read_text(encoding="utf-8").strip() == f"ALPHA-{u}"
    assert b.read_text(encoding="utf-8").strip() == f"BETA-{u}"
    assert c.read_text(encoding="utf-8").strip() == f"GAMMA-{u}"


def test_start_with_prompt_then_file_followup(
    tmp_path: Path, unique_session_ids: tuple[str, str]
) -> None:
    """First turn ``start(prompt=...)``; second ``send_prompt(..., prompt_as_file=True)``."""
    soc, label = unique_session_ids
    secret = uuid.uuid4().hex[:12]
    round1 = tmp_path / "round1.txt"
    round2 = tmp_path / "round2.txt"
    first_prompt = (
        f"Create a UTF-8 file at {round1} with exactly two lines:\\n"
        f"LINE1:{secret}\\nLINE2:IGNORE\\n"
        "Reply DONE when finished."
    )
    follow = (
        f"Read the file at {round1}. Create {round2} with a single line that is "
        f"the LINE1 value from round1 repeated twice with no separator "
        f"(e.g. if LINE1 is abc then write abcabc). Reply DONE."
    )
    agent = CursorAgent(
        tmp_path,
        MODEL,
        tmux_socket=soc,
        label=label,
        quiet=True,
        kill_session=False,
    )
    try:
        assert agent.start(prompt=first_prompt) == 0
        assert round1.exists()
        agent.send_prompt(follow, timeout_s=900, prompt_as_file=True)
        agent.await_done(timeout_s=900)
    finally:
        agent.stop()

    assert round2.exists()
    assert round2.read_text(encoding="utf-8").strip() == secret * 2


def test_prompt_as_file_temp_cleanup_on_stop(
    tmp_path: Path, unique_session_ids: tuple[str, str]
) -> None:
    soc, label = unique_session_ids
    log = tmp_path / "cleanup_log.txt"
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
        for _ in range(2):
            tok = uuid.uuid4().hex[:8]
            agent.send_prompt(
                f"Append one line to {log}: {tok}\\nThen stop. Reply DONE.",
                timeout_s=900,
                prompt_as_file=True,
            )
            agent.await_done(timeout_s=900)
            agent.await_ready(timeout_s=900)
        assert list(tmp_path.glob("cursor-driver-prompt-*.md"))
    finally:
        agent.stop()

    assert not list(tmp_path.glob("cursor-driver-prompt-*.md"))


@pytest.mark.parametrize("prompt_as_file", [True, False])
def test_send_prompt_direct_vs_file_same_result(
    tmp_path: Path,
    unique_session_ids: tuple[str, str],
    prompt_as_file: bool,
) -> None:
    soc, label = unique_session_ids
    token = uuid.uuid4().hex[:12]
    proof = tmp_path / f"parity_{prompt_as_file}_{token}.txt"
    instruction = (
        f"Create a UTF-8 file at {proof} with content exactly: TOKEN={token}\\n"
        "Reply DONE when finished."
    )
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
        agent.send_prompt(instruction, timeout_s=900, prompt_as_file=prompt_as_file)
        agent.await_done(timeout_s=900)
    finally:
        agent.stop()

    assert proof.exists()
    assert token in proof.read_text(encoding="utf-8")


def test_quiet_suppresses_driver_prints(
    tmp_path: Path,
    unique_session_ids: tuple[str, str],
    capsys: pytest.CaptureFixture[str],
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
