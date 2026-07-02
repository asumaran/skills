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

## Skills

| Skill | What it does |
|-------|--------------|
| `worktree` | Create git worktrees with the `wt` CLI following the canonical `~/wt/{repo}/{branch}` layout and herdr integration. |
