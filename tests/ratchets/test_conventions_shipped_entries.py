"""The `must_use` entries the scaffold recommends, read from the docs an adopter copies them from.

`docs/conventions-ratchet.md` ("Entries worth declaring") is the source an adopting repo pastes into its
own `.fleet.toml`. These tests parse that exact text, so an entry that stops parsing, or stops catching
the call it names, fails here instead of in an adopter. The scaffold's own table is held to the same two
entries.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from scripts import conventions_ratchet as cr

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "conventions-ratchet.md"
REQUESTS_VERBS = ("get", "post", "put", "patch", "delete", "head", "request")


def recommended_toml() -> str:
    """The toml fences between "Entries worth declaring" and the next bold paragraph, joined."""
    text = DOC.read_text(encoding="utf-8")
    start = text.index("**Entries worth declaring.**")
    end = text.index("**Enabling an entry in a repo that has hits today.**")
    return "\n".join(re.findall(r"```toml\n(.*?)```", text[start:end], flags=re.DOTALL))


def config_from(entries_toml: str) -> cr.Config:
    cfg = cr.parse_config("[conventions_ratchet]\nenabled = true\n" + entries_toml)
    assert cfg is not None
    return cfg


def entry_for(cfg: cr.Config, call: str) -> cr.MustUse:
    found = [e for e in cfg.must_use if call in e.calls]
    assert len(found) == 1, f"expected exactly one must_use entry naming {call}, got {len(found)}"
    return found[0]


def hits(cfg: cr.Config, src: str, path: str) -> list[str]:
    return [f"{h.rule}:{h.line}" for h in cr.scan_source(src, path, cr.rules_for(path, cfg), cr.entries_for(path, cfg))]


def test_the_docs_recommend_an_entry_for_each_single_home_convention() -> None:
    cfg = config_from(recommended_toml())
    for verb in REQUESTS_VERBS:
        assert entry_for(cfg, f"requests.{verb}").helper == ("src/pooled_http.py",)
    sqlite = entry_for(cfg, "sqlite3.connect")
    assert sqlite.paths == ("app/", "src/")
    assert "get_db" in sqlite.why


def test_the_requests_entry_flags_a_bare_call_and_leaves_the_pooled_session_alone() -> None:
    cfg = config_from(recommended_toml())
    bare = "".join(f"import requests\nrequests.{verb}(u)\n" for verb in REQUESTS_VERBS)
    assert len(hits(cfg, bare, "src/a.py")) == len(REQUESTS_VERBS)
    assert hits(cfg, bare, "src/pooled_http.py") == []
    assert hits(cfg, bare, "scripts/one_shot.py") == []  # a one-shot script is outside `paths`
    assert hits(cfg, "import requests\nSESSION = requests.Session()\nSESSION.get(u)\n", "src/a.py") == []


def test_the_sqlite_entry_flags_a_handler_that_opens_its_own_connection() -> None:
    cfg = config_from(recommended_toml())
    router = (
        "import sqlite3\n\n\ndef list_items():\n    conn = sqlite3.connect(DB_PATH)\n"
        "    try:\n        return conn.execute('select 1').fetchall()\n    finally:\n        conn.close()\n"
    )
    assert hits(cfg, router, "app/webapp/routers/items.py") == ["must-use:5"]
    assert hits(cfg, "from sqlite3 import connect\nconnect(DB_PATH)\n", "src/store.py") == ["must-use:2"]
    assert hits(cfg, router, "src/db.py") == []  # the module that defines get_db is the one home
    assert hits(cfg, router, "scripts/migrate.py") == []  # outside `paths`
    assert hits(cfg, router, "tests/test_items.py") == []


def test_the_sqlite_entry_takes_the_repos_helper_and_a_reasoned_exemption() -> None:
    own_home = recommended_toml().replace('helper = ["src/db.py"]', 'helper = ["src/connection.py"]')
    cfg = config_from(own_home)
    call = "import sqlite3\nconn = sqlite3.connect(DB_PATH)\n"
    assert hits(cfg, call, "src/connection.py") == []
    assert hits(cfg, call, "src/other.py") == ["must-use:2"]
    marked = "import sqlite3\n# must-use-exempt: a long-lived single connection\nconn = sqlite3.connect(DB_PATH)\n"
    assert hits(cfg, marked, "src/other.py") == []


def test_the_scaffolds_own_table_holds_the_same_two_entries() -> None:
    cfg, _ = cr.load_config(REPO_ROOT)
    assert cfg is not None
    for call in ("requests.get", "sqlite3.connect"):
        assert call in {c for e in cfg.must_use for c in e.calls}, f"the scaffold's .fleet.toml has no must_use entry for {call}"
    sqlite = entry_for(cfg, "sqlite3.connect")
    assert (REPO_ROOT / sqlite.helper[0]).is_file(), "the scaffold's sqlite helper must exist"
    assert tomllib.loads((REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8"))["conventions_ratchet"]["enabled"] is True
