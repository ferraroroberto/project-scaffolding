# Portable project skills

This is the project layout and onboarding contract for [project-scaffolding#250](https://github.com/ferraroroberto/project-scaffolding/issues/250). Fleet-wide discovery, link installation, ownership records and repair belong to [fleet-config#748](https://github.com/ferraroroberto/fleet-config/issues/748); this scaffold does not ship that installer. Machine-wide instructions remain owned by `fleet-config`.

## Instruction chain

A fresh clone commits `CLAUDE.md` as its project instructions and `AGENTS.md` as the short pointer to that file. Keep both names: Claude reads the former; Codex and Pi discover the latter and are instructed to read the former. A pointer is an instruction to the agent, not a filesystem include. Never maintain a second copy of the project prose. A package needing additional instructions follows the same pattern inside that package; the nested file supplements the root instructions. Launch Codex or Pi inside that package to establish its scope. Do not rely on a root-started session discovering later changes to its working directory.

## One source, links at the same scope

Keep each existing skill at its maintained source, including a real `.agents/skills/<name>` source. Do not migrate directories solely to change agent branding. In a new project, a reviewed `.claude/skills/<name>/SKILL.md` is a concrete starting convention; another native root can remain canonical when already adopted. Record each source and its repository-relative scope in the project's README. A directory existing on disk is not evidence that a client loads it.

```text
CLAUDE.md                           maintained project instructions
AGENTS.md                           committed pointer
.claude/skills/project-check/        maintained root skill
.agents/skills/project-check/        generated link to that one directory
packages/api/CLAUDE.md               optional package instructions
packages/api/AGENTS.md               optional package pointer
packages/api/.claude/skills/api-check/  maintained package skill
packages/api/.agents/skills/api-check/  generated link at the SAME scope
```

Use a directory junction on Windows or a directory symlink on POSIX. Link the complete skill directory so its relative references to scripts/assets still work. A source outside a native discovery root may need one link in each required native root. A source already visible through native compatibility needs no additional route. Do not link a package skill into the root or any user home: that would make it available to unrelated work.

Discovery links are per skill, never replacements for an entire `.agents`, `.claude` or `skills` directory. Preserve real directories, unrelated files, private sources and user-created links. Inspect reparse points and resolved targets before writing. If the desired entry already resolves to the selected source, leave it alone. If the entry exists with different content or a different target, report a collision and leave both entries untouched; never merge, overwrite, rename or delete either source automatically.

Compare both the frontmatter `name` and the resolved source identity across all roots visible to the client, including root/package ancestors and user skills. Same source through two routes is one skill; publish only one route where possible and confirm the native inventory contains one entry. Different sources with the same name are a collision even if their folder names differ. Require an explicit owner decision to select or rename a skill; do not depend on a harness's precedence rules (Codex may list both, while other clients choose a winner). Sibling-only skills may reuse a name only if their scopes never overlap in the session.

Only selected skill directories with a valid `SKILL.md` enter generated discovery roots. Exclude helper containers such as `_lib`, `_shared`, `_private`, dot directories, caches, conversations, memory and runtime output. Helpers referenced *inside* an approved skill remain beside its source, not separately advertised as skills. Do not recursively mirror a source parent: clients differ in how they scan grouping directories and helper Markdown. `docs/agents/skills/` in this scaffold contains documentation pointers, not an installable project skill catalog.

## Tracking and lifecycle

The scaffold ignores `.claude/`, `.agents/` and `.codex/` at every depth by default, preserving local private context. Those directories may contain legitimate maintained skills and generated discovery links; “ignored” does not mean “safe to replace.” `.pi/` and `.grok/` local configuration also remain ignored. Do not unignore an entire agent directory or force-add private skills to make them portable.

When a skill is intentionally shared with a clone, review all files in its source, then narrowly replace the applicable blanket ignore rule with an allowlist for that approved source. For example, to share only a root `project-check` source, replace the `.claude/` rule with:

```gitignore
**/.claude/*
!/.claude/skills/
/.claude/skills/*
!/.claude/skills/project-check/
```

For a nested source use the exact package path in the three anchored rules instead. For multiple approved sources add explicit scope/name exceptions. If the source is in `.agents/skills`, apply the same narrow pattern to `.agents/`; keep all generated sibling links ignored. Ordinary ignore patterns for secrets, logs and caches still apply. Review `git status --short --untracked-files=all`, `git check-ignore -v --no-index <private-path>`, and the exact staged file list before committing. A private local skill stays private and is not promised to fresh clones.

After cloning, inventory the tracked sources, then create the missing scoped discovery links only for clients that need them. This is a local onboarding step until the fleet installer provides it; cloning alone cannot recreate ignored links. For a single reviewed skill in a fresh scope, these are the link primitives (inspect collisions first):

```powershell
# From the scope directory; existing real parents are kept.
$source = (Resolve-Path .claude/skills/project-check).Path
New-Item -ItemType Directory -Path .agents/skills -Force | Out-Null
# Run only when this exact entry is absent, including dangling links.
New-Item -ItemType Junction -Path .agents/skills/project-check -Target $source
```

```sh
mkdir -p .agents/skills
# Run only when neither -e nor -L reports an existing entry.
ln -s ../../.claude/skills/project-check .agents/skills/project-check
```

Record generated link path, resolved source and owner so refresh/cleanup can distinguish owned links from user data. Reconcile after a source is added, moved or removed and after a checkout moves. Remove only an owned link whose identity still matches the record, never its target; an unknown, modified or broken entry gets its own report. On Windows, remove a verified directory junction itself with `[System.IO.Directory]::Delete($link)` (one verified link path, without recursion); never recursively delete across reparse points.

Every worktree is its own checkout and discovery scope. Recreate links against that worktree's sources, never the primary checkout's ignored private directories. Do not copy private context or share an absolute primary-source junction into a worktree. Before worktree teardown, unlink its owned junctions without traversing their targets. Recreating the same links twice must leave the same source and inventory; teardown must leave the primary sources and all real directories intact.

## Capability and evidence

Native documentation: [Claude skills](https://code.claude.com/docs/en/skills), [Codex skills](https://developers.openai.com/codex/skills/), [Codex instructions](https://developers.openai.com/codex/guides/agents-md/). Pi's installed `docs/skills.md` and `dist/core/resource-loader.js` are the source for its installed release; Grok's installed `inspect --help` and `inspect --json` establish its compatibility discovery. Check installed versions again after upgrades.

The issue's disposable fixture probes observed the following on 2026-09-05. **Verified** here means native discovery metadata, not skill execution, hook parity or model quality. **Unsupported** means a capability was tested and absent; **unknown** means it was not established. No row is inferred from a directory's existence.

| Client | Verified discovery | Unsupported / unknown |
| --- | --- | --- |
| Claude Code 2.1.261 | Native initialization `commands` catalog, project settings: root sees root sentinel once; package sees root + package once each; sibling sees root only. Canonical `.claude/skills` sources need no link. A second probe verified a real `.agents` source through one inverse `.claude` junction, once per visible scope. | Root-session on-demand nested discovery is documented but not exercised here; model invocation and instruction-pointer obedience are unknown. |
| Codex CLI 0.153.3 | Installed app-server `skills/list`, `forceReload: true`: same root/package/sibling result through per-skill `.agents/skills` junctions; returned paths resolve to maintained sources. | Automatic descendant discovery from a root-started session is not the documented contract; start in the package. Model invocation is unknown. |
| Pi 0.84.4 | Installed `DefaultResourceLoader`, trusted project, no extensions: same scoped inventory using native `.agents/skills`; no `.pi` mirror needed. | Untrusted-project loading is excluded by its documented trust contract. Interactive trust UI and skill execution are unknown. |
| Grok 0.2.118 | `inspect --json`: `.claude/skills` compatibility discovers root without a Grok link; with `.agents` links, root/package/sibling inventories contain one matching entry per visible sentinel. | In-session descendant refresh and skill execution are unknown. No unsupported native-root claim follows from this probe. |

## Repeatable verification

Use disposable local repositories containing public synthetic sentinels only; never send real private context to a model for a discovery test. Prefer local inventory interfaces without a model turn. Keep normal client configuration untouched and record any per-probe settings/trust differences.

1. Start from a disposable clone with the committed instruction pointer. Separately create an empty synthetic repository for client probes that might load context; add a root sentinel, a differently named package sentinel and an empty sibling. Each skill has valid `name`/`description` frontmatter and a body that only says to return a harmless marker. Add a pre-existing real `.agents/keep.txt` and a distinct maintained `.agents/skills` entry.
2. Before linking, inspect each client's native inventory. Add only missing per-skill routes; repeat the inventory at root, package and sibling. Expect root-only / root-plus-package / root-only and exactly one entry per resolved source. Test the inverse source direction when adopting a real `.agents` source for Claude.
3. Introduce a different source with a colliding frontmatter name, and an occupied destination with different content. The onboarding collision check must report each and leave both intact. Remove only the synthetic collision after recording it. Check helpers/private directories have no generated route.
4. Exercise the narrow ignore allowlist in the clone: the reviewed source is eligible for tracking, while private context, conversations, local settings, helper containers and generated links remain ignored. Confirm `AGENTS.md` and `CLAUDE.md` remain tracked.
5. Create a disposable linked worktree from committed synthetic sources and recreate its own links. A worktree source edit must appear through its link and leave the primary source unchanged. Verify repeated setup has no duplicate entries and cleanup removes only the owned links before removing that disposable worktree.
6. Record client version, cwd/scope, link target, observed catalog and every unknown separately in the issue/PR. Run the scaffold's `scripts/verify-before-ship.ps1`; filesystem fixtures supplement this gate and do not substitute for native discovery evidence.
