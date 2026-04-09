# Migration guide: CursorAgent file-backed prompts and session cwd (01)

This document is written for downstream **AI agents and SOP authors** who orchestrate `cursor_driver` from another repository. Follow it mechanically when upgrading a dependency pin.

## Public API surface

**Supported consumer API:** `CursorAgent` imported from `cursor_driver` (see [`src/cursor_driver/__init__.py`](../src/cursor_driver/__init__.py)).

Do **not** treat `cursor_driver.tui_ops` as stable API; this guide does not document internal TUI string changes.

## Commit and date range

| Field | Value |
| --- | --- |
| **Since (exclusive baseline)** | `eef1ce4b5b7da098205d5b61b5fac70db9c2ab9d` — *2026-04-07 15:48:29 +0900* — `Add testing to the skill` |
| **Until (inclusive)** | `7bed6205e976b7e9f506a59b5b874e77b74c014a` — *2026-04-09 17:09:11 +0900* — `refactor(harness-skill): split SKILL.md into progressive disclosure references` |

**Interpretation:** Update your integration if it assumed behavior from a checkout **at or before** the baseline hash above. The **until** hash is the last commit included in this migration note (current `HEAD` when the guide was written).

### Commits that changed `CursorAgent` / installable package behavior

These are the commits in the range that touch [`src/cursor_driver/`](../src/cursor_driver/):

| Short hash | Date (author) | Subject |
| --- | --- | --- |
| `389138b0` | 2026-04-09 14:15:03 +0900 | feat(agent): file-backed send_prompt; align TUI waiters with agent UI |
| `acbb4bf` | 2026-04-09 14:45:37 +0900 | Create prompts under .cursor/prompts |
| `9b10a19` | 2026-04-09 15:11:01 +0900 | Set workspace explicitly, test that no source activate is leaked |

Other commits in the window are documentation, CI/skill layout, `.gitignore`, or tests without changing the documented `CursorAgent` contract below.

---

## 1. BREAKING: `send_prompt` default is file-backed

### What changed

`CursorAgent.send_prompt` gained keyword-only argument `prompt_as_file: bool = True`. When `True` (the default), the method writes `text` to a temporary `.md` file under `<workspace>/.cursor/prompts/`, tracks that path, and types a **short** line into the TUI: `Read and follow the instructions in <absolute-path>`.

Previously, `send_prompt(text, *, timeout_s=...)` sent `text` **verbatim** via tmux `send_keys` (no intermediate file).

### Who is affected

Any caller that relied on the TUI receiving the **full** string passed to `send_prompt` is affected, **unless** they use the new escape hatch.

### Migration

**Rule:** If you need the old “type the whole string into the TUI” behavior, pass `prompt_as_file=False` on every `send_prompt` call that depended on it.

```python
# BEFORE (implicit old behavior: literal text to TUI)
agent.send_prompt("Do a small thing", timeout_s=600.0)

# AFTER (preserve old behavior)
agent.send_prompt("Do a small thing", timeout_s=600.0, prompt_as_file=False)
```

**Rule:** If you intentionally want file-backed delivery (large prompts, same pattern as `start(prompt=...)`), keep the default or pass `prompt_as_file=True` explicitly.

```python
agent.send_prompt(large_markdown_document, timeout_s=600.0)  # OK: default True
```

**Do not** manually wrap your user text in `Read and follow the instructions in ...` and then call `send_prompt` without `prompt_as_file=False` expecting only one hop — with the default `True`, that would create a **second** indirection. Prefer either:

- `send_prompt(user_text)` with default file-backing, **or**
- `send_prompt(f"Read and follow the instructions in {path}", prompt_as_file=False)` only if you already created the file yourself.

---

## 2. BEHAVIORAL: Temp prompt files live under `.cursor/prompts`

### What changed

Temporary prompt files created by `CursorAgent` use `tempfile.mkstemp(..., dir=<staging>)` where `<staging>` is **`<workspace>/.cursor/prompts`**, which is created with `mkdir(parents=True, exist_ok=True)`.

Previously, temp files for `start(prompt=...)` were created directly under `<workspace>/` (same filename prefix pattern `cursor-driver-prompt-*`).

### Who is affected

Automation that **globbed or watched** `<workspace>/cursor-driver-prompt-*.md` at the repo root.

### Migration

**Rule:** Change glob / watch paths to:

```text
<workspace>/.cursor/prompts/cursor-driver-prompt-*.md
```

---

## 3. BEHAVIORAL: `stop()` deletes tracked temp prompt files

### What changed

`CursorAgent.stop()` kills the tmux session as before, then removes **tracked** temp prompt file paths created by this instance (the same files appended when using file-backed `send_prompt` or `start(prompt=...)`) and clears `pane`.

Previously, `stop()` did not remove those files (except that `start` with a prompt still removed its own file in `finally` after the one-shot flow).

### Who is affected

Debugging or post-mortem scripts that expected prompt `.md` files to remain on disk **after** `stop()`.

### Migration

**Rule:** Copy any file you need for inspection **before** calling `stop()`.

```python
import shutil
from pathlib import Path

# Example: preserve last prompt file before teardown
# (adjust source path if you track it yourself)
shutil.copy2(src, Path("/tmp/prompt-retained.md"))
agent.stop()
```

---

## 4. BEHAVIORAL: tmux session initial working directory is `workspace`

### What changed

`CursorAgent.start` passes `start_directory=str(self.workspace)` when creating the tmux session (in addition to `agent --workspace {self.workspace}` in the command line).

Previously, the new session did not set tmux `start_directory`; the shell’s cwd could follow the **libtmux parent process** cwd rather than `workspace`.

### Who is affected

Rare: code that depended on the initial pane cwd **not** being `workspace` while still passing a different `workspace` argument.

### Migration

**Rule:** Pass the directory you want the session rooted in as `workspace` to `CursorAgent(..., workspace=Path(...))`. No change needed for normal usage.

---

## Quick reference

| Topic | Severity | One-line fix |
| --- | --- | --- |
| Literal `send_prompt` text to TUI | **BREAKING** | Add `prompt_as_file=False` |
| Glob for temp prompts | Behavioral | Use `.cursor/prompts/cursor-driver-prompt-*.md` |
| Files after `stop()` | Behavioral | Copy before `stop()` |
| tmux cwd vs `workspace` | Behavioral | Use `workspace=` as source of truth |

## Verification checklist (for agent executors)

1. Search the consumer repo for `send_prompt(` — add `prompt_as_file=False` wherever the TUI must receive the raw string.
2. Search for `cursor-driver-prompt` or `mkstemp` call sites that assume workspace root — point at `.cursor/prompts/`.
3. Search for `stop()` paired with file inspection — reorder to copy or read files first.
