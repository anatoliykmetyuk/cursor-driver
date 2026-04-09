# Project Boilerplate

File contents for the harness project scaffolding.  Use these templates
verbatim when creating the project directory (Step 2 of SKILL.md).

## `setup.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## `run.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -u src/<script>.py "$@"
```

## `requirements.txt`

Always include cursor-driver via absolute local path:

```
/Users/anatolii/Projects/cursor-driver
```

Add other dependencies (e.g. `tqdm`) as needed.

## `.gitignore`

```
.venv/
__pycache__/
out/
```

## `test.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/python -m pytest tests/ "$@"
```

Make `setup.sh`, `run.sh`, and `test.sh` executable.

---

## Prompt template example

A good prompt template has three sections: a **context table** mapping field
names to `{{PLACEHOLDER}}` values, a **task list** referencing those
placeholders, and **rules / constraints** bounding what the agent may do.

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
