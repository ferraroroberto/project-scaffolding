"""Fleet scoreboard for the implicit-state-machine work: numbers from committed state only.

    python scripts/tools/state_scoreboard.py [--at <date|sha|rev>] [--root DIR] [--repo NAME ...] [--json]
                                       [--bug-split <date>]

For every fleet repo (a git checkout under the fleet root that has a `.fleet.toml`) it reads only
what is committed at one commit and reports: the conventions-baseline counts of the three state
rules, the declared `[[state_machines]]`, the tests that prove each machine refuses an illegal
transition, and the places outside a declared owner that write or re-spell a machine's state.
`--bug-split` adds the lagging bug signal (needs `gh`). Two runs at the same commit print
byte-identical output, and nothing is ever written to a repo.

A repo or section that cannot be read is `unknown` (`?`), never zero; one the repo has not opted
into is `not-enrolled` (`-`); one whose history does not reach `--at` is `absent`. Exit codes: 0 all
readable, 2 bad arguments, 3 at least one repo unknown. The metrics and which are targets:
docs/implicit-state-machines.md, "Scoreboard".
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.conventions_state import is_js_source, js_state_names  # noqa: E402 -- need the sys.path line above
from scripts.tools.state_scoreboard_bugs import GhRunner, closed_bugs, count_bugs, github_slug, run_gh  # noqa: E402
from scripts.tools.state_scoreboard_read import (  # noqa: E402 -- need the sys.path line above
    STATE_RULES,
    ReadError,
    count_proofs,
    enrolled_rules,
    epoch,
    is_date,
    parse_config,
    read_file,
    read_findings,
    read_machines,
    resolve_ref,
    run_git,
    state_names,
)
from src.fleet_root import FleetRootError, fleet_root  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NOT_CONFIRMED = 3
UNKNOWN = "?"
NOT_MEASURED = "-"


def discover(root: Path, only: list[str]) -> list[Path]:
    """The fleet's primary checkouts: git folders (not worktrees) holding a committed `.fleet.toml`."""
    repos = []
    for folder in sorted(root.iterdir(), key=lambda p: p.name):
        if not (folder / ".git").is_dir() or (only and folder.name not in only):
            continue
        try:
            has_card = run_git(folder, "cat-file", "-e", "HEAD:.fleet.toml").returncode == 0
        except ReadError:
            has_card = False
        if has_card or folder.name in only:
            repos.append(folder)
    return repos


def _unknown(reason: str) -> dict[str, Any]:
    return {"status": "unknown", "reason": reason}


def _machines(repo: Path, sha: str, config: dict[str, Any], split: str | None, gh: GhRunner) -> dict[str, Any]:
    try:
        declared = read_machines(config)
    except ReadError as exc:
        return _unknown(str(exc))
    out: dict[str, Any] = {"status": "ok", "declared": len(declared), "items": []}
    try:
        proofs = count_proofs(repo, sha, declared) if declared else {}
    except ReadError as exc:
        proofs = {}
        out["proof_reason"] = str(exc)
    issues, bug_reason = [], ""
    if split and declared:
        try:
            issues = closed_bugs(github_slug(repo), gh)
        except ReadError as exc:
            bug_reason = str(exc)
    for machine in declared:
        js = is_js_source(machine.module)
        source = read_file(repo, sha, machine.module) if js or machine.module.endswith(".py") else None
        reader = js_state_names if js else state_names
        states = reader(source, machine.type) if source else []
        item: dict[str, Any] = {"name": machine.name, "module": machine.module, "states": len(states),
                                "proof_tests": proofs.get(machine.name)}
        if split:
            item["bugs"] = _unknown(bug_reason) if bug_reason else count_bugs(issues, machine, states, split)
        out["items"].append(item)
    return out


def measure(repo: Path, at: str, split: str | None = None, gh: GhRunner = run_gh) -> dict[str, Any]:
    """One repo's scoreboard row at `at`; every section is `ok`, `not-enrolled` or `unknown` on its own."""
    row: dict[str, Any] = {"repo": repo.name}
    try:
        sha = resolve_ref(repo, at)
        if sha is None:
            return {**row, "status": "absent", "reason": f"no commit at or before {at}"}
        row["sha"] = sha[:12]
        text = read_file(repo, sha, ".fleet.toml")
        if text is None:
            return {**row, "status": "not-enrolled", "reason": "no .fleet.toml at this commit",
                    "findings": {"status": "not-enrolled"}, "machines": {"status": "ok", "declared": 0, "items": []}}
        config = parse_config(text)
    except ReadError as exc:
        return {**row, "status": "unknown", "reason": str(exc), "findings": _unknown(str(exc)),
                "machines": _unknown(str(exc))}
    row["machines"] = _machines(repo, sha, config, split, gh)
    row["findings"] = _findings(repo, sha, config)
    row["status"] = _overall(row)
    return row


def _findings(repo: Path, sha: str, config: dict[str, Any]) -> dict[str, Any]:
    try:
        rules = enrolled_rules(config)
        if not rules:
            return {"status": "not-enrolled", "reason": "conventions ratchet does not enforce a state rule"}
        by_rule = read_findings(repo, sha, config, rules)
    except ReadError as exc:
        return _unknown(str(exc))
    out: dict[str, Any] = {"status": "ok", "by_rule": by_rule}
    if len(rules) == len(STATE_RULES):
        # The re-spelled-state and shared-flag rules are the places beyond a declared owner.
        out["duplicate_derivations"] = sum(sum(by_rule[r].values()) for r in ("state-set-repeat", "state-write"))
    return out


def _overall(row: dict[str, Any]) -> str:
    machines, findings = row["machines"], row["findings"]
    proofs_unknown = any(i["proof_tests"] is None for i in machines.get("items", []))
    if "unknown" in (machines["status"], findings["status"]) or proofs_unknown:
        return "unknown"
    return "not-enrolled" if findings["status"] == "not-enrolled" else "ok"


def totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fleet sums over the repos each number was actually measured in, with the counts that were not."""
    out: dict[str, Any] = {"repos": len(rows), "by_status": {}, "findings": {r: {"py": 0, "js": 0} for r in STATE_RULES},
                           "findings_repos": 0, "duplicate_derivations": 0, "duplicate_repos": 0,
                           "machines": 0, "machines_without_proof": 0, "machines_proof_unknown": 0}
    for row in rows:
        out["by_status"][row["status"]] = out["by_status"].get(row["status"], 0) + 1
        findings = row.get("findings", {})
        if findings.get("status") == "ok":
            out["findings_repos"] += 1
            for rule, split in findings["by_rule"].items():
                for kind, count in split.items():
                    out["findings"][rule][kind] += count
            if "duplicate_derivations" in findings:
                out["duplicate_repos"] += 1
                out["duplicate_derivations"] += findings["duplicate_derivations"]
        for item in row.get("machines", {}).get("items", []):
            out["machines"] += 1
            if item["proof_tests"] is None:
                out["machines_proof_unknown"] += 1
            elif item["proof_tests"] == 0:
                out["machines_without_proof"] += 1
    out["by_status"] = dict(sorted(out["by_status"].items()))
    return out


def _cell(value: Any) -> str:
    return UNKNOWN if value is None else str(value)


def _rule_cell(row: dict[str, Any], rule: str) -> str:
    findings = row.get("findings", {})
    if findings.get("status") == "unknown":
        return UNKNOWN
    split = findings.get("by_rule", {}).get(rule)
    return NOT_MEASURED if split is None else f"{split['py']}/{split['js']}"


def _row_cells(row: dict[str, Any]) -> list[str]:
    findings, machines = row.get("findings", {}), row.get("machines", {})
    dup = findings.get("duplicate_derivations")
    dup_cell = UNKNOWN if findings.get("status") == "unknown" else NOT_MEASURED if dup is None else str(dup)
    items = machines.get("items", [])
    declared = UNKNOWN if machines.get("status") == "unknown" else str(machines.get("declared", 0))
    unproven = UNKNOWN if machines.get("status") == "unknown" or any(i["proof_tests"] is None for i in items) \
        else str(sum(1 for i in items if i["proof_tests"] == 0))
    return [row["repo"], row.get("sha", NOT_MEASURED), row["status"],
            *(_rule_cell(row, r) for r in STATE_RULES), dup_cell, declared, unproven]


def render(rows: list[dict[str, Any]], total: dict[str, Any], at: str, split: str | None) -> str:
    """The plain-text scoreboard: one table, the fleet totals, then every reason and machine."""
    head = ["repo", "commit", "status", "literal py/js", "set-repeat py/js", "write py/js", "duplicates", "machines",
            "no proof"]
    cells = [head, *(_row_cells(r) for r in rows)]
    widths = [max(len(c[i]) for c in cells) for i in range(len(head))]
    lines = [f"State scoreboard at {at}", ""]
    lines += ["  ".join(c.ljust(w) for c, w in zip(line, widths, strict=True)).rstrip() for line in cells]
    f, by = total["findings"], total["by_status"]
    kinds = ", ".join(f"{k} {v}" for k, v in by.items()) or "none"
    lines += ["", f"Repos: {total['repos']} ({kinds})",
              f"Findings (target 0, {total['findings_repos']} repos measured): "
              + ", ".join(f"{r} {f[r]['py']}/{f[r]['js']}" for r in STATE_RULES),
              f"Duplicate derivations (target 0, {total['duplicate_repos']} repos measured): "
              f"{total['duplicate_derivations']}",
              f"Declared machines: {total['machines']}; without a transition proof: {total['machines_without_proof']};"
              f" proof unknown: {total['machines_proof_unknown']}"]
    lines += _details(rows, split)
    return "\n".join(lines) + "\n"


def _details(rows: list[dict[str, Any]], split: str | None) -> list[str]:
    lines: list[str] = []
    for row in rows:
        reasons = [row.get("reason", ""), row.get("findings", {}).get("reason", ""),
                   row.get("machines", {}).get("reason", ""), row.get("machines", {}).get("proof_reason", "")]
        for reason in dict.fromkeys(r for r in reasons if r):
            lines.append(f"{row['repo']}: {row['status']}: {reason}")
    machines = [(r["repo"], i) for r in rows for i in r.get("machines", {}).get("items", [])]
    if machines:
        lines += ["", "Machines (proof tests = tests marked state-machine-proof):"]
    for repo, item in machines:
        line = f"  {repo}: {item['name']} ({item['module']}) states {item['states']}, proof tests {_cell(item['proof_tests'])}"
        if item["proof_tests"] == 0:
            line += "  <- no proof"
        bugs = item.get("bugs")
        if bugs and bugs.get("status") == "unknown":
            line += f"  bugs ? ({bugs['reason']})"
        elif bugs:
            line += f"  bugs closed before/after {split}: {bugs['before']}/{bugs['after']}"
        lines.append(line)
    return lines


def _moment(text: str) -> str:
    return dt.datetime.fromtimestamp(epoch(text), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None, gh: GhRunner = run_gh) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--at", default="HEAD", help="a date (UTC, YYYY-MM-DD[THH:MM]), a revision, or `default` (each repo's origin/HEAD tip); default HEAD")
    parser.add_argument("--root", type=Path, help="the folder holding the fleet's repos (default: the fleet root)")
    parser.add_argument("--repo", action="append", default=[], help="only this repo folder (repeatable)")
    parser.add_argument("--json", action="store_true", help="print the full scoreboard as JSON")
    parser.add_argument("--bug-split", help="a date: add closed-bug counts before/after it (needs gh)")
    args = parser.parse_args(argv)
    try:
        split = _moment(args.bug_split) if args.bug_split else None
        if args.bug_split and not is_date(args.bug_split):
            raise ValueError("--bug-split must be a date")
        root = args.root or fleet_root()
        if args.at and is_date(args.at):
            epoch(args.at)
    except (ValueError, FleetRootError) as exc:
        print(f"state_scoreboard: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not root.is_dir():
        print(f"state_scoreboard: {root} is not a directory", file=sys.stderr)
        return EXIT_USAGE
    rows = [measure(repo, args.at, split, gh) for repo in discover(root, args.repo)]
    total = totals(rows)
    if args.json:
        print(json.dumps({"at": args.at, "bug_split": split, "repos": rows, "totals": total}, indent=2, sort_keys=True))
    else:
        sys.stdout.write(render(rows, total, args.at, split))
    return EXIT_NOT_CONFIRMED if total["by_status"].get("unknown") else EXIT_OK


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
