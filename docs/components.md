# The `[components]` catalog

`.fleet.toml`'s `[components]` table is the canonical `<manifest key> → <src path>` map of every vendor-verbatim component this scaffold publishes, read by `scripts/vendored_catalog.py`. Only this repo carries it — an adopter declares what it copied in its own `[vendored]` table instead; this one declares what the scaffold publishes, and only the scaffold publishes.

## Why it exists

`/propagate-vendored <component>` builds its adopter list from adopters' `[vendored]` entries. A repo that carries a component without declaring it is invisible to that wave: the fan-out re-vendors the declared repos, reports success, and leaves the undeclared carrier stale.

It is load-bearing in two more places:

- `fleet-config`'s `vendored_drift.py` hashes every fleet repo's copy of a catalogued path to name repos carrying an undeclared component.
- `scripts/verify-before-ship.ps1` derives its `mypy --strict` gate list from the same declaration, rather than keeping a second hand-maintained list, so a new Python component is type-gated the day it lands.

## Keeping it current

Add a component to the table in the same PR that adds it to the tree. `tests/test_vendored_catalog.py` is the anti-drift guard that fails otherwise.
