"""Tmux-based orchestration of the Cursor ``agent`` CLI.

Starts ``agent`` in detached tmux sessions, sends prompts via ``send-keys``,
and polls TUI state to detect lifecycle transitions (trust dialog, ready,
busy, done).  All Cursor-agent-specific markers and heuristics live here so
callers only interact with high-level functions.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import libtmux

# ---------------------------------------------------------------------------
# TUI markers
# ---------------------------------------------------------------------------

FOOTER_MARKER = "/ commands \u00b7 @ files \u00b7 ! shell"
BUSY_MARKER = "ctrl+c to stop"
TRUST_MARKER = "Trust this workspace"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

POLL_INTERVAL_S = 1.0
AGENT_TIMEOUT_S = 30 * 60  # 30 min per agent invocation

# ---------------------------------------------------------------------------
# Tmux helpers
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[\d;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def tail_text(pane: libtmux.Pane, n_lines: int = 10) -> str:
    """Capture the last *n_lines* of the pane, ANSI-stripped."""
    lines = pane.capture_pane(start=-n_lines)
    return strip_ansi("\n".join(lines))


# ---------------------------------------------------------------------------
# Lifecycle predicates – each describes a mutually exclusive TUI state.
# All operate on a pre-captured text snapshot so callers control capture scope.
# ---------------------------------------------------------------------------

def is_trust_prompt(text: str) -> bool:
    """Trust dialog is active (waiting for ``a`` / ``q``).

    The footer is never visible while the trust dialog is up.
    """
    return TRUST_MARKER in text and FOOTER_MARKER not in text


def is_ready(text: str) -> bool:
    """Agent is idle and waiting for user input."""
    return FOOTER_MARKER in text and BUSY_MARKER not in text


def is_busy(text: str) -> bool:
    """Agent is working (generating, editing, running tools)."""
    return BUSY_MARKER in text


# ---------------------------------------------------------------------------
# Lifecycle actions
# ---------------------------------------------------------------------------

def handle_trust(pane: libtmux.Pane, timeout_s: float = AGENT_TIMEOUT_S) -> None:
    """Accept the workspace-trust dialog and wait for it to disappear.

    Sends ``a`` exactly once, then blocks until the trust prompt is no longer
    the active screen.
    """
    pane.send_keys("a", enter=False)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not is_trust_prompt(tail_text(pane, n_lines=20)):
            return
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError("trust dialog did not dismiss")


# ---------------------------------------------------------------------------
# Lifecycle waiters
# ---------------------------------------------------------------------------

def await_ready(pane: libtmux.Pane, timeout_s: float = AGENT_TIMEOUT_S) -> None:
    """Poll until the agent is ready for input.

    If a workspace-trust dialog is encountered, handles it via :func:`handle_trust`.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        text = tail_text(pane, n_lines=20)
        if is_ready(text):
            return
        if is_trust_prompt(text):
            handle_trust(pane, deadline - time.monotonic())
            continue
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError("agent did not become ready in time")


def await_busy(pane: libtmux.Pane, timeout_s: float = AGENT_TIMEOUT_S) -> None:
    """Wait until the agent starts working."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if is_busy(tail_text(pane)):
            return
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError("agent never started working")


def await_done(pane: libtmux.Pane, timeout_s: float = AGENT_TIMEOUT_S) -> None:
    """Wait for a busy agent to finish."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not is_busy(tail_text(pane)):
            return
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"agent work exceeded {timeout_s}s")


# ---------------------------------------------------------------------------
# High-level agent runner
# ---------------------------------------------------------------------------

def run_agent(
    workspace: Path,
    model: str,
    prompt: str,
    *,
    tmux_socket: str = "cursor-agent",
    label: str = "agent",
    quiet: bool = False,
) -> int:
    """Start ``agent`` in a detached tmux session, send *prompt*, wait for completion.

    Parameters
    ----------
    workspace:
        Working directory for the agent (also where the temp prompt file is created).
    model:
        Model identifier passed to ``agent --model``.
    prompt:
        Full prompt text.  Written to a temp file under *workspace* and referenced
        via a short instruction sent to the agent TUI.
    tmux_socket:
        Name of the tmux server socket (``tmux -L <socket>``).  Each logical
        group of agents should use its own socket to stay isolated.
    label:
        Human-readable label used for the tmux session name and log lines.
    quiet:
        When ``True``, suppress informational output (start / attach / done).

    Returns
    -------
    int
        ``0`` on success, non-zero on failure.
    """
    agent_bin = shutil.which("agent")
    if not agent_bin:
        print("error: `agent` not found on PATH (install Cursor CLI)", file=sys.stderr)
        return 127

    server = libtmux.Server(socket_name=tmux_socket)
    session_name = label

    try:
        old = server.sessions.get(session_name=session_name)
        if old is not None:
            old.kill()
    except Exception:
        pass

    fd, prompt_path = tempfile.mkstemp(suffix=".md", prefix="cursor-driver-prompt-", dir=str(workspace))
    try:
        os.write(fd, prompt.encode("utf-8"))
        os.close(fd)

        agent_cmd = f"{agent_bin} --yolo --model {model} --workspace {workspace}"
        if not quiet:
            print(f"[{label}] starting agent in tmux ...", flush=True)
            print(f"[{label}] attach with:  tmux -L {tmux_socket} attach -t {session_name}", flush=True)

        session = server.new_session(
            session_name=session_name,
            window_command=agent_cmd,
            attach=False,
        )
        pane = session.active_window.active_pane
        assert pane is not None

        await_ready(pane)

        short_prompt = f"Read and follow the instructions in {prompt_path}"
        pane.send_keys(short_prompt, enter=False)
        time.sleep(0.2)
        pane.send_keys("", enter=True)

        await_busy(pane)
        await_done(pane)
        if not quiet:
            print(f"[{label}] done.", flush=True)
        return 0

    except TimeoutError as exc:
        print(f"[{label}] timeout: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[{label}] error: {exc}", file=sys.stderr)
        return 1
    finally:
        Path(prompt_path).unlink(missing_ok=True)
        try:
            s = server.sessions.get(session_name=session_name)
            if s is not None:
                s.kill()
        except Exception:
            pass
