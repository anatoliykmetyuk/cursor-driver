"""TUI markers, tmux pane capture, and Cursor agent lifecycle helpers."""

from __future__ import annotations

import re
import time

import libtmux

# ---------------------------------------------------------------------------
# TUI markers
# ---------------------------------------------------------------------------

# Shown on the idle agent TUI once loaded (Cursor Agent ~2026.04+). Combined with
# BUSY_MARKER absence in :func:`is_ready` to mean "ready for input".
FOOTER_MARKER = "Auto-run"
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
        if is_busy(tail_text(pane, n_lines=20)):
            return
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError("agent never started working")


def await_done(pane: libtmux.Pane, timeout_s: float = AGENT_TIMEOUT_S) -> None:
    """Wait for a busy agent to finish."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not is_busy(tail_text(pane, n_lines=20)):
            return
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(f"agent work exceeded {timeout_s}s")
