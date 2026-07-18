# `src/doc_capture/` — deterministic, fail-safe app screenshots + README regen

Canonical **vendor-verbatim** component (project-scaffolding#171; pilot proven and merged in ferraroroberto/content-management#110, PR #162). Manifest-driven Playwright screenshots of a *running* app, plus a README "tour" section regenerated between markers. The companion LLM half — the `/docs-shots` skill that decides *when* to capture (diff ∩ `source_globs` → propose-then-capture) — lives in ferraroroberto/fleet-config#93 and invokes this engine; the skill activates only when `docs/screenshots/manifest.json` exists in a repo.

## Invariants (the part worth canonicalizing)

- **Manifest is the contract.** `docs/screenshots/manifest.json` declares every capturable feature; the engine never invents targets.
- **Fail-safe masking.** An entry without `mask` selectors is refused, loudly — never captured raw, even with `--force`. Enforced in `plan_features`; `capture_features` only acts on planned items, so nothing downstream can bypass the gate.
- **Idempotency by input hash.** sha256 over the files matched by `source_globs` + the entry's capture config (`reach`/`mask`/`wait`). PNG bytes are never hashed (they drift run-to-run).
- **Stable filenames.** `docs/screenshots/<feature>-desktop.png`; timestamps live in manifest metadata only, so git diffs stay clean.
- **Clean, non-persistent, non-stealth browser.** `launch.py` launches real Chrome (`channel="chrome"`) with determinism flags (`srgb`, hidden scrollbars, pinned locale/timezone/scale, forced light + reduced motion) and a settle CSS that kills animations/carets. This is deliberately *not* the stealth scraping profile — doc capture drives your own localhost app — so the kwargs ship self-contained inside the component (reasoning: content-management#110). A project with its own `chrome_launch.py` may re-export them.

## Files

| File | What |
| --- | --- |
| `engine.py` | App-shape-agnostic core: manifest load/save, input hashing, `plan_features`, capture loop, README generator. |
| `adapters.py` | Reach adapters — the app-shape-specific page choreography. Ships `streamlit` (pilot-proven) and `url` (FastAPI + static PWA). |
| `launch.py` | The non-stealth doc-capture browser launch/context kwargs + settle CSS. |
| `__main__.py` | CLI: `capture [--only NAME] [--force] [--headed] [--base-url URL]` · `readme` · `all`. |

## Manifest contract — `docs/screenshots/manifest.json`

```json
{
  "app": {
    "kind": "streamlit",
    "base_url": "http://localhost:8501",
    "start_hint": "launch_app.bat"
  },
  "features": {
    "reporting": {
      "title": "📊 Reporting",
      "description": "One paragraph for the README tour block.",
      "source_globs": ["app/app.py", "app/tab_reporting.py"],
      "reach": { "label": "reporting", "click": false },
      "wait": { "text": "daily numbers" },
      "mask": ["[data-testid=\"stCode\"]"],
      "input_hash": null,
      "captured_at": null,
      "files": []
    }
  }
}
```

**`app` block** — `kind`: which reach adapter drives the page, `streamlit` (default when omitted — pre-`kind` manifests keep working) or `url`; `base_url`: where the running app answers (overridable per run with `--base-url`); `start_hint`: shown in the unreachable-app error.

**Per feature (author-maintained):**

| Field | Meaning |
| --- | --- |
| `title` / `description` | Feed the README tour block only (not the input hash). |
| `source_globs` | Repo-root-relative globs of the source files whose changes stale the shot — drives input-hash idempotency. |
| `reach` | How the adapter navigates to the feature (see per-kind fields below). Part of the input hash. |
| `wait` | Readiness signal before the shot: `selector` (CSS) and/or `text` (visible text). Part of the input hash. |
| `mask` | **Required.** CSS selectors painted neutral-gray before the shot. An entry without it is refused, never captured raw. Part of the input hash. |

**Per feature (engine-maintained — never hand-edit):** `input_hash`, `captured_at`, `files`.

**`reach` fields per kind** — `streamlit`: `label` (segmented-control section button text; omit for single-view apps), `click` (default `true`; set `false` for the app's default section — clicking an already-selected option would deselect it), `expand` (expander labels to open before the shot: content hidden in a collapsed expander keeps DOM boxes, so its masks would paint over unrelated visible UI). The adapter also collapses the sidebar — verified by *visibility at shot time* (`aria-expanded` can lie mid-hydration) — and masks the whole sidebar when it stays visible. `url`: `path` (route appended to `base_url`, default `/`).

## README tour section

Add the two markers once, where the screenshots belong:

```markdown
<!-- docs-shots:start -->
<!-- docs-shots:end -->
```

`python -m src.doc_capture readme` rewrites the block between them from the manifest (deterministic; features never captured are omitted so no broken image links; rerun is a no-op).

## Adopting in another repo

1. Copy this whole package **byte-for-byte** (relative imports keep it location-independent) to a path exactly **two directories below the repo root** — `REPO_ROOT` is resolved as `parents[2]`.
2. Write `docs/screenshots/manifest.json` per the contract above and add the two README markers.
3. Record the adoption in your `.fleet.toml` (schema: fleet-config `architecture/README.md`; written/bumped by `/propagate-vendored doc_capture`, not by hand):

```toml
[vendored]
doc_capture = { src = "src/doc_capture", sha = "<scaffold commit>", dest = "src/doc_capture" }
```

**First adopter:** `content-management` (the pilot, at `dest = "config/doc_capture"`) — its `[vendored].doc_capture` entry is written by the first `/propagate-vendored doc_capture` wave, which re-vendors this canonical shape over the pilot copy.

Dependencies: Playwright (+ real Chrome) at capture time only — planning, hashing, and README regen are stdlib and run browserless.
