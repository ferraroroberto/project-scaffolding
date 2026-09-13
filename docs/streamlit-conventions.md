# Streamlit conventions

Moved verbatim from `CLAUDE.md` (`#254`) so the always-on file stays under its size cap. `CLAUDE.md` keeps each section's heading, its *apply only if* gate and one-line rules, and points here for the full procedure, reasoning, snippets and decision records. Headings match `CLAUDE.md`'s, so a reference to a section by name resolves in either file. Two rules are enforced by a check rather than prose alone: the `st.set_page_config` rule and the no-`streamlit`-imports-outside-the-UI-directory boundary. `#254` had reworded them as guidance because nothing enforced them (prompt-drift R-27); `#256` added the checks and restored them as rules.

## Streamlit conventions
*Apply only if this project uses Streamlit.*

- Call `st.set_page_config(layout="wide", page_title="...")` first, before any other Streamlit call. Enforced by `tests/test_streamlit_conventions.py`: it parses the entry point (`app/app.py`) with `ast` and fails if any other module-level Streamlit call comes first. Calls inside function/class bodies and inside imported view modules are not checked.
- Use `width="stretch"`/`width="content"`. **Never** introduce new `use_container_width=True` (deprecated); migrate existing uses when touched.
- All mutable state in `st.session_state`; no module-level globals.
- `@st.cache_data` for DataFrames/files; `@st.cache_resource` for DB clients/models.
- Every widget needs a stable, explicit `key=`.
- UI code only in the UI directory (e.g. `app/`); data logic in the non-UI package (e.g. `src/`). `streamlit` is never imported outside the UI directory, not even lazily inside a function. Enforced by ruff `TID251` (flake8-tidy-imports banned-api in `pyproject.toml`, run by `scripts/verify-before-ship.ps1`); `"app/**"` is the only per-file ignore — never widen it to make non-UI code pass. Streamlit-only helpers go under `app/` (e.g. `app/log_panel.py`).
- User feedback via `st.error()`/`st.warning()`/`st.success()`, not `st.write()`.
- **App layout:** main file (e.g. `app.py`) handles only page config, shared state, sidebar, routing. Default to native multipage nav — `st.navigation` + `st.Page`, one view per file exposing `render()`. `st.tabs()` for sub-sections *within* a view; sidebar radio only when asked.
- **Ask before assuming:** `st.session_state` key names/scope; caching strategy (`@st.cache_data` TTL vs `@st.cache_resource`); widget `key=` names/input sources; page placement (new page vs section in existing).
- **Custom CSS/JS hooking Streamlit's internal DOM is fragile** — raw `data-testid` selectors undocumented, rename between versions; `position: sticky` inside `st.container(key=...)` breaks on Streamlit's per-element `stLayoutWrapper` divs. Fix: `docs/streamlit-css-hooking-gotchas.md`.
