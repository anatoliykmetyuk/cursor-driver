# Workflow: identify breaking changes and write a migration guide

Use this playbook when the maintainers ask for a **migration note** after a batch of commits. It mirrors the process used for [`01-file-backed-prompts.md`](01-file-backed-prompts.md). Write for **downstream AI agents and SOP authors**: imperative steps, explicit scope rules, and copy-pasteable before/after snippets.

## 1. Lock the commit window

1. Record **since** and **until** commits exactly as the request specifies (e.g. *since and including* commit `abc123` through current `HEAD`).
2. If the request is ambiguous, default to: **until** = `HEAD`; **since** = parent of the first commit in the range, or the named “last good” ref — and state that interpretation in the migration doc.
3. For every commit in the window, collect **full hash**, **author date** (`git log --format=%ai`), and **subject**:

   ```bash
   git log --oneline <since>^..HEAD
   git log --format='%H %ai %s' <since>^..HEAD
   ```

## 2. Define “public API” before you read diffs

Consumer-facing surface is **not** “every importable symbol.” Decide scope up front so internal refactors do not get mis-labeled as breaking.

1. Read the package root export contract — for this repo, [`src/cursor_driver/__init__.py`](../src/cursor_driver/__init__.py) sets `__all__` to `["CursorAgent"]`. Treat **`CursorAgent` as the stable, user-facing API** for migration purposes.
2. Treat other modules under `src/cursor_driver/` (for example `tui_ops`) as **implementation details** unless the project explicitly documents them as stable. Changes there only belong in a migration guide if they **change observable behavior of the public type** (e.g. `send_prompt` semantics), not if they only adjust internal strings used by predicates that consumers never call directly.
3. If the project adds CLI entry points or re-exports later, extend this rule from `pyproject.toml` (`[project.scripts]`) and `__init__.py` in the same way.

## 3. Filter commits that matter for consumers

1. List commits that touch the installable package:

   ```bash
   git log --format='%H %s' <since>^..HEAD -- src/cursor_driver/
   ```

2. Classify the rest (docs-only, `.gitignore`, tests-only, skill/markdown layout) as **no public API impact** unless they change install layout or version pins.
3. For each relevant commit, skim the message; then rely on the **aggregated diff** for the package (next section), not on the message alone.

## 4. Diff the package and classify changes

1. Produce one diff for the consumer package tree:

   ```bash
   git diff <since>^..HEAD -- src/cursor_driver/
   ```

2. For each change, assign **exactly one** category:

   | Category | Meaning | Migration guide |
   | --- | --- | --- |
   | **BREAKING** | Callers must change code or flags to preserve behavior, or silent behavior change on the same call signature default | Numbered section; **before/after** code |
   | **BEHAVIORAL** | Observable side effects (paths on disk, cleanup timing, cwd) that may break scripts but not typical `CursorAgent` usage | Separate numbered section; glob/path rules |
   | **Out of scope** | Internal helpers, private attrs, non-exported modules with no effect on `CursorAgent` contract | Omit or one-line “internal only” |

3. Pay special attention to:

   - New keyword args **with defaults** that **flip runtime behavior** (same call, different effect — document as BREAKING for integrators).
   - File paths, `stop()` / lifecycle cleanup, and process/session cwd assumptions.

## 5. Write the migration document

1. Create `migration/NN-short-slug.md` — use zero-padded `NN` if this repo numbers guides (e.g. `01-...`).
2. Front-load **audience**, **public API scope** (link `__init__.py`), and a **commit range table** (since / until, full hashes, dates).
3. Add a **short table** of commits that touch `src/cursor_driver/` with hash, date, subject.
4. For each BREAKING or BEHAVIORAL item:

   - **What changed** (factual).
   - **Old vs new** behavior.
   - **Who is affected** (search terms: method names, path globs).
   - **Migration** — imperative rules and minimal code blocks integrators can paste.

5. End with a **verification checklist** (grep patterns, e.g. `send_prompt(`, `cursor-driver-prompt`, `stop()`).

## 6. Quality bar (agent-checkable)

- Prefer **full commit hashes** in the range table; short hashes are optional in secondary tables.
- **Do not** mark internal-only edits as breaking because another module changed.
- Every BREAKING item needs a **concrete** mitigation (flag name, path pattern, or call pattern).
- Link files by repo-relative path so tools and humans resolve them in one hop.

## 7. Optional: align with “skill-style” documentation

Skills use **progressive disclosure** (metadata → body → references). Migration notes are flatter, but borrow these ideas:

- Put **scope and commit bounds** first (metadata).
- Keep the body **procedure-oriented** for integrators (numbered sections, checklists).
- If a guide grows past ~200 lines, split rare edge cases into a second numbered guide rather than one long file.

---

**Summary:** define public API from `__init__.py` → filter git history → diff `src/cursor_driver/` → classify → write `migration/NN-*.md` with hashes, dates, and copy-paste migrations.
