"""Tmux-based orchestration of the Cursor ``agent`` CLI.

Starts ``agent`` in detached tmux sessions, sends prompts via ``send-keys``,
and polls TUI state to detect lifecycle transitions (trust dialog, ready,
busy, done).  Low-level TUI helpers live in :mod:`cursor_driver.tui_ops`.
The :class:`~cursor_driver.agent.CursorAgent` driver is in :mod:`cursor_driver.agent`.
"""

from __future__ import annotations

from .agent import CursorAgent

__all__ = ["CursorAgent"]
