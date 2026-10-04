# Instructions for Codex

Before starting any task, read and follow `CLAUDE.md` in this directory as the
shared source of project instructions. Read and follow the files it references
with `@path` syntax as well, resolving paths relative to the referencing file.

Keep shared project rules in `CLAUDE.md` and its referenced files, not here.

## Codebase navigation

This project uses Code Context Engine (CCE) for code retrieval.

Use `context_search` first when exploring the codebase, locating implementations,
understanding architecture, or finding related code. Prefer it over broad
directory scans or reading many files speculatively.

Use:
- `context_search` to locate relevant code and patterns.
- `expand_chunk` when more source around a result is needed.
- `related_context` to inspect callers, imports, and related implementations.
- `session_recall` when a previous project decision or earlier work is actually
  relevant to the current task.

CCE is for navigation and context selection, not a substitute for inspecting
the actual implementation. Before modifying code, read the complete relevant
files or sections and understand affected callers and tests.

Use `rg`/text search when looking for an exact string, symbol, error message,
route, or other case where literal search is more appropriate than semantic
retrieval.

## Internationalization

hocX is multilingual (see `CLAUDE.md`, section "Internationalisierung / i18n"). Never write a new
user-visible UI string directly into a component — add a translation key for every registered
locale instead, and run `python3 scripts/check-i18n-completeness.py` and
`python3 scripts/check-i18n-hardcoded-text.py` before finishing any UI change.

## Working method

For non-trivial changes:

1. Use CCE to identify the relevant implementation, dependencies, and tests.
2. Read the concrete files that will be modified.
3. Make the smallest coherent change that solves the task.
4. Run the smallest relevant checks or tests first.
5. Expand to broader test suites or E2E only when the change or verification
   requires it.
6. Review the resulting diff for unrelated changes before finishing.

Do not repeatedly explore parts of the repository already understood during the
current task.

## Project memory

Use CCE memory selectively.

Record a decision only when it is likely to matter in future sessions, such as
an architectural choice, non-obvious constraint, or deliberate tradeoff.

Record a code area only when the information would materially help future work.

Do not record routine edits, obvious implementation details, temporary debugging
information, or information already documented in the repository.