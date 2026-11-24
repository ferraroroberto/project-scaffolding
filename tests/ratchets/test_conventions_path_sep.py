"""The `path-sep` rule: text a regex parsed joined onto a path without normalising its separator.

A `.bat` writes `scripts\\run.py`; Windows splits it at the backslash, POSIX reads it as one file
name, so a join that works on the gating machine breaks only on the Mac nightly. The rule fails
the join written that way and passes it once the separator is normalised.
"""

from __future__ import annotations

import pytest

from scripts import conventions_ratchet as cr

RULE = "path-sep"
CFG = cr.Config(cr.DEFAULT_BASELINE, (RULE,))

# The shape that broke the Mac nightly: a regex match, a prefix strip, then a join.
PRE_FIX = '''
def _wrapper_scripts(bat_path, text):
    root = bat_path.parent.resolve()
    scripts = []
    for match in _BAT_PY_PATH_RE.findall(text):
        rel = _BAT_DIR_PREFIX_RE.sub("", match)
        if not rel or "%" in rel:
            continue
        candidate = (root / rel).resolve()
        scripts.append(candidate)
    return scripts
'''
FIXED = PRE_FIX.replace('.sub("", match)', '.sub("", match).replace("\\\\", "/")')


def hits(src: str, path: str = "src/scanner.py") -> list[str]:
    return [f"{h.rule}:{h.line}" for h in cr.scan_source(src, path, cr.rules_for(path, CFG))]


def test_the_rule_is_known_and_opt_in() -> None:
    assert RULE in cr.RULES
    cfg = cr.parse_config(f'[conventions_ratchet]\nenabled = true\nrules = ["{RULE}"]\n')
    assert cfg is not None and cfg.rules == (RULE,)
    assert hits(PRE_FIX) and not cr.scan_source(PRE_FIX, "src/scanner.py", frozenset({"no-window"}))


def test_the_pre_fix_wrapper_scripts_shape_fails_and_the_fix_passes() -> None:
    assert hits(PRE_FIX) == [f"{RULE}:9"]
    assert '.replace("\\\\", "/")' in FIXED
    assert hits(FIXED) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("m.group(1)", id="group"),
        pytest.param("pat.search(line).group('path')", id="search-group"),
        pytest.param("re.findall(r'\\S+\\.py', text)[0]", id="findall-index"),
        pytest.param("'%s.py' % m.groupdict()['name']", id="groupdict-format"),
    ],
)
def test_each_text_source_fails_when_joined(source: str) -> None:
    src = f"def f(root, m, pat, line, text):\n    rel = {source}\n    return root / rel\n"
    assert hits(src) == [f"{RULE}:3"]


def test_a_whole_file_read_is_a_host_written_pointer_not_parsed_text() -> None:
    src = "def f(repo, dot_git):\n    first = dot_git.read_text().strip()\n    return repo / first[len('gitdir:'):]\n"
    assert hits(src) == []


def test_a_posixpath_join_of_a_url_path_passes() -> None:
    assert hits("def f(base, m):\n    return posixpath.join(base, m.group(1))\n") == []


@pytest.mark.parametrize(
    "join",
    [
        pytest.param("root / rel", id="div"),
        pytest.param("Path(root, rel)", id="path"),
        pytest.param("pathlib.PurePosixPath(rel)", id="pure-posix"),
        pytest.param("root.joinpath('a', rel)", id="joinpath"),
        pytest.param("os.path.join(root, rel)", id="os-path-join"),
        pytest.param("root / f'{rel}.py'", id="fstring"),
        pytest.param("root / ('x/' + rel)", id="concat"),
    ],
)
def test_each_join_spelling_fails(join: str) -> None:
    src = f"def f(root, m):\n    rel = m.group(1)\n    return {join}\n"
    assert hits(src) == [f"{RULE}:3"]


def test_the_name_is_followed_through_unpacking_loops_and_comprehensions() -> None:
    assert hits("def f(root, m):\n    a, b = m.groups()\n    return root / b\n") == [f"{RULE}:3"]
    assert hits("def f(root, t):\n    for n in P.findall(t):\n        yield root / n.strip()\n") == [f"{RULE}:3"]
    assert hits("def f(root, t):\n    return [root / n for n in P.findall(t)]\n") == [f"{RULE}:2"]
    assert hits("def f(root, t):\n    if (n := P.search(t).group(1)):\n        return root / n\n") == [f"{RULE}:3"]
    assert hits("def f(p, m):\n    p /= m.group(1)\n    return p\n") == [f"{RULE}:2"]


@pytest.mark.parametrize(
    "clean",
    [
        pytest.param("m.group(1).replace('\\\\', '/')", id="replace"),
        pytest.param("PureWindowsPath(m.group(1)).as_posix()", id="pure-windows-path"),
        pytest.param("'scripts/run.py'", id="literal"),
        pytest.param("Path('scripts') / 'run.py'", id="path-object"),
        pytest.param("int(m.group(1))", id="not-text"),
    ],
)
def test_normalised_literal_and_path_values_pass(clean: str) -> None:
    src = f"def f(root, m):\n    rel = {clean}\n    return root / rel\n"
    assert hits(src) == []


def test_a_split_on_the_backslash_passes() -> None:
    assert hits("def f(root, m):\n    return root.joinpath(*m.group(1).split('\\\\'))\n") == []


def test_a_clean_reassignment_clears_the_name() -> None:
    src = "def f(root, m):\n    rel = m.group(1)\n    rel = rel.replace('\\\\', '/')\n    return root / rel\n"
    assert hits(src) == []


def test_a_nested_function_starts_clean() -> None:
    src = "def f(root, m):\n    rel = m.group(1)\n    def g(rel):\n        return root / rel\n    return g\n"
    assert hits(src) == []


def test_a_parameter_is_not_known_to_be_text() -> None:
    assert hits("def f(root, rel):\n    return root / rel\n") == []


def test_test_modules_are_not_scanned() -> None:
    assert hits(PRE_FIX, "tests/unit/test_scanner.py") == []


def test_the_exempt_marker_needs_the_rule_and_a_reason() -> None:
    head = "def f(root, m):\n    rel = m.group(1)\n"
    assert hits(f"{head}    return root / rel  # {RULE}-exempt: Windows-only tool\n") == []
    assert hits(f"{head}    # {RULE}-exempt: the file is written with forward slashes\n    return root / rel\n") == []
    assert hits(f"{head}    return root / rel  # {RULE}-exempt\n") == [f"{RULE}:3"]
    assert hits(f"{head}    return root / rel  # no-window-exempt: wrong rule\n") == [f"{RULE}:3"]
