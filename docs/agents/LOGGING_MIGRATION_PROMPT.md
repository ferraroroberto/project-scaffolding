# LOGGING_MIGRATION_PROMPT.md

Standalone prompt for migrating `print()` → `logging` across a Python repository or monorepo. Run this as its own plan-mode task — it is not part of the AGENTS/CLAUDE rollout.

```
You are migrating `print()` calls to the `logging` module across this repository.

Scope:
- Only Python files outside `.venv/`, `old/`, `node_modules/`, and any `tests/` directories that intentionally use print for assertions.
- Skip standalone scripts whose entire purpose is shell-style stdout (e.g. CLI filters that pipe). Confirm any such file with the user before skipping.

Approach (plan mode — present, get approval, then execute in phases of ≤5 files):
1. Inventory: report file count and line count of `print(` per top-level subfolder.
2. Per file: pick the right logger name (module path or domain), add `import logging` + `log = logging.getLogger(__name__)` if not already present.
3. Map calls:
   - `print(x)` → `log.info("%s", x)` (default)
   - `print(f"...")` → keep f-string but switch to `log.info(...)`; prefer lazy `%` formatting for hot paths.
   - `print("ERROR ...")` / printed tracebacks → `log.error(..., exc_info=True)`
   - `print("WARN ...")` / `print("⚠️ ...")` → `log.warning(...)`
   - Debug/trace prints → `log.debug(...)`
4. For Streamlit apps, prefer the project's existing logger setup if there is one (see project-scaffolding/src/logger.py for the canonical 3-sink pattern: terminal + file + Streamlit live panel).
5. Ensure root logging is configured exactly once per entrypoint (don't add `logging.basicConfig` to library modules).
6. Verify per phase: `& .\.venv\Scripts\python.exe -m py_compile <changed files>`; for Streamlit changes, boot-test once.

Out of scope:
- Don't refactor surrounding code.
- Don't change log format strings beyond what's needed to convert the call.
- Don't introduce structured logging (JSON) unless asked.
```
