# Agent Guidelines

## Development Environment

All environment setup and task execution **must** go through the scripts in `scripts/`.
Do not install dependencies, run tests, or lint manually — the scripts handle virtual-environment
activation and the correct command sequence.

### Initial setup

```bash
scripts/setup-venv.sh
```

This creates `.venv`, installs the package in editable mode, and pulls in all dev dependencies.

### Linting & type-checking

```bash
scripts/lint.sh
```

Runs `ruff check`, `ruff format --check`, and `mypy` inside the virtual environment.

### Running tests

```bash
scripts/test.sh
```

By default this runs **only unit tests**. Integration tests are skipped unless you
explicitly opt in with the `-i` (or `--integration`) flag:

```bash
scripts/test.sh -i
```

Integration tests require a live Cursor agent and tmux session; they are gated behind
the `CURSOR_DRIVER_INTEGRATION=1` environment variable that the flag sets automatically.

You can pass extra pytest arguments after the flag:

```bash
scripts/test.sh -i -k test_prompt_and_exit
```
