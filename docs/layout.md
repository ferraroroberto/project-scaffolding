# Layout

Where code goes in this repo. `scripts/structure_ratchet.py` enforces it (shape `streamlit`, declared in `.fleet.toml`, no extra roots); the rules themselves are in [repo-layout.md](repo-layout.md) and the mechanism in [structure-ratchet.md](structure-ratchet.md).

This repo is the scaffold: it is both a working Streamlit starter and the publisher of the vendor-verbatim components every fleet repo copies. A derived project keeps the folders it uses and deletes the rest.

## Top-level folders

- `app/` — the Streamlit shell. `app.py` is the entry point (page config, then navigation); `views/` holds one `render()` module per view and `styles/` the CSS overlays. Three folders beside them are vendored components that adopters carry at the same path: `tray/` (single-instance mutex and watchdog), `webapp/` (the HTTP/2 launch module and the `_vendored/` static channel with the nav, the usage log and the other shared UI components) and `site/` (the static-site starter).
- `src/` — non-UI logic: config, logging, runtime-data paths, the pooled HTTP client, the compression and login-lockout middleware, the usage log, and the example pipelines under `pipelines/` and notifier under `notify/`. No `streamlit` import, and nothing here imports `app` (the ratchet's layer check fails it).
- `scripts/` — operations CLIs: the vendored ratchets and their helpers, `classify_e2e.py`, `gen_verify_skill.py`, the certificate generators, the site tooling and `verify-before-ship.ps1`, the pre-ship gate. Never imported by `app/`.
- `tests/` — pytest suite mirroring what it tests (`ratchets/`, `site/`, `locations/`, `ci/`, `vendored/`), the soak harness under `soak/`, the Playwright regression suite under `e2e/` and the pages it serves under `fixtures/` and `e2e/fixtures/`.
- `docs/` — durable reference: the conventions, the ratchet references, the onboarding playbook and the architecture diagram.
- `brand/` — the fleet icon masters (`*.svg`) and `catalog.json`, which `scripts/brand_gen.py` turns into the generated icons.
- `data/` — runtime input, output and logs. Contents are gitignored; only the `.gitkeep` files are tracked.

## Root files

The root holds the instructions (`CLAUDE.md`, `AGENTS.md`, `README.md`), the project config (`.fleet.toml`, `pyproject.toml`, `pytest.ini`, `requirements.txt`, `.gitignore`, `LICENSE`), the `.*-ratchet-baseline.json` files, the four launchers (`launch_app.*`, `launch_server.*`) and `tray.bat.template`. Each is in the `streamlit` shape's list of root files; nothing else belongs at the root.

## Where new code goes

- A new view: `app/views/<name>.py` exposing `render()`, registered in `app/app.py`. Never `tab_x.py`, `x_tab.py` or a `main()`.
- New logic: `src/<domain>/`, once `src/` reaches 40 modules; flat until then. A pipeline job is `src/pipelines/<job>.py` with one `run()`.
- A new vendor-verbatim component: its source in the folder its adopters will carry it in, plus a line in the `[components]` table of `.fleet.toml` in the same change. UI components go under `app/webapp/static/_vendored/<component>/`.
- A new ops script: `scripts/`. A helper the app imports belongs in `src/`.
- Test data a test reads: `tests/fixtures/`. A new test mirrors the module it covers.

## Exceptions

None. `extra_roots` and `extra_root_files` are empty, and the structure baseline records no root file, folder type, placement or redundant entry. A new exception needs its reason in this file and in `.fleet.toml`.
