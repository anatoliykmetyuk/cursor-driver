---
name: harness
description: >
  Turn a markdown SOP (Standard Operating Procedure) into a Python harness
  that automates mechanical steps via script and delegates agentic steps to
  Cursor agents via cursor-driver.  Use this skill whenever the user wants to
  automate an SOP, convert a procedure into a script, harness a workflow, or
  mentions turning a markdown procedure into code that orchestrates agents.
  Also use when the user says "harness", "automate this SOP", or asks to
  create a scripted agent pipeline from a document.
---

# Harness — SOP-to-Script Automation

You are converting a human-readable SOP (Standard Operating Procedure) written
in markdown into a self-contained Python project that **scripts** the
mechanical parts and **delegates** the judgment-heavy parts to Cursor agents
via `cursor-driver`.

## When to use this skill

- The user has (or points you at) a markdown file describing a multi-step
  procedure.
- Some steps are rote (clone repos, copy files, parse JSON) and some require
  reasoning or code inspection that an LLM agent should handle.
- The goal is a one-command `./run.sh` that executes the whole procedure.

## Step 1 — Understand the SOP

Read the SOP markdown.  For every numbered step, decide (with the user)
whether it is:

| Category | Examples | How it ends up |
|----------|----------|----------------|
| **Mechanical** | clone a repo, copy a file, parse JSON, filter a list, back up a file | Python code in the script |
| **Agentic** | inspect source code and decide something, write a summary, make a judgment call | A prompt template fed to `CursorAgent` |

Present your classification to the user and get confirmation before writing
any code.  The user knows which steps they trust a script to do and which
need an agent's judgment.

## Step 2 — Create the project directory

Create a **new directory** for the harness and move the SOP into it.  If the SOP file is
`some-dir/my-procedure.md`, create `some-dir/my-procedure/` and move
the SOP inside as `SOP.md`:

```
some-dir/
└── my-procedure/                  # new directory, named after the SOP
    ├── SOP.md                     # original SOP, moved here and renamed
    ├── setup.sh                   # create venv, install deps
    ├── run.sh                     # activate venv, run the script
    ├── test.sh                    # activate venv, run pytest
    ├── requirements.txt           # cursor-driver (absolute path) + any other deps
    ├── .gitignore
    ├── src/
    │   └── <script>.py            # the main automation script
    ├── prompts/
    │   ├── <step-a>.md            # prompt template for first agentic step
    │   └── <step-b>.md            # prompt template for second agentic step
    ├── tests/
    │   ├── conftest.py            # shared fixtures
    │   ├── test_helpers.py        # pure function tests
    │   ├── test_mechanical.py     # subprocess tests (mocked)
    │   ├── test_agents.py         # CursorAgent tests (mocked)
    │   └── test_pipeline.py       # full pipeline flow tests
    └── out/                       # (gitignored) agent output artifacts
```

### File contents

**`setup.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**`run.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -u src/<script>.py "$@"
```

**`requirements.txt`** — always include cursor-driver via absolute local path:

```
/Users/anatolii/Projects/cursor-driver
```

Add other dependencies (e.g. `tqdm`) as needed.

**`.gitignore`**

```
.venv/
__pycache__/
out/
```

Make `setup.sh` and `run.sh` executable.

## Step 3 — Write prompt templates

For each agentic step, create a markdown file under `prompts/`.  Prompt
templates use `{{PLACEHOLDER}}` syntax for variables the script fills in at
runtime.

A good prompt template has:

1. **Context table** — a markdown table mapping field names to `{{PLACEHOLDER}}`
   values so the agent knows exactly what it is working with.
2. **Task list** — numbered steps the agent must perform, referencing
   placeholders by name.
3. **Rules / constraints** — explicit boundaries on what the agent may and may
   not do (which files to edit, which fields to change, what constitutes a
   valid output).

Example:

```markdown
You are running the discovery workflow for **one** plugin.

## Context

| Field | Value |
|-------|-------|
| Plugin ID | {{PLUGIN_ID}} |
| Clone path | {{CLONE_DIR}} |
| Tracker file | {{TRACKER_PATH}} |

## Tasks

1. Read `{{CLONE_DIR}}/build.sbt`.
2. Decide porting status using the markers below.
3. Edit `{{TRACKER_PATH}}`: update Status for ID {{PLUGIN_ID}}.

## Rules

- Only change Status to "Already Ported" if markers confirm it.
  Otherwise leave the existing value untouched.
```

Keep prompts focused on a single concern.  If the SOP has a final
aggregation / summary step, that is a separate prompt template with its own
placeholders.

## Step 4 — Write the automation script

The script lives at `src/<name>.py`.  Structure it as follows.

### Configuration section

Put tunables at the top so they are easy to find and change:

```python
AGENT_MODEL = os.environ.get("<PREFIX>_AGENT_MODEL", "composer-2-fast")
PARALLEL = 5
TMUX_SOCKET = "<sop-name>"
```

- Model is overridable via environment variable, with a sensible default.
- Parallelism is a constant referenced by a `--parallel` CLI flag.
- Tmux socket name is unique to this SOP to isolate its sessions.

### Placeholder substitution

Use a simple string-replace helper — no template engine needed:

```python
def apply_placeholders(template: str, mapping: dict[str, str]) -> str:
    out = template
    for key, value in mapping.items():
        out = out.replace(f"{{{{{key}}}}}", value)
    return out
```

### One function per SOP step

Every step of the SOP gets its own function in the script — mechanical or
agentic.  When someone reads the script, they should be able to look at the
function list and immediately see the 1-to-1 mapping to the SOP steps.

For **mechanical** steps, the function contains the Python logic directly
(clone a repo, parse JSON, back up a file, etc.).

For **agentic** steps, the function:

1. Prepares the placeholder mapping from runtime data.
2. Calls `apply_placeholders` on the prompt template.
3. Creates a `CursorAgent`, calls `.start(prompt=...)`, then `.await_done()`.

```python
from cursor_driver import CursorAgent

def run_my_agent(entry, *, template, model, ...):
    prompt = apply_placeholders(template, {"KEY": value, ...})
    agent = CursorAgent(
        workspace, model,
        tmux_socket=TMUX_SOCKET, label=f"step-{entry_id}", quiet=quiet,
    )
    code = agent.start(prompt=prompt)
    if code == 0:
        agent.await_done()
    return code
```

Key points about the cursor-driver API:

- `CursorAgent(workspace, model, *, tmux_socket, label, quiet, kill_session)`
- `.start(prompt=None) -> int` — launches agent in tmux; if prompt is given,
  writes it to a temp file and sends the agent a short instruction to read it.
  Returns `0` on success.  Does **not** wait for the agent to finish.
- `.await_done(*, timeout_s=...)` — blocks until the agent finishes its
  current work.  Call this explicitly after a successful `start()`.
- `.send_prompt(text)` — for multi-turn flows: waits for ready, sends text,
  waits for busy.

### Parallel execution

When the SOP loops over a collection (e.g. "for each plugin"), use
`ThreadPoolExecutor` with the configurable parallelism.  Each agent gets a
unique label (e.g. `plugin-{id}`) so tmux sessions don't collide.  Use a
`threading.Lock` around shared mutable counters.

Display a `tqdm` progress bar on stderr to track completion.  Add `tqdm` to
`requirements.txt`.  Update the bar in the `as_completed` loop so the
operator sees how many items have finished out of the total.

### CLI

Expose useful flags via `argparse`: `--parallel`, `--max-items`,
`--only-id`, `--no-progress`.  Wire defaults to the configuration constants.

### Main function

`main()` should be short and read like the SOP itself — a sequence of calls
to the per-step functions.  Someone reading `main()` should immediately
recognize the SOP's procedure:

```python
def main() -> int:
    args = parse_args()
    # Step 1
    step_1_result = run_step_1(...)
    # Step 2
    step_2_result = run_step_2(...)
    # Step 3
    ...
```

## Step 5 — Write tests

Every harness should have a test suite that validates orchestration logic
without invoking real agents or external commands.  Follow the testing
strategy documented in [TESTING.md](TESTING.md) (in this skill directory).

In short:

1. Add `pytest` to `requirements.txt`.
2. Create `tests/` with one file per layer: helpers, file parsing, mechanical
   steps (mocked `subprocess.run`), agent wrappers (mocked `CursorAgent`),
   and pipeline flow (all mocked, every branch covered).
3. Create `test.sh` alongside `run.sh` — a convenience script that runs
   `pytest` inside the venv:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -m pytest tests/ "$@"
```

4. Make `test.sh` executable.
5. Run the suite and fix any failures before presenting work to the user.

See `TESTING.md` for the full testing strategy: layer definitions, fixture
patterns, mock setup, scenario tables, and the checklist.

## The SOP is the source of truth

Do **not** modify the body of `SOP.md`.  The only change allowed is adding a
short paragraph at the very top stating that this SOP is automated and should
be executed via `./run.sh`.  Everything else stays exactly as the user wrote
it.  The script is an implementation of the SOP, not a replacement — if the
SOP changes, the script should be updated to match, not the other way around.

## Checklist

Before you present the result to the user, verify:

- [ ] `SOP.md` is present and reflects the automated workflow.
- [ ] `setup.sh` and `run.sh` are executable.
- [ ] `requirements.txt` includes the absolute path to cursor-driver.
- [ ] Every agentic step has a prompt template in `prompts/`.
- [ ] Prompt templates use `{{PLACEHOLDER}}` syntax, no hardcoded paths.
- [ ] The script has a Configuration section at the top.
- [ ] Each agent has its own function (not inlined in main).
- [ ] `agent.await_done()` is called after every successful `agent.start()`.
- [ ] Parallel execution uses `ThreadPoolExecutor` with configurable workers.
- [ ] `out/` directory is gitignored and cleaned before the summary agent runs.
- [ ] The script compiles: `python -m py_compile src/<script>.py`.
- [ ] `pytest` is in `requirements.txt`.
- [ ] `test.sh` is executable and runs the suite via the venv.
- [ ] Tests cover every pipeline branch (see `TESTING.md` checklist).
- [ ] All tests pass: `./test.sh -v`.
