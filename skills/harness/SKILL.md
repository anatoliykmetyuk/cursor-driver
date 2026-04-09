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
any code.

### Identify the working directory

While reading the SOP, figure out the **working directory** — the directory
where the harness should run and where agents should open their workspaces.
This is the single most important path decision in the harness because it
determines what files agents can see and edit.  Infer it from the data the
SOP operates on — pick the narrowest scope that covers every file the
procedure touches.

The working directory is **never** the harness project directory itself (where
`run.sh` and `src/` live), and **never** the directory from which `run.sh`
happens to be invoked.

Confirm the working directory with the user alongside the step classification.

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
    │   ├── <step-a>.md                # single-turn agentic step
    │   ├── <step-b>_prompt_0.md       # chunked step — first turn
    │   ├── <step-b>_prompt_1.md       # chunked step — second turn
    │   └── <step-b>_prompt_2.md       # chunked step — further turn (if needed)
    ├── tests/
    │   ├── conftest.py            # shared fixtures
    │   ├── test_helpers.py        # pure function tests
    │   ├── test_mechanical.py     # subprocess tests (mocked)
    │   ├── test_agents.py         # CursorAgent tests (mocked)
    │   └── test_pipeline.py       # full pipeline flow tests
    └── out/                       # (gitignored) agent output artifacts
```

Read [references/project-boilerplate.md](references/project-boilerplate.md)
for the exact file contents of `setup.sh`, `run.sh`, `test.sh`,
`requirements.txt`, and `.gitignore`.  Make the shell scripts executable.

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

Keep prompts focused on a single concern.  If the SOP has a final
aggregation / summary step, that is a separate prompt template with its own
placeholders.

See [references/project-boilerplate.md](references/project-boilerplate.md)
for a full prompt template example.

## Step 4 — Write the automation script

The script lives at `src/<name>.py`.  Read
[references/script-guide.md](references/script-guide.md) for detailed
patterns, code examples, and the cursor-driver API.

At a high level, the script must:

- **Resolve the working directory** first — from the SOP's data context,
  never defaulting to the harness project dir or `cwd`.  Expose `--workdir`
  as a CLI override.
- **Put configuration at the top** — agent model (env-overridable),
  parallelism, tmux socket name.
- **One function per SOP step** — mechanical steps contain Python logic
  directly; agentic steps load a prompt template, substitute placeholders,
  and drive a `CursorAgent`.
- **Chunk prompts** around long-running tasks — split at boundaries where
  output floods the context window, using `send_prompt()` for subsequent
  turns.
- **Parallel execution** — when the SOP loops over a collection, use
  `ThreadPoolExecutor` with a configurable worker count and a `tqdm`
  progress bar.
- **CLI** — `argparse` with `--workdir`, `--parallel`, `--max-items`,
  `--only-id`, `--no-progress`.
- **`main()`** reads like the SOP — a short sequence of calls to per-step
  functions.

## Step 5 — Write tests

Every harness should have a test suite that validates orchestration logic
without invoking real agents or external commands.  Follow the testing
strategy documented in [TESTING.md](TESTING.md) (in this skill directory).

In short:

1. Add `pytest` to `requirements.txt`.
2. Create `tests/` with one file per layer: helpers, file parsing, mechanical
   steps (mocked `subprocess.run`), agent wrappers (mocked `CursorAgent`),
   and pipeline flow (all mocked, every branch covered).
3. Make `test.sh` executable.
4. Run the suite and fix any failures before presenting work to the user.

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

- [ ] Working directory is resolved from the SOP's data context, never defaulting to the harness project dir or `cwd`.
- [ ] `--workdir` CLI flag exists for user override.
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
- [ ] Agentic steps that span long-running tasks are chunked into separate `_prompt_N` turns.
