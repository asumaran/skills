# skills

Personal collection of [Agent Skills](https://code.claude.com/docs/en/skills)
for Claude Code and other compatible agents.

Each skill lives in `skills/<name>/SKILL.md`. The layout is compatible with the
[`npx skills`](https://github.com/vercel-labs/skills) installer.

## Install

Install every skill globally (into `~/.claude/skills/`):

```bash
npx skills add asumaran/skills --skill '*' -g -a claude-code -y
```

Or a single skill:

```bash
npx skills add asumaran/skills --skill worktree -g -a claude-code -y
```

## Install scope

Every skill here is meant to be installed **globally** by default; the dotfiles
`skills` module installs all of them into `~/.claude/skills/` on every run. A
skill can opt out of that automatic install by declaring it in its SKILL.md
frontmatter:

```yaml
---
name: my-skill
description: ...
install: manual
---
```

Skills marked `install: manual` are skipped by the automatic installers and are
installed by hand (e.g. per-project) with `npx skills add ... --skill <name>`.

## Tests

The scripts with logic (`skills/task/status.py`, `skills/worker/lineage.sh`)
have fixture tests under `tests/`, run against temp dirs and fake `gh`/`herdr`
binaries (they never touch `~/.claude`):

```bash
python3 tests/status_test.py
bash tests/lineage_test.sh
```

## Skills

| Skill | What it does |
|-------|--------------|
| `gen-commit-msg` | Generate a Conventional Commits message and commit, with selective staging and the user's title/body format. |
| `handoff` | Write or refresh `HANDOFF.md`, the untracked resume file at a worktree or task directory root, so a fresh session can continue the work. |
| `pr-collapsible-tests` | Reorganize the manual test steps of a PR description into collapsible `<details>` toggles. |
| `ship` | `/ship [commit\|push\|release\|deploy]`: ship the current work up to the given level using the repo's documented mechanism. Explicit invocation only. |
| `task` | `/task new\|plan\|go\|status\|resume\|decide\|close\|promote\|link\|gate\|ack\|new-repo\|help`: run any assignment (a Jira ticket, an idea, a personal project) as a task with its state in `~/.claude/work/<KEY>/` (`TASK.md` frontmatter operated by `status.sh`, a plan, numbered decisions, reports), launching deliverables through workers. `/task status --all` summarizes every task (coordinator state, phases, most urgent next action); `status` ends with a "Next commands:" footer; `/task help` prints the command table (`status.sh help`, also shown when bare `/task` finds no task); `status.sh workers-in <worktree>` discovers the agents living in an adopted worktree. |
| `worker` | Launch a Claude worker for a ticket, a PR or a task deliverable (`--task <dir>#<id>`, rounds with `--round N`) in its own worktree and herdr space, with a handoff, a standard boot prompt and a lineage record (`lineage.sh`) that `asagents` draws the agents tree from. |
| `worktree` | Create git worktrees with the `wt` CLI following the canonical `~/wt/{repo}/{branch}` layout and herdr integration, and hand work off to a Claude instance in the worktree's herdr space. |
| `zed` | Open files, worktrees, diffs or generated output in the Zed editor from a terminal session, picking the right window flag. |
