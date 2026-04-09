# Automation Script Guide

Patterns, code examples, and the cursor-driver API for writing the main
harness script (`src/<name>.py`).  Read this during Step 4 of SKILL.md.

## Working directory resolution

The script must resolve the working directory before doing anything else.
This is the directory agents open as their workspace and where the harness
runs its mechanical steps — it is the SOP's operating context, not the
harness project directory.

Choose the working directory based on the SOP's data:

| SOP pattern | Working directory |
|-------------|-------------------|
| Operates on a cloned git repo | The clone directory |
| Edits files inside a specific project | That project's root |
| Processes a data file or directory | The parent directory containing the data |
| No clear data anchor | A fresh temporary directory (`tempfile.mkdtemp`) |

The working directory is **never** the harness project directory itself (where
`run.sh` and `src/` live), and **never** the directory from which `run.sh`
happens to be invoked.

Expose it as a `--workdir` CLI flag so the user can always override it.  When
the flag is omitted, the script should resolve the directory automatically
based on what the SOP operates on.  If the SOP clones a repo, the clone
target *is* the working directory.  If the SOP processes files at a known
path, that path is the working directory.  When there is genuinely no anchor,
create a temporary directory and log its path so the user can find it:

```python
import tempfile

def resolve_workdir(cli_value: str | None, sop_default: str | None) -> Path:
    if cli_value:
        return Path(cli_value).resolve()
    if sop_default:
        return Path(sop_default).resolve()
    workdir = Path(tempfile.mkdtemp(prefix="harness-"))
    print(f"No working directory specified; using temp dir: {workdir}", file=sys.stderr)
    return workdir
```

Pass the resolved working directory to every step function and to
`CursorAgent(workspace=workdir, ...)`.  Never default `workspace` to the
harness project directory or to `Path.cwd()`.

## Configuration section

Put tunables at the top so they are easy to find and change:

```python
AGENT_MODEL = os.environ.get("<PREFIX>_AGENT_MODEL", "composer-2-fast")
PARALLEL = 5
TMUX_SOCKET = "<sop-name>"
```

- Model is overridable via environment variable, with a sensible default.
- Parallelism is a constant referenced by a `--parallel` CLI flag.
- Tmux socket name is unique to this SOP to isolate its sessions.

## Placeholder substitution

Use a simple string-replace helper — no template engine needed:

```python
def apply_placeholders(template: str, mapping: dict[str, str]) -> str:
    out = template
    for key, value in mapping.items():
        out = out.replace(f"{{{{{key}}}}}", value)
    return out
```

## One function per SOP step

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

## Chunking prompts around long-running tasks

Every long-running or token-heavy operation — compilation, a full test suite,
an iterative fix-and-retry loop, a large data migration — floods the agent's
context window with output.  Instructions that appeared earlier in the same
prompt get pushed out of the model's effective attention, and in practice the
agent "forgets" to follow them roughly a third of the time.

Split each boundary where this can happen into a separate prompt chunk.  The
first chunk runs via `agent.start(prompt=...)`, subsequent chunks via
`agent.send_prompt(...)`.  Each call writes a fresh prompt file under the
workspace, so the next batch of instructions lands at the top of the agent's
attention instead of buried under pages of build logs.

Name the prompt templates `<step>_prompt_0.md`, `<step>_prompt_1.md`, etc.
under `prompts/`.  Single-turn steps that don't need chunking keep their
plain `<step>.md` name.

Use `kill_session=False` on `CursorAgent` when you chain chunks in one session.

```python
templates = [
    prompts_dir / "deploy_prompt_0.md",   # e.g. build the project
    prompts_dir / "deploy_prompt_1.md",   # e.g. run the test suite
    prompts_dir / "deploy_prompt_2.md",   # e.g. analyse failures and fix
]

agent = CursorAgent(workspace, model, tmux_socket=TMUX_SOCKET, kill_session=False)
if agent.start(prompt=apply_placeholders(templates[0].read_text(), mapping)) != 0:
    return 1
agent.await_done()
for tmpl in templates[1:]:
    agent.send_prompt(apply_placeholders(tmpl.read_text(), mapping))
    agent.await_done()
agent.stop()
```

The rule of thumb: if an operation might produce hundreds of lines of output or
take long enough that the agent iterates many times, that is a chunk boundary.
Put the instructions that follow it into the next prompt file.

## cursor-driver API

- `CursorAgent(workspace, model, *, tmux_socket, label, quiet, kill_session)`
- `.start(prompt=None) -> int` — launches agent in tmux; if prompt is given,
  writes it to a temp file and sends the agent a short instruction to read it.
  Returns `0` on success.  Does **not** wait for the agent to finish.
- `.await_done(*, timeout_s=...)` — blocks until the agent finishes its
  current work.  Call this explicitly after a successful `start()`.
- `.send_prompt(text, ..., prompt_as_file=True)` — for multi-turn flows: waits
  for ready, sends the prompt (by default written to a temp file like `start`,
  with a short "read this file" instruction), waits for busy.  Use
  `prompt_as_file=False` to send *text* directly as keystrokes (short lines only).

## Parallel execution

When the SOP loops over a collection (e.g. "for each plugin"), use
`ThreadPoolExecutor` with the configurable parallelism.  Each agent gets a
unique label (e.g. `plugin-{id}`) so tmux sessions don't collide.  Use a
`threading.Lock` around shared mutable counters.

Display a `tqdm` progress bar on stderr to track completion.  Add `tqdm` to
`requirements.txt`.  Update the bar in the `as_completed` loop so the
operator sees how many items have finished out of the total.

## CLI

Expose useful flags via `argparse`: `--workdir`, `--parallel`, `--max-items`,
`--only-id`, `--no-progress`.  Wire defaults to the configuration constants.
`--workdir` overrides the working directory; when omitted, the script resolves
it automatically as described above.

## Main function

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
