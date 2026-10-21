# jobs-app feature map

One file per view. Seeded from the repo's committed inventories, never hand-written: the e2e suite's `surface()` names first, then `[[design.review.extra_steps]]`, then the `## UX surface` key views in `CLAUDE.md`. Regenerate with project-scaffolding's `scripts/gen_verify_skill.py`; add traps to a view's `## Gotchas`, the only hand-written part.

<!-- gen:begin index -->
| Feature | Sub-features | Driving nodes | Seeded from |
| --- | --- | --- | --- |
| [about](about.md) | 1 | 0 | key views |
| [filters](filters.md) | 1 | 1 | surface() · extra_steps |
| [home](home.md) | 1 | 0 | key views |
| [jobs](jobs.md) | 3 | 3 | surface() |
| [settings](settings.md) | 1 | 1 | surface() · key views |

**Declared e2e surfaces** (`[[e2e.surface]]`: diff-routing groups, context only, not seeds):

- `jobs`: `tests/e2e/test_jobs.py`

**Not mapped** (a `surface()` call the generator cannot turn into a driving node):

- `tests/e2e/test_jobs.py::_open_hidden`: `jobs.hidden` is called outside a test function
- `tests/e2e/test_jobs.py::test_dynamic_name`: a `surface()` name that is not a string literal
<!-- gen:end index -->
