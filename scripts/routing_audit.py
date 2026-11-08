"""Nightly audit of what per-change e2e routing skipped.

The per-change gate routes e2e with `classify_e2e` (skip / static / surface /
full). The nightly full run is the audit of that routing: a failing node on a
night whose merged commits were routed skip, or static for a node outside the
static target, means the adopter's `[e2e]` rules are too narrow.

Two halves, split by trust:

  audit   runs on the Mac runner after the WebKit leg. Reads only the adopter
          checkout, the junit file and its own state file; makes no network
          call and writes `audit.json` in the run folder. Ends on one line:
          ``AUDIT=clean nights=1 misses=0`` (exit 0),
          ``AUDIT=miss nights=1 misses=N`` (exit 1) or
          ``AUDIT=unknown nights=0 reason=...`` (exit 3, never folded into
          clean).
  file    runs on a trusted host that holds `gh`. Reads a pulled `audit.json`
          (untrusted data: adopter code produced the node ids) and files, or
          comments on, ONE deduped issue in the adopter. Ends on
          ``FILE=none|created|commented|unchanged`` or ``FILE=unknown`` (exit 3).

Routing is judged with the adopter's current `[e2e]` table over each commit's
changed files, a shared stylesheet counting as full: that leans toward fewer
misses, never false ones. Docs: docs/mac-runner.md, "Routing audit".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from classify_e2e import E2EConfig, classify, load_config  # noqa: E402 -- needs the sys.path lines above

from src import runtime_files  # noqa: E402 -- needs the sys.path lines above
from src.no_window import NO_WINDOW  # noqa: E402 -- needs the sys.path lines above

GIT_TIMEOUT_S = 120
GH_TIMEOUT_S = 60
MAX_AUDIT_BYTES = 1_000_000
MAX_NODES_IN_ISSUE = 50
MAX_NODE_CHARS = 300
ISSUE_TITLE = "e2e routing: nightly audit found a miss"
OWNER = "ferraroroberto"
_REPO_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


# ------------------------------------------------------------------ git
def _git(repo: Path, *args: str) -> str | None:
    """Stdout of a git command in *repo*, or None when it fails or times out."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            creationflags=NO_WINDOW, timeout=GIT_TIMEOUT_S, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def _commit_files(repo: Path, sha: str) -> list[str] | None:
    """Paths one first-parent commit changed (against its first parent)."""
    if _git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^1") is not None:
        out = _git(repo, "diff", "--name-only", f"{sha}^1", sha)
    else:
        out = _git(repo, "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", sha)
    return None if out is None else [ln for ln in out.splitlines() if ln.strip()]


# ---------------------------------------------------------------- junit
def _resolve_module(repo: Path, classname: str) -> tuple[str, str] | None:
    """Split a junit classname into (module path, class chain) by what exists on disk."""
    parts = [p for p in classname.split(".") if p]
    for i in range(len(parts), 0, -1):
        rel = "/".join(parts[:i]) + ".py"
        if (repo / rel).is_file():
            return rel, ".".join(parts[i:])
    return None


def failing_nodes(junit: Path, repo: Path) -> list[tuple[str, bool]] | None:
    """(node id, module resolved) per failed or errored testcase; None when unreadable."""
    try:
        root = ET.parse(junit).getroot()
    except (OSError, ET.ParseError):
        return None
    found: dict[str, bool] = {}
    for case in root.iter("testcase"):
        if case.find("failure") is None and case.find("error") is None:
            continue
        name = case.get("name", "")
        resolved = _resolve_module(repo, case.get("classname", ""))
        if resolved is None:
            node = f"{case.get('classname', '')}::{name}".strip(":")
            found[node] = False
        else:
            module, chain = resolved
            node = "::".join(p for p in (module, *chain.split("."), name) if p)
            found[node] = True
    return sorted(found.items())


def _in_target(node: str, targets: str) -> bool:
    module = node.split("::", 1)[0]
    for target in targets.split():
        if "::" in target:
            if node == target or node.startswith(target + "::"):
                return True
        elif module == target or module.startswith(target.rstrip("/") + "/"):
            return True
    return False


# ---------------------------------------------------------------- audit
def _unknown(reason: str) -> dict[str, Any]:
    return {"outcome": "unknown", "nights": 0, "misses": 0, "reason": reason}


def _classify_window(repo: Path, config: E2EConfig, base: str, head: str) -> dict[str, int] | None:
    """Tier counts over the first-parent commits in base..head; None when git cannot say."""
    listing = _git(repo, "rev-list", "--first-parent", f"{base}..{head}")
    if listing is None:
        return None
    counts = {"skip": 0, "static": 0, "surface": 0, "full": 0}
    for sha in listing.split():
        files = _commit_files(repo, sha)
        if files is None:
            return None
        if not files:
            continue
        counts[classify(files, config, {}).tier] += 1
    return counts


def _read_state(path: Path) -> str | None:
    try:
        sha = json.loads(path.read_text(encoding="utf-8")).get("last_green_sha")
    except (OSError, ValueError, AttributeError):
        return None
    return sha if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{7,64}", sha) else None


def _write_state(path: Path, sha: str) -> None:
    runtime_files.make_dirs(path.parent)
    tmp = path.with_suffix(".tmp")
    runtime_files.save_text(tmp, json.dumps({"last_green_sha": sha}))
    tmp.replace(path)


def run_audit(repo: Path, e2e_outcome: str, junit: Path, state: Path) -> dict[str, Any]:
    """Audit one night. Advances *state* only on a green full-suite night."""
    if e2e_outcome not in ("success", "failure"):
        return _unknown(f"WebKit e2e leg {e2e_outcome or 'not run'}")
    head = (_git(repo, "rev-parse", "HEAD") or "").strip()
    if not head:
        return _unknown("adopter HEAD not readable")
    if e2e_outcome == "success":
        _write_state(state, head)
        return {"outcome": "clean", "nights": 1, "misses": 0, "reason": "green night"}

    nodes = failing_nodes(junit, repo)
    if nodes is None:
        return _unknown("junit file missing or unreadable")
    if not nodes:
        return _unknown("e2e failed but no failing test was parsed")
    config = load_config(repo / ".fleet.toml")
    if config.source != "declared":
        return _unknown(f"adopter [e2e] table {config.source}")
    base = _read_state(state)
    if base is None:
        return _unknown("no earlier green night recorded")
    if _git(repo, "merge-base", "--is-ancestor", base, head) is None:
        return _unknown("last green commit not in the adopter history")
    tiers = _classify_window(repo, config, base, head)
    if tiers is None:
        return _unknown("window commits not readable")

    all_ids = [n for n, _ in nodes]
    if tiers["skip"]:
        missed = all_ids
    elif tiers["static"]:
        if any(not ok and not _in_target(n, config.static_pytest_target) for n, ok in nodes):
            return _unknown("failing node outside any readable module under a static-routed change")
        missed = [n for n in all_ids if not _in_target(n, config.static_pytest_target)]
    else:
        missed = []
    return {
        "outcome": "miss" if missed else "clean", "nights": 1, "misses": len(missed),
        "reason": "failing nodes on skip/static-routed changes" if missed else "routing covered the failure",
        "failing_nodes": all_ids, "miss_nodes": missed, "tiers": tiers,
        "window_commits": sum(tiers.values()),
    }


def _audit_main(args: argparse.Namespace) -> int:
    result = run_audit(Path(args.repo_dir), args.e2e_outcome, Path(args.junit), Path(args.state))
    result["repo"] = args.repo
    runtime_files.make_dirs(Path(args.out).parent)
    runtime_files.save_text(args.out, json.dumps(result, indent=2))
    out, nights, misses = result["outcome"], result["nights"], result["misses"]
    note = f", unknown: {result['reason']}" if out == "unknown" else ""
    if args.summary_file:
        runtime_files.append_text(args.summary_file, f"Routing audit: nights audited {nights}, misses found {misses}{note}.\n\n")
    if out == "unknown":
        print(f"AUDIT=unknown nights=0 reason={result['reason']}")
        return 3
    print(f"AUDIT={out} nights={nights} misses={misses}")
    return 1 if out == "miss" else 0


# ----------------------------------------------------------------- file
def _clean_node(node: str) -> str:
    return re.sub(r"[\x00-\x1f`]", "", node)[:MAX_NODE_CHARS]


def _validated(path: Path) -> dict[str, Any] | None:
    """The pulled audit.json if it is the shape this tool writes, else None."""
    try:
        if path.stat().st_size > MAX_AUDIT_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not _REPO_NAME.match(str(data.get("repo", ""))):
        return None
    nodes, tiers = data.get("miss_nodes"), data.get("tiers")
    if not isinstance(nodes, list) or not all(isinstance(n, str) for n in nodes):
        return None
    if not isinstance(tiers, dict) or not all(isinstance(v, int) for v in tiers.values()):
        return None
    return data


def marker(nodes: list[str]) -> str:
    digest = hashlib.sha256("\n".join(sorted(nodes)).encode("utf-8")).hexdigest()[:12]
    return f"<!-- routing-audit:{digest} -->"


def issue_body(data: dict[str, Any]) -> str:
    nodes = [_clean_node(n) for n in sorted(data["miss_nodes"])]
    shown = nodes[:MAX_NODES_IN_ISSUE]
    more = f"\n... and {len(nodes) - len(shown)} more" if len(nodes) > len(shown) else ""
    tiers = data["tiers"]
    tier_text = ", ".join(f"{k}: {v}" for k, v in sorted(tiers.items()))
    return "\n\n".join([
        "## What & why",
        "The nightly full e2e run failed on nodes that per-change routing would have skipped, so the `[e2e]` rules in `.fleet.toml` are too narrow for these changes.",
        "## Routing verdict",
        f"- Commits audited since the last green night: {data.get('window_commits', sum(tiers.values()))} ({tier_text})\n- Failing nodes the routing would not have run: {len(nodes)}",
        "## Failing nodes",
        "```\n" + "\n".join(shown) + more + "\n```",
        "## Acceptance",
        "- [ ] The `[e2e]` rules route the changes that touch these nodes to a tier that runs them.\n- [ ] The next nightly run is green or reports no miss.",
        marker(data["miss_nodes"]),
    ])


def _gh(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["gh", *args], capture_output=True, text=True, encoding="utf-8",
            errors="replace", stdin=subprocess.DEVNULL, creationflags=NO_WINDOW,
            timeout=GH_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def file_issue(data: dict[str, Any], slug: str) -> tuple[str, str]:
    """File or update the one deduped issue. Returns (FILE state, detail)."""
    listing = _gh("issue", "list", "--repo", slug, "--state", "open", "--search",
                  f'"{ISSUE_TITLE}" in:title', "--json", "number,title")
    if listing is None:
        return "unknown", "gh could not list issues"
    try:
        open_numbers = [i["number"] for i in json.loads(listing) if i.get("title") == ISSUE_TITLE]
    except (ValueError, KeyError, TypeError):
        return "unknown", "gh listing unreadable"
    body = issue_body(data)
    if not open_numbers:
        url = _gh("issue", "create", "--repo", slug, "--title", ISSUE_TITLE, "--body", body,
                  "--label", "bug", "--assignee", "@me")
        return ("created", url.strip()) if url else ("unknown", "gh could not create the issue")
    number = str(open_numbers[0])
    view = _gh("issue", "view", number, "--repo", slug, "--json", "body,comments")
    if view is None:
        return "unknown", "gh could not read the open issue"
    if marker(data["miss_nodes"]) in view:
        return "unchanged", f"#{number}"
    done = _gh("issue", "comment", number, "--repo", slug, "--body", body)
    return ("commented", f"#{number}") if done is not None else ("unknown", "gh could not comment")


def _file_main(args: argparse.Namespace) -> int:
    data = _validated(Path(args.audit))
    if data is None:
        print("FILE=unknown reason=audit.json missing or not the expected shape")
        return 3
    if data.get("outcome") != "miss" or not data["miss_nodes"]:
        print(f"FILE=none outcome={data.get('outcome')}")
        return 0
    slug = args.repo_slug or f"{OWNER}/{data['repo']}"
    if args.dry_run:
        print(issue_body(data))
        print("FILE=none dry-run")
        return 0
    state, detail = file_issue(data, slug)
    print(f"FILE={state} {detail}")
    return 3 if state == "unknown" else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="audit one night (runner side, no network)")
    a.add_argument("--repo-dir", required=True)
    a.add_argument("--repo", required=True, help="adopter repo name")
    a.add_argument("--e2e-outcome", required=True)
    a.add_argument("--junit", required=True)
    a.add_argument("--state", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--summary-file")
    f = sub.add_parser("file", help="file or update the adopter issue (trusted host, needs gh)")
    f.add_argument("--audit", required=True)
    f.add_argument("--repo-slug", help="owner/name; default is the owner's repo named in audit.json")
    f.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv[1:])
    return _audit_main(args) if args.cmd == "audit" else _file_main(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
