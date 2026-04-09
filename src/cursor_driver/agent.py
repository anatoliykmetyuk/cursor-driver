"""High-level tmux driver for the Cursor ``agent`` CLI."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import libtmux

from . import tui_ops


class CursorAgent:
    """Drive a Cursor ``agent`` instance inside a detached tmux session.

    Construct with *workspace*, *model*, and optional socket / label / flags, then
    call :meth:`start` to launch the CLI and populate :attr:`pane`.  Use
    :meth:`send_prompt` to type into that TUI after a session-only start.

    When :meth:`start` is given a *prompt* string, the text is written to a temp
    file under *workspace*, a short instruction is sent so the agent reads that
    file, and the call blocks until the agent finishes (busy → idle).  When
    *prompt* is omitted, only the tmux session is started.

    For a two-step flow (start empty, then :meth:`send_prompt` one or more times),
    pass ``kill_session=False`` so the session stays alive.  Call :meth:`stop`
    to kill that session explicitly.  The default ``kill_session=True`` tears
    the session down in a ``finally`` block after :meth:`start` returns; the
    returned :attr:`pane` is then no longer usable for further input.

    Lifecycle predicates (:meth:`is_trust_prompt`, :meth:`is_ready`, :meth:`is_busy`)
    capture the current pane tail and delegate to :mod:`cursor_driver.tui_ops`.
    Waiters (:meth:`await_ready`, :meth:`await_busy`, :meth:`await_done`) delegate
    there on :attr:`pane`.
    """

    def __init__(
        self,
        workspace: Path,
        model: str,
        *,
        tmux_socket: str = "cursor-agent",
        label: str = "agent",
        quiet: bool = False,
        kill_session: bool = True,
    ) -> None:
        """
        Parameters
        ----------
        workspace:
            Working directory for the agent (and, when :meth:`start` is called
            with a prompt, where the temp instruction file is created).
        model:
            Model identifier passed to ``agent --model``.
        tmux_socket:
            Name of the tmux server socket (``tmux -L <socket>``).  Use distinct
            sockets to isolate different agent groups.
        label:
            Session name and prefix for log lines (``tmux attach -t <label>``).
        quiet:
            If ``True``, suppress ``starting agent`` / attach hint / ``done`` lines.
        kill_session:
            If ``True`` (default), kill the tmux session in ``finally`` after
            :meth:`start` returns.  Set ``False`` to keep the session for
            ``tmux attach`` or follow-up :meth:`send_prompt` calls.
        """
        self.workspace = workspace
        self.model = model
        self.tmux_socket = tmux_socket
        self.label = label
        self.quiet = quiet
        self.kill_session = kill_session
        self.pane: libtmux.Pane | None = None
        self._prompt_paths: list[Path] = []

    def _discard_prompt_file(self, path: Path | str) -> None:
        p = Path(path)
        p.unlink(missing_ok=True)
        try:
            self._prompt_paths.remove(p)
        except ValueError:
            pass

    def _cleanup_all_prompt_files(self) -> None:
        for p in list(self._prompt_paths):
            p.unlink(missing_ok=True)
        self._prompt_paths.clear()

    def _require_pane(self) -> libtmux.Pane:
        if self.pane is None:
            raise RuntimeError("CursorAgent is not started; call start() first")
        return self.pane

    def stop(self) -> None:
        """Kill the tmux session for this agent and clear :attr:`pane`.

        Tears down the ``agent`` process that was started as the session's
        initial command.  Safe if the session does not exist or was already
        removed.  Use this to stop a long-lived session started with
        ``kill_session=False`` without waiting for :meth:`start` to return.
        """
        try:
            server = libtmux.Server(socket_name=self.tmux_socket)
            s = server.sessions.get(session_name=self.label)
            if s is not None:
                s.kill()
        except Exception:
            pass
        self._cleanup_all_prompt_files()
        self.pane = None

    # --- lifecycle predicates (capture pane, delegate to :mod:`cursor_driver.tui_ops`) ---

    def is_trust_prompt(self) -> bool:
        """Trust dialog is active (waiting for ``a`` / ``q``).

        Uses :func:`~cursor_driver.tui_ops.tail_text` on :attr:`pane` and
        :func:`~cursor_driver.tui_ops.is_trust_prompt`.
        """
        return tui_ops.is_trust_prompt(tui_ops.tail_text(self._require_pane(), n_lines=20))

    def is_ready(self) -> bool:
        """Agent is idle and waiting for user input.

        Uses :func:`~cursor_driver.tui_ops.tail_text` on :attr:`pane` and
        :func:`~cursor_driver.tui_ops.is_ready`.
        """
        return tui_ops.is_ready(tui_ops.tail_text(self._require_pane(), n_lines=20))

    def is_busy(self) -> bool:
        """Agent is working (generating, editing, running tools).

        Uses :func:`~cursor_driver.tui_ops.tail_text` on :attr:`pane` and
        :func:`~cursor_driver.tui_ops.is_busy`.
        """
        return tui_ops.is_busy(tui_ops.tail_text(self._require_pane(), n_lines=20))

    # --- lifecycle waiters (delegate to :mod:`cursor_driver.tui_ops`) ---

    def await_ready(self, *, timeout_s: float = tui_ops.AGENT_TIMEOUT_S) -> None:
        """Poll until the agent is ready for input.

        Uses :attr:`pane`.  Delegates to :func:`~cursor_driver.tui_ops.await_ready`.
        """
        tui_ops.await_ready(self._require_pane(), timeout_s=timeout_s)

    def await_busy(self, *, timeout_s: float = tui_ops.AGENT_TIMEOUT_S) -> None:
        """Wait until the agent starts working.

        Uses :attr:`pane`.  Delegates to :func:`~cursor_driver.tui_ops.await_busy`.
        """
        tui_ops.await_busy(self._require_pane(), timeout_s=timeout_s)

    def await_done(self, *, timeout_s: float = tui_ops.AGENT_TIMEOUT_S) -> None:
        """Wait for a busy agent to finish.

        Uses :attr:`pane`.  Delegates to :func:`~cursor_driver.tui_ops.await_done`.
        """
        tui_ops.await_done(self._require_pane(), timeout_s=timeout_s)

    def send_prompt(
        self,
        text: str,
        *,
        timeout_s: float = tui_ops.AGENT_TIMEOUT_S,
        prompt_as_file: bool = True,
    ) -> None:
        """Wait until the agent TUI is ready, then send the prompt and press Enter.

        When *prompt_as_file* is ``True`` (default), *text* is written to a temp
        ``.md`` file under :attr:`workspace`, tracked until :meth:`stop`, and a
        short ``Read and follow the instructions in <path>`` line is sent — the
        same pattern as :meth:`start` with a *prompt*.  Use ``False`` to send
        *text* directly via tmux ``send-keys`` (only for short lines).

        Blocks until the agent has started working before returning.

        Raises
        ------
        RuntimeError
            If :meth:`start` has not been called successfully yet (no :attr:`pane`).
        """
        pane = self._require_pane()
        self.await_ready(timeout_s=timeout_s)
        if prompt_as_file:
            fd, prompt_path = tempfile.mkstemp(
                suffix=".md",
                prefix="cursor-driver-prompt-",
                dir=str(self.workspace),
            )
            os.write(fd, text.encode("utf-8"))
            os.close(fd)
            p = Path(prompt_path)
            self._prompt_paths.append(p)
            text_to_send = f"Read and follow the instructions in {prompt_path}"
        else:
            text_to_send = text
        pane.send_keys(text_to_send, enter=False)
        time.sleep(0.2)
        pane.send_keys("", enter=True)
        self.await_busy()

    def start(self, prompt: str | None = None) -> int:
        """Start ``agent`` in tmux and set :attr:`pane`.

        Spawns ``agent`` in a new detached session (replacing any existing
        session with the same *label*).  If *prompt* is ``None``, returns as soon
        as the pane exists.  If *prompt* is a string, writes it to a temp ``.md``
        file, sends ``Read and follow the instructions in <path>`` via the same
        mechanism as :meth:`send_prompt`, then waits until the agent leaves the
        busy state and returns to idle.

        Parameters
        ----------
        prompt:
            When set, full prompt text written to a temp file and referenced from
            the TUI.  When omitted, only the tmux session is started.

        Returns
        -------
        int
            ``0`` on success, ``127`` if the ``agent`` executable is not on
            ``PATH``, ``1`` on timeout or other failure.  On failure after a
            session was created, :attr:`pane` may still be set for inspection.
        """
        agent_bin = shutil.which("agent")
        if not agent_bin:
            print("error: `agent` not found on PATH (install Cursor CLI)", file=sys.stderr)
            self.pane = None
            return 127

        server = libtmux.Server(socket_name=self.tmux_socket)
        session_name = self.label

        try:
            old = server.sessions.get(session_name=session_name)
            if old is not None:
                old.kill()
        except Exception:
            pass

        # Orphan temp prompts from a prior session on this agent instance.
        self._cleanup_all_prompt_files()

        prompt_path: str | None = None
        self.pane = None
        try:
            if prompt is not None:
                fd, prompt_path = tempfile.mkstemp(
                    suffix=".md",
                    prefix="cursor-driver-prompt-",
                    dir=str(self.workspace),
                )
                os.write(fd, prompt.encode("utf-8"))
                os.close(fd)
                self._prompt_paths.append(Path(prompt_path))

            agent_cmd = f"{agent_bin} --yolo --model {self.model} --workspace {self.workspace}"
            if not self.quiet:
                print(f"[{self.label}] starting agent in tmux ...", flush=True)
                print(
                    f"[{self.label}] attach with:  tmux -L {self.tmux_socket} "
                    f"attach -t {session_name}",
                    flush=True,
                )

            session = server.new_session(
                session_name=session_name,
                window_command=agent_cmd,
                attach=False,
            )
            pane = session.active_window.active_pane
            assert pane is not None
            self.pane = pane

            if prompt is None:
                return 0

            assert prompt_path is not None
            short_prompt = f"Read and follow the instructions in {prompt_path}"
            self.send_prompt(short_prompt, prompt_as_file=False)
            self.await_done()
            if not self.quiet:
                print(f"[{self.label}] done.", flush=True)
            return 0

        except TimeoutError as exc:
            print(f"[{self.label}] timeout: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"[{self.label}] error: {exc}", file=sys.stderr)
            return 1
        finally:
            if prompt_path is not None:
                self._discard_prompt_file(prompt_path)
            if self.kill_session:
                self.stop()
