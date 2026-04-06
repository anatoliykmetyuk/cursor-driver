"""Unit tests for :mod:`cursor_driver.tui_ops` — predicates and lifecycle waiters."""

from __future__ import annotations

import pytest

from cursor_driver import tui_ops

F = tui_ops.FOOTER_MARKER
B = tui_ops.BUSY_MARKER
T = tui_ops.TRUST_MARKER


class MockPane:
    """Deterministic :class:`libtmux.Pane` stand-in for waiter tests."""

    def __init__(self, frames: list[list[str]]) -> None:
        self._frames = frames
        self._n = 0
        self.send_keys_calls: list[tuple[str, bool]] = []

    def capture_pane(self, start: int = -10) -> list[str]:
        if self._n < len(self._frames):
            out = self._frames[self._n]
            self._n += 1
        else:
            out = self._frames[-1]
        return out

    def send_keys(self, keys: str, enter: bool = False) -> None:
        self.send_keys_calls.append((keys, enter))


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tui_ops, "POLL_INTERVAL_S", 0.0)


# --- strip_ansi ---


def test_strip_ansi_empty() -> None:
    assert tui_ops.strip_ansi("") == ""


def test_strip_ansi_plain() -> None:
    assert tui_ops.strip_ansi("hello") == "hello"


def test_strip_ansi_sgr() -> None:
    raw = "\x1b[31mred\x1b[0m"
    assert tui_ops.strip_ansi(raw) == "red"


def test_strip_ansi_complex_sgr() -> None:
    raw = "\x1b[1;32mok\x1b[m"
    assert tui_ops.strip_ansi(raw) == "ok"


# --- Predicate matrix (§3.4) ---


@pytest.mark.parametrize(
    ("text", "exp_trust", "exp_ready", "exp_busy"),
    [
        ("", False, False, False),
        (F, False, True, False),
        (T, True, False, False),
        (B, False, False, True),
        (f"{F}\n{B}", False, False, True),
        (f"{F}\n{T}", False, True, False),
        (f"{T}\n{B}", True, False, True),
        (f"{F}\n{T}\n{B}", False, False, True),
        (
            f"\x1b[31m{F}\x1b[0m",
            False,
            True,
            False,
        ),
    ],
    ids=[
        "none",
        "footer_only",
        "trust_only",
        "busy_only",
        "footer_busy",
        "footer_trust_adversarial",
        "trust_busy",
        "all_three",
        "ansi_footer",
    ],
)
def test_predicate_matrix(
    text: str,
    exp_trust: bool,
    exp_ready: bool,
    exp_busy: bool,
) -> None:
    plain = tui_ops.strip_ansi(text)
    assert tui_ops.is_trust_prompt(plain) is exp_trust
    assert tui_ops.is_ready(plain) is exp_ready
    assert tui_ops.is_busy(plain) is exp_busy


def test_adversarial_footer_plus_trust_documents_ready_first_branch() -> None:
    """Footer + trust: ``is_ready`` is True before trust handling in ``await_ready``."""
    text = f"{F}\n{T}"
    assert tui_ops.is_ready(text) is True
    assert tui_ops.is_trust_prompt(text) is False


# --- await_ready R1–R6 ---


def test_R1_await_ready_already_ready_no_send_keys() -> None:
    pane = MockPane([[F]])
    tui_ops.await_ready(pane, timeout_s=5.0)
    assert pane.send_keys_calls == []


def test_R2_await_ready_blank_then_ready() -> None:
    pane = MockPane([["boot"], ["..."], [F]])
    tui_ops.await_ready(pane, timeout_s=5.0)
    assert pane.send_keys_calls == []


def test_R3_await_ready_trust_then_ready_sends_a() -> None:
    pane = MockPane([[T], [T], [F]])
    tui_ops.await_ready(pane, timeout_s=5.0)
    assert ("a", False) in pane.send_keys_calls


def test_R4_await_ready_trust_many_polls_then_ready() -> None:
    trust_lines: list[list[str]] = [[T] for _ in range(8)]
    pane = MockPane(trust_lines + [[F]])
    tui_ops.await_ready(pane, timeout_s=5.0)
    assert ("a", False) in pane.send_keys_calls


def test_R5_await_ready_never_ready_timeout() -> None:
    pane = MockPane([["waiting"]])
    with pytest.raises(TimeoutError, match="agent did not become ready in time"):
        tui_ops.await_ready(pane, timeout_s=0.05)


def test_R6_handle_trust_timeout_trust_never_clears() -> None:
    pane = MockPane([[T]])
    with pytest.raises(TimeoutError, match="trust dialog did not dismiss"):
        tui_ops.handle_trust(pane, timeout_s=0.05)


# --- handle_trust H1–H3 ---


def test_H1_handle_trust_first_snapshot_not_trust_returns_after_one_a() -> None:
    pane = MockPane([[F]])
    tui_ops.handle_trust(pane, timeout_s=5.0)
    assert pane.send_keys_calls == [("a", False)]


def test_H2_handle_trust_trust_clears_immediately_after_a() -> None:
    pane = MockPane([[T], [F]])
    tui_ops.handle_trust(pane, timeout_s=5.0)
    assert pane.send_keys_calls[0] == ("a", False)


def test_H3_handle_trust_never_clears_timeout() -> None:
    pane = MockPane([[T]])
    with pytest.raises(TimeoutError, match="trust dialog did not dismiss"):
        tui_ops.handle_trust(pane, timeout_s=0.05)


# --- await_busy B1–B3 ---


def test_B1_await_busy_already_busy() -> None:
    pane = MockPane([[B]])
    tui_ops.await_busy(pane, timeout_s=5.0)


def test_B2_await_ready_then_busy() -> None:
    pane = MockPane([[F], [F], [f"{F}\n{B}"]])
    tui_ops.await_busy(pane, timeout_s=5.0)


def test_B3_await_busy_never_busy_timeout() -> None:
    pane = MockPane([[F]])
    with pytest.raises(TimeoutError, match="agent never started working"):
        tui_ops.await_busy(pane, timeout_s=0.05)


# --- await_done D1–D3 ---


def test_D1_await_done_not_busy_first_poll_returns_immediately() -> None:
    pane = MockPane([[F]])
    tui_ops.await_done(pane, timeout_s=5.0)


def test_D2_await_done_busy_then_idle() -> None:
    pane = MockPane([[f"{F}\n{B}"], [f"{F}\n{B}"], [F]])
    tui_ops.await_done(pane, timeout_s=5.0)


def test_D3_await_done_stays_busy_timeout() -> None:
    pane = MockPane([[f"{F}\n{B}"]])
    with pytest.raises(TimeoutError, match="agent work exceeded"):
        tui_ops.await_done(pane, timeout_s=0.05)


# --- tail_text ---


def test_tail_text_joins_and_strips_ansi() -> None:
    pane = MockPane([["\x1b[31mx\x1b[0m", F]])
    text = tui_ops.tail_text(pane, n_lines=10)  # type: ignore[arg-type]
    assert "\x1b" not in text
    assert F in text
