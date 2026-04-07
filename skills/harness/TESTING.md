# Harness Testing Strategy

Every harness has the same layered architecture (pure helpers, I/O functions,
subprocess calls, agent wrappers, pipeline orchestrator), so the testing
approach is uniform.  Tests validate the full orchestration logic **without
invoking real agents or external commands**.

## Principles

1. **No real agents.**  `cursor_driver.CursorAgent` is always mocked.
2. **No real subprocess.**  `subprocess.run` is patched for any CLI / git
   calls the harness makes.
3. **Real filesystem via `tmp_path`.**  Data files, output directories, and
   any other artifacts the script reads or writes are created in pytest's
   temporary directory.
4. **One test file per layer.**  Keeps tests focused and fast to run in
   isolation (`./test.sh -k test_pipeline`).

## Test layers

A harness script naturally splits into testable layers.  The exact number of
layers depends on the SOP — some harnesses have more file-parsing logic,
others have more subprocess steps.  Identify the layers by reading the
script and grouping functions by the kind of I/O they perform.

Typical layers:

| Layer | Test file | What to mock | What to assert |
|-------|-----------|--------------|----------------|
| **Pure helpers** | `test_helpers.py` | Nothing | Return values of `apply_placeholders`, naming/formatting helpers, CLI arg parsing |
| **Data file I/O** | `test_data.py` (or one file per data format) | Nothing (use `tmp_path` files) | Functions that read, write, or validate SOP-specific data files (JSON configs, decision files, status outputs, etc.) — cover every valid variant and every validation error path |
| **Mechanical steps** | `test_mechanical.py` | `subprocess.run` | Correct command args passed to subprocess, return-code propagation, directory creation/removal side effects |
| **Agent wrappers** | `test_agents.py` | `CursorAgent` | Placeholder substitution in the prompt, correct workspace/label/model forwarded, return-code propagation |
| **Pipeline flow** | `test_pipeline.py` | All step functions + subprocess calls | Orchestration logic: success path, every error/early-exit branch, fallback logic, progress-bar ticking |

Not every harness will have all five layers.  If the script has no data-file
parsing (e.g. it only calls agents and reads their output), skip that layer.
If it has no subprocess calls, skip the mechanical layer.  The pure-helpers
and pipeline-flow layers are always present.

## Project layout

Add a `tests/` directory and a `test.sh` runner alongside `run.sh`:

```
<harness>/
  tests/
    conftest.py
    test_helpers.py
    test_data.py             # or split into test_<format>.py per data type
    test_mechanical.py
    test_agents.py
    test_pipeline.py
  test.sh                    # convenience runner
```

Add `pytest` to `requirements.txt`.

### `test.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -m pytest tests/ "$@"
```

Make it executable.  Supports forwarding pytest flags:
`./test.sh -v -k test_success_path`.

## Shared fixtures (`conftest.py`)

The conftest provides reusable building blocks so individual test files stay
short.  Adapt these to the SOP's data model:

| Fixture | Purpose |
|---------|---------|
| `sample_item` | A dict (or object) representing one work item the pipeline processes |
| `data_file(tmp_path)` | Writes the SOP's primary data file (JSON list, CSV, etc.) with 1–2 sample items, returns its `Path` |
| `prompt_templates(tmp_path)` | Creates stub `.md` files (one per agentic step) with `{{PLACEHOLDER}}` tokens under a `prompts/` dir |
| `harness_root(tmp_path)` | Builds the full directory tree the pipeline expects (output dirs, working dirs, data dirs) |
| `mock_agent_class` | Patches `CursorAgent` so `.start()` returns 0 and `.await_done()` is a no-op; yields the mock class for inspection |

**`sys.path` trick** — add the harness `src/` directory to `sys.path` at the
top of `conftest.py` so tests can `import <script>` directly:

```python
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
```

## Writing tests per layer

### Pure helpers (`test_helpers.py`)

No mocking.  Call the function, assert the return value.

```python
class TestApplyPlaceholders:
    def test_single(self):
        assert apply_placeholders("Hello {{NAME}}", {"NAME": "world"}) == "Hello world"

    def test_no_match(self):
        assert apply_placeholders("no placeholders", {"X": "y"}) == "no placeholders"
```

Cover: single/multiple placeholders, repeated placeholders, no-match,
empty mapping.  For naming/formatting helpers, test normalisation (case,
whitespace, special-character replacement).

### Data file I/O (`test_data.py`)

Write real files to `tmp_path`, call the parsing/writing function, assert
results or expected exceptions.

```python
def test_load_item_found(data_file):
    item = load_item(data_file, item_id=42)
    assert item["id"] == 42

def test_load_item_not_found(data_file):
    with pytest.raises(KeyError, match="no item with id 99"):
        load_item(data_file, item_id=99)

def test_invalid_format(tmp_path):
    p = tmp_path / "data.json"
    p.write_text('{"not": "a list"}')
    with pytest.raises(ValueError):
        load_item(p, item_id=1)
```

Cover every valid variant and every validation error path that the
parsing functions can raise.

### Mechanical steps (`test_mechanical.py`)

Patch `subprocess.run` to return a configurable `CompletedProcess`.  Assert
the correct command list was passed and that return codes propagate.

```python
@patch("<script>.subprocess.run")
def test_step_success(mock_run, sample_item, tmp_path):
    mock_run.return_value = CompletedProcess(args=[], returncode=0)
    result = run_step(sample_item, tmp_path, quiet=True)
    args = mock_run.call_args[0][0]
    assert args[0] == "git"  # or whatever CLI the step calls
```

Cover: success, failure (exception or non-zero return code), pre-existing
directory cleanup, external binary not found (`shutil.which` returns `None`).

### Agent wrappers (`test_agents.py`)

Use the `mock_agent_class` fixture.  Call the `step_*` function, capture the
`prompt=` keyword passed to `.start()`, and verify placeholders were replaced.

```python
def test_step_placeholders(mock_agent_class, sample_item, tmp_path):
    step_foo(sample_item, workspace=tmp_path, template="ID={{ITEM_ID}}", model="m", label="l")
    prompt = mock_agent_class.return_value.start.call_args[1]["prompt"]
    assert "ID=42" in prompt
```

Also verify the correct workspace, label, and model reach
`CursorAgent.__init__`.

### Pipeline flow (`test_pipeline.py`)

This is the most valuable layer — it tests the conditional orchestration
without running any real work.

**Fixture approach:** create a `@pytest.fixture` called `patched` that patches
*every* step function and mechanical call at once using
`unittest.mock.patch` as context managers.  Each mock has a sensible default
(returns 0, writes expected output files).  Individual tests override specific
mocks to trigger different branches.

**Scenarios to cover:**

Read the orchestrator function (`run_single_item`, `run_pipeline`, or
whatever the harness calls it) and identify every conditional branch.  For
each branch, write a test that forces that branch and asserts:

- Which downstream steps were (or were not) called.
- What the exit code is.
- What the manifest / output files contain.
- That the summary / cleanup step still runs on early exit.

Common scenario patterns (adapt names to the SOP):

| Scenario | What to override | Key assertions |
|----------|-----------------|----------------|
| Success path | Nothing (all defaults succeed) | All steps recorded in output, exit code 0 |
| Early error at step N | Step N returns non-zero | Steps N+1.. not called, summary/cleanup still runs |
| Decision file parse error | Step writes invalid data | Early exit, error recorded in manifest |
| Conditional path A vs B | Decision file contains different values | Correct branch of steps executed, other branch skipped |
| Fallback logic | Primary step fails, fallback condition met | Fallback function called, success if fallback succeeds |
| Progress bar | Pass a `MagicMock` bar | `bar.update` call args sum to the expected step count for every scenario |

**Helper class** — a `PipelineHarness(tmp_path)` that builds the directory
tree, writes data files and prompt stubs, and exposes a `.run(bar=...)`
method.  This keeps each test to 3–5 lines of setup + assert.

## Checklist

Before presenting the test suite to the user, verify:

- [ ] `pytest` is in `requirements.txt`.
- [ ] `test.sh` is executable and runs from the harness root.
- [ ] Every test file imports the harness script via the `sys.path` trick.
- [ ] No test invokes a real `CursorAgent` or real `subprocess.run`.
- [ ] Pipeline tests cover every early-exit branch in the orchestrator
      function.
- [ ] Progress-bar ticking sums to the expected step count in every
      scenario.
- [ ] All tests pass: `./test.sh -v`.
