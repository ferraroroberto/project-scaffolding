# Static-analysis ratchet

`scripts/static_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It computes the current duplicated-code, unused-code and likely-bug/security findings, compares them with a committed baseline, and **fails only on a finding that is new**. Existing debt never blocks work; it cannot grow either.

Why a ratchet rather than a weekly audit: an audit re-finds the same duplication every run, and the fix lives in someone's head. A gate stage encodes the lesson in structure (the pstack principle "encode lessons in structure").

## What it checks

| Concern | Python | JS |
|---|---|---|
| Duplicate blocks | `jscpd` | `jscpd` (same run) |
| Unused imports / variables | `ruff check --select F401,F841` | not covered |
| Likely bugs and security patterns | curated ruff `B` / `S` codes (same ruff call) | not covered |

- **`jscpd` is pinned to an exact version** (`JSCPD_VERSION` in the script, currently `5.4.0`) and run through `npx --yes jscpd@<version>`. One tool covers both languages; a stdlib JS tokenizer (regex literals, template strings) would be a bug farm of its own. The cost is that **Node is a prerequisite for an adopter that opts in**. jscpd 5 ships its own `--baseline`; this script does not use it, so that duplicates and unused names share one baseline file, one key scheme and one set of modes.
- **ruff** is invoked as `python -m ruff` from the interpreter running the script, with `--select F401,F841` plus the repo's `ruff_rules` (default: the curated `B`/`S` set below), in one call. That replaces the rule *selection* only: the repo's own ruff config (excludes, `per-file-ignores`) and inline `# noqa` still apply. An adopter that has no ruff in its venv gets a **not confirmed** exit, not a pass.
- **No JS unused-code check.** eslint would be a second Node tool plus per-repo config. JS is covered for duplication only.

## Curated bug and security rules

`DEFAULT_RULES` in the script lists every enforced code with a one-line why. In short:

- **flake8-bugbear (`B`)**: `B002 B003 B004 B005 B006 B012 B015 B016 B017 B018 B020 B021 B022 B025 B026 B029 B030 B031 B032 B033 B034 B035 B039`, the bugbear codes that flag a construct which does not do what it reads as (a mutable default shared by every call, `return` in `finally` swallowing the exception, `pytest.raises(Exception)`, a set literal repeating `0` and `False`, `re.sub` flags passed positionally).
- **flake8-bandit (`S`)**: `S102 S103 S113 S201 S307 S506 S602 S604 S605 S701`: `exec`/`eval` of data, a world-writable `chmod`, an HTTP call without a timeout, Flask `debug=True`, an unsafe `yaml.load`, `shell=True` and `os.system`, Jinja2 with autoescape off.

The bar for a code: a new hit is something a reviewer fixes rather than argues with. Each candidate was measured over every fleet checkout with the repo's own ruff config and the ratchet's excludes, and a sample of its hits was read by hand.

**Not reported in test paths** (`**/tests/**`, `**/test_*.py`, `**/*_test.py`, `**/conftest.py`): `S102 S307 S602 S604 S605`. Running code or a shell command on fixture input is a test's job, not an injection path; every such hit in the fleet's tests was a harness doing exactly that. The bug codes still apply to tests (`B017` exists for them).

**Left out**, and why (non-test hits across the fleet in brackets):

| Code | Why it is not enforced |
|---|---|
| `S101` assert (66, plus tens of thousands in tests) | `assert` is pytest's idiom and a type-narrowing tool in app code |
| `S603`, `S607` subprocess call / partial executable path (350, 148) | fires on every subprocess call; the injection risk is `shell=True`, which `S602` covers |
| `B904` raise without `from` (369) | traceback-chaining style, not a defect |
| `S110`, `S112` `try`-`except`-`pass`/`continue` (230, 43) | the sampled hits were deliberate best-effort cleanup |
| `S608` SQL built from strings (151) | the sampled hits interpolate column lists or `?` placeholders with the values bound |
| `S311` non-crypto `random` (133) | games, jitter and sampling, not secrets |
| `B905` `zip` without `strict=` (112) | style; adding `strict=True` changes behaviour |
| `S310` `urlopen` with a variable URL (74) | fires on every urllib call |
| `S104` binding all interfaces (54) | LAN-served apps bind `0.0.0.0` on purpose |
| `B023` loop variable captured by a closure (41) | every sampled closure was called inside the same iteration |
| `B007` unused loop variable (38) | style |
| `S105`, `S106`, `S107` hardcoded password (21, 15, 0) | fires on names containing "token" or "password": CLI flags, status constants |
| `S324` MD5/SHA-1 (19) | the sampled hits were content fingerprints; ruff cannot tell a fingerprint from a credential hash |
| `S501`, `S323`, `S507` TLS or host-key verification off (8, 4, 1) | the fleet's self-signed local certificates and LAN hosts are trusted on purpose |
| `B008` call in a default argument (16) | FastAPI's `Depends()` / `Query()` is the idiom |
| `S202` archive `extractall` (5) | pinned release archives; Python 3.14's tar default is the `data` filter |
| `S314` XML parsing (6) | parses the repo's own or a trusted feed |

An adopter that wants a different set replaces it with `ruff_rules` (below); `ruff_rules = []` keeps only the unused-name check. A code ruff does not know makes ruff exit 2, which the stage reports as **not confirmed**, never as a pass.

**Measured over the fleet** with the curated set: 36 reported hits across 9 checkouts (`S113` 19, `B033` 8, `B034` 2, `B006` 2, `B017` 2, `S602` 1, `S102` 1, `S307` 1), all read by hand; 32 are real (16 requests without a timeout, 8 duplicated set items, the rest one each of the patterns above). The other 4 are deliberate: 3 `httpx` streaming clients with an explicit `timeout=None`, which `S113` also flags, and one snippet runner whose job is `exec`. The 5 hits the test-path rule drops were all test harnesses.

## The three outcomes of a run

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (no new finding), or the stage is **not enabled** | continues |
| `1` | A new finding, or the baseline file is missing | fails |
| `2` | Bad `[static_ratchet]` table, unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: a detector could not run (no `npx`, no network on the first `npx`, ruff missing, timeout, unparseable output) | fails |

Exit 3 is its own state and is never folded into a pass: a tool that did not run has established nothing, so it must not read as "no new findings". Re-run once the prerequisite is fixed.

A baselined finding that has **disappeared** passes, and the run prints `N baselined finding(s) are gone -- run --update-baseline`. Failing instead would force the baseline edit into the same PR; the trade accepted here is that a stale entry lets the identical block regrow silently until someone shrinks the baseline, so shrink it in the PR that removes the debt.

## Keys and the baseline file

Keys carry no line numbers, so inserting code above a baselined finding does not re-flag it.

- **Duplicate:** `dup:<12 hex of sha1 of the whitespace-normalised fragment>:<fileA>|<fileB>` (paths sorted). The key is **strict**: editing the cloned block reads as one hit gone plus one new, so the author either removes the duplication or re-baselines it with the explicit flag, visible in review. A tolerant key (file pair only) would let a clone grow unnoticed. jscpd reports a clone as an ordered pair and the fragment hashed is the first file's; that order is deterministic for an unchanged tree.
- **Unused:** `unused:<rule>:<file>:<symbol>`, the symbol being the backtick-quoted name in ruff's message (falling back to the stripped source line).
- **Bug / security:** `lint:<rule>:<file>:<stripped source line>`. The source line, not the message, because one message ("call without timeout") repeats for every hit; editing the flagged line reads as one hit gone plus one new, like an edited clone.
- **Repeats** of one key (the same name unused twice in a file, the same block cloned twice between two files) get a `#<n>` suffix counting up from 2, in source-line order.

The baseline is committed, sorted JSON, one entry per line so diffs review cleanly:

```json
{
  "version": 1,
  "tools": {"jscpd": "5.4.0", "ruff": "0.15.21"},
  "entries": [
    {"key": "dup:e1d7fd9755a8:a.js|b.js", "files": ["a.js", "b.js"]},
    {"key": "lint:S113:c.py:return requests.get(url).json()", "files": ["c.py"]},
    {"key": "unused:F401:b.py:os", "files": ["b.py"]}
  ]
}
```

`tools` records what produced the file and is informational only; it is rewritten whenever the baseline is. A ruff upgrade that changes what the selected codes report shows up as new or gone entries, and is handled like any other.

## Modes

```
python scripts/static_ratchet.py                                   # check (what the gate runs)
python scripts/static_ratchet.py --init                            # first baseline; refuses to overwrite
python scripts/static_ratchet.py --update-baseline                 # drop stale entries; exit 1 + write nothing if any finding is new
python scripts/static_ratchet.py --update-baseline --allow-additions   # the explicit flag that adds entries
```

Normal use can only shrink the baseline. Adding entries needs `--allow-additions` and shows in review as added lines in the baseline file.

## Adopting it (opt-in per repo)

Re-vendoring the script never breaks a repo that has not opted in: an absent `[static_ratchet]` table, or `enabled = false`, prints `static ratchet: not enabled` and exits 0 (declared, not inferred).

1. Vendor `scripts/static_ratchet.py` byte-for-byte (`/propagate-vendored static_ratchet`; manifest key `static_ratchet`), and declare it in the repo's `[vendored]` table.
2. Make sure `npx` (Node) and `ruff` (in the venv that runs the gate) are available; on CI, install both before the gate.
3. Add to the repo's own `.fleet.toml`:

   ```toml
   [static_ratchet]
   enabled    = true
   baseline   = ".static-ratchet-baseline.json"   # default
   min_lines  = 10                                  # default
   min_tokens = 100                                 # default
   exclude    = ["**/_vendored/**"]                 # added to the built-in set
   ruff_rules = ["B006", "S113"]                    # optional: replaces the curated B/S set; [] = none
   ```

   Always excluded: `node_modules`, `.venv`, `venv`, `.git`, `__pycache__`, `*.min.js`. `exclude` globs are anchored at the repo root; `**/` means "any depth". An adopter excludes `**/_vendored/**` because vendor-verbatim copies are duplicates by design and cannot be fixed downstream; the scaffold itself does not, since it owns them. `jscpd` also honours `.gitignore`.

   **Vendored files are left out automatically.** Every `dest` in the repo's own `[vendored]` table (a file or a folder) is excluded from both detectors on top of `exclude`, so the vendored ratchet scripts never report against each other or against the adopter's code and nothing about them is baselined. Vendored code is checked once, in this scaffold where it is owned; a future vendored component is covered the day it is declared. The scaffold has no `[vendored]` table, so its own copies stay in scope. A `[vendored]` entry without a `dest` excludes nothing.
4. Run `python scripts/static_ratchet.py --init` and commit the baseline.

   **An existing adopter re-vendoring the script** keeps its baseline: `dup:` and `unused:` keys are unchanged, and nothing in `.fleet.toml` has to change (an absent `ruff_rules` means the curated set). Its first check reports today's curated hits as new `lint:` findings, so run `python scripts/static_ratchet.py --update-baseline --allow-additions` once and commit the added `lint:` lines in the re-vendor PR; that diff is the review of the inherited debt. A repo that is not ready sets `ruff_rules = []` instead.
5. Add a gate stage that runs `python scripts/static_ratchet.py` and fails on any non-zero exit. The scaffold's `scripts/verify-before-ship.ps1` places it after `ruff` and before `mypy`; a Python acceptance runner calls the same script. **Do not path-route it**: duplication needs the whole tree.
6. If the repo uses diff-proportionate e2e routing, add a `tier = "none"` rule for the baseline file to `.fleet.toml` `[e2e]` (the file at the repo root otherwise fails safe to the full browser suite) and a matching assertion in `tests/test_classify_e2e.py`.

The script spawns `npx` and ruff with `CREATE_NO_WINDOW`, derived locally (it is vendor-verbatim, so it cannot import `src/no_window.py`).

## Cost and tuning

Measured with a warm `npx` cache on the dev box, using the defaults above and ruff with its own config disregarded:

| Tree | Python + JS files scanned | jscpd | ruff `F401,F841` |
|---|---|---|---|
| this scaffold | ~85 | ~1.4 s | well under 1 s |
| a ~660-file adopter | 663 | ~14 s | ~1.4 s |
| a ~350-file adopter | 351 | ~21 s | ~1.9 s |

The first `npx` call downloads jscpd once. Treat roughly **30 s** as the line at which to revisit scope (`exclude` globs, raising `min_tokens`) rather than accept it. At the defaults the scaffold has no duplicates, so its own baseline is empty and the ratchet is exercised by the test suite; the two adopters measured above carry real debt (25 and 4 duplicate pairs, 36 and 144 unused names, counted without their own ruff config and with `_vendored/` excluded), which is what their first `--init` will record.

`min_lines = 10` / `min_tokens = 100` are the starting defaults, to be tuned against real output. Lowering them finds many more, smaller clones (at 6 lines / 50 tokens the scaffold alone reports eight).

Adding the curated `B`/`S` codes to the same ruff call adds no measurable time: on the 17 adopters, repeated runs of the wider call stay within about 0.05 s of the unused-only one (ruff takes 0.1 to 0.2 s either way).

## Limits

- Exact clones only (jscpd's default). Renamed-identifier and near-miss clones are not detected.
- Python and JS only (`--format python,javascript`).
- No JS unused import/variable detection, and no JS bug/security rules.
- Needs Node; a machine without it gets exit 3 on the first run, by design.

## Tests

`tests/test_static_ratchet.py`: pure logic against captured jscpd/ruff JSON shapes (key stability when lines shift, new-versus-baselined, every mode), plus the acceptance criteria end to end on throwaway trees with the real jscpd and ruff. A missing prerequisite is a hard failure there, never `pytest.skip`.
