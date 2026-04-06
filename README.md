# cursor-driver

Python library that runs the Cursor `agent` CLI in tmux and exposes a small API to start the session, send prompts, and observe or wait on agent lifecycle. The public surface is **`CursorAgent`** in [`src/cursor_driver/agent.py`](src/cursor_driver/agent.py).

**Requirements:** Python 3.10+, tmux, `agent` on `PATH`, and the `libtmux` dependency (see [`pyproject.toml`](pyproject.toml)).

## Getting started

Run `./scripts/setup-venv.sh` from the repo root (venv + editable install), then:

```python
from pathlib import Path
from cursor_driver import CursorAgent

repo = Path("/path/to/your/repo")
driver = CursorAgent(repo, model="your-model-id")

# One-shot: start agent, run prompt, tear down session when finished (default).
if driver.start(prompt="Do one task and summarize.") != 0:
    raise SystemExit(1)

# Or: keep the session and drive it with send_prompt + waiters.
driver = CursorAgent(repo, model="your-model-id", kill_session=False)
if driver.start() != 0:
    raise SystemExit(1)
driver.send_prompt("First instruction.")
driver.await_done()
driver.send_prompt("Second instruction.")
driver.await_done()
```

## API

The package exports a single public class. Import: `from cursor_driver import CursorAgent` (same class: `cursor_driver.agent.CursorAgent`).

### `class CursorAgent`

| Member | Signature | Role |
|--------|------------|------|
| *(constructor)* | `CursorAgent(workspace, model, *, tmux_socket=…, label=…, quiet=…, kill_session=…)` | `workspace` is a `Path`; `model` is the `--model` id; optional tmux socket name, session label, stdout noise, and whether `start()` tears down the session on exit. |
| `start` | `start(prompt=None) -> int` | Launch `agent` in tmux and set `pane`. No prompt: return when the session exists. String prompt: run to completion. Returns `0`, `127` (no `agent`), or `1`. |
| `send_prompt` | `send_prompt(text, *, timeout_s=...)` | After `start()`, wait for input readiness, send `text` and Enter, then wait until busy. |
| `is_trust_prompt` | `is_trust_prompt() -> bool` | Snapshot: trust dialog visible. |
| `is_ready` | `is_ready() -> bool` | Snapshot: idle, waiting for input. |
| `is_busy` | `is_busy() -> bool` | Snapshot: working. |
| `await_ready` | `await_ready(*, timeout_s=...)` | Block until ready for input. |
| `await_busy` | `await_busy(*, timeout_s=...)` | Block until busy. |
| `await_done` | `await_done(*, timeout_s=...)` | Block until current work finishes. |
| `pane` | attribute | `libtmux.Pane` or `None` after `start()`. |

**Attributes** (set at construction): `workspace`, `model`, `tmux_socket`, `label`, `quiet`, `kill_session`.

## Tests

```bash
./scripts/test.sh
```

Integration (live agent + tmux): `./scripts/test.sh --integration`
