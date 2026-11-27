# Probe fake ratchet

`scripts/probe_fake_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It holds the rule that a process, port or listener probe is pinned on every supported platform by a fake: each probe module the repo declares has a test that feeds it each platform's probe output through a seam, and a change to a probe module ships with a change to such a test.

## Why

Every lane gates on Windows only. Code that reads processes, ports or listeners behaves differently on macOS, so a probe change that passes every Windows gate can reach `main` and turn the [Mac nightly](mac-runner.md) red a night later, one repo at a time. A fake per platform (a recorded or hand-built probe result, injected through a parameter, a monkeypatched function or a stub command runner) catches the macOS shape in the Windows gate, with no Mac.

The fakes must cover the macOS differences that have reached `main` before:

- **The image path moves after launch.** A framework Python on macOS re-executes itself, so a process started as `.venv/bin/python` reports `.../Python.framework/.../Resources/Python.app/Contents/MacOS/Python`. A probe that matches a process by its image path must accept both.
- **A listener scan can be refused or partial.** `lsof` without privileges skips other users' processes and can exit non-zero while still printing rows; a probe must tell "nothing listening" from "could not see".
- **Listeners on another address.** macOS reports `*:8000`, `[::1]:8000` and `127.0.0.1.8000` (a dot before the port in `netstat`) where Windows prints `0.0.0.0:8000`; a probe that counts holders of a port must parse each shape and decide which addresses count.
- **Other output columns.** `ps` and `lsof` column sets differ from `tasklist` and `netstat -ano`; pin each platform's real output as recorded text.

A test that only runs the probe for real covers the platform it runs on, which is Windows in the gate. A `skipif(sys.platform == "darwin")` is the opposite of a fake.

## The rules

### `probe-fake-missing`

A declared probe module has no test module that reaches it and fakes one of the declared platforms. One hit per module and platform, so a module with a Windows fake and no macOS fake is one `darwin` hit. Existing gaps sit in the baseline and only shrink.

A test module **reaches** a probe when it imports it (`import src.resource_probe`, `from src import resource_probe`, `from src.resource_probe import sample_process`; a `src/` layout module is also reached by its name under `src/`), or names it in a string (`monkeypatch.setattr("src.resource_probe.sample_process", ...)`, a load by path `"src/resource_probe.py"`).

It **fakes a platform** when the platform's words appear in its identifiers or string data: a test, fixture, class, variable or argument name, or a string constant. The words, compared as whole word tokens (`window` and `machine` never count):

| Platform | Words |
|---|---|
| `win32` | `win32`, `win64`, `win`, `windows`, `nt` |
| `darwin` | `darwin`, `macos`, `mac`, `osx` |
| `linux` | `linux` |

So `DARWIN_LSOF = """..."""`, `def test_holders_macos(...)`, `monkeypatch.setattr(sys, "platform", "darwin")` and `@pytest.mark.parametrize("platform", ["win32", "darwin"])` each count. Docstrings, comments and the strings inside a `skip`, `skipif`, `xfail` or `importorskip` call do not.

### `probe-changed-no-fake`

The branch's diff against the merge base with `base_ref` (committed, staged, unstaged and untracked files) changes a probe module but no test module that reaches it. A diff hit belongs to one change, so it is never written to the baseline and `--allow-additions` cannot record it: the change ships its fake, or carries the exemption below.

### `bare-exempt`

A `probe-fake-exempt` marker with no reason. It exempts nothing and is itself a hit.

### Exempting a probe

`probe-fake-exempt: <reason>` anywhere in a probe module exempts it from `probe-fake-missing` (a probe that reads the same thing the same way on every OS). The same marker among the lines a diff adds to the module exempts that diff from `probe-changed-no-fake` (a rename, a log line); it does not exempt the next change. Every exemption is printed on every run.

## The Mac nightly is unverified

Whenever the diff touches a declared probe module, the stage prints one line, pass or fail:

```
MAC_NIGHTLY: unverified (this diff changes probe module(s) src/ports.py; per-platform fakes stand in until the next Mac nightly is green)
```

The finish report carries that state for the Mac nightly as **unverified**, never folded into the gate's pass: the fakes stand in for the Mac, they do not prove it. The next green night on that repo's `main` settles it.

## Scope

Probe modules are the tracked and untracked-but-not-ignored `.py` files matching a `probes` glob. Test modules are files named `test_*.py` or `*_test.py` matching a `test_paths` glob (default `tests/**`).

## What is not checked

- **That the fake is right.** The ratchet sees that a test reaches the probe and names a platform; whether the recorded output is the real macOS shape is review's call, and the Mac nightly's.
- **Probes the repo does not declare.** Which modules probe processes, ports or listeners is declared in `probes`, never guessed.
- **A diff on `main` itself.** On `main` the merge base is `HEAD`, so the diff is empty and only `probe-fake-missing` runs.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | pass, or the table is absent or `enabled = false` |
| 1 | a hit beyond the baseline, a diff hit, the baseline is missing, or `--update-baseline` met an addition without `--allow-additions` |
| 2 | bad configuration (unknown key, no `probes`, unknown platform), a malformed baseline, `--init` over an existing baseline |
| 3 | **not confirmed**: `git` could not list the tree or find the merge base with `base_ref` (fetch it, or set `base_ref`), or a file cannot be read or does not parse; the gate fails on it |

## The baseline file

`.ratchets/probe-fake.json` (or `baseline`): a version and the sorted `probe-fake-missing` and `bare-exempt` hits, one per line. It only shrinks on its own: a gone hit prints a hint to run `--update-baseline`.

## Modes

- `python scripts/probe_fake_ratchet.py`: check against the baseline and the branch's diff.
- `--init`: write the first baseline; never overwrites. The diff is not read.
- `--update-baseline`: drop gone hits; refuses additions.
- `--update-baseline --allow-additions`: also record new `probe-fake-missing` hits, which shows in review as added lines.

## Adopting it (opt-in per repo)

Adopt it in any repo the Mac nightly tests whose code probes processes, ports or listeners:

```toml
[probe_fake_ratchet]
enabled    = true
baseline   = ".ratchets/probe-fake.json"        # default
probes     = ["src/ports.py", "src/proc/*.py"]  # globs; required
platforms  = ["win32", "darwin"]                # default; sys.platform values
test_paths = ["tests/**"]                       # default
base_ref   = "origin/main"                      # default
```

Then `scripts/tools/adopt_ratchets.py <target> --ratchets probe_fake` copies the script, records it under `[vendored]` and writes the first baseline, or do the same by hand ([adopting-ratchets.md](adopting-ratchets.md)). The scaffold enables it for itself and declares its own probes: the installer's listener check, the resource sampler, the self-restart and the tests' port probe.

## Tests

`tests/ratchets/probe_fake/test_probe_fake_ratchet.py`: the reference case (a probe change with no fake change is red, then green once the fake moves with it), one hit per missing platform, a platform named only in a skip or a docstring, reaching a probe through a string, both exemptions and a bare marker, an untracked new probe, every mode with the diff hit never baselined, the not-confirmed exits, bad configuration, and this repo's own baseline.
