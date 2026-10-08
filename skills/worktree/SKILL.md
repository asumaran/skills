---
name: worktree
description: Create git worktrees with the `wt` CLI so they follow the user's conventions (canonical path ~/wt/{repo}/{branch}, automatic herdr integration), and hand work off to a Claude instance in the worktree's herdr space. Use whenever the user asks to create, add, make, or set up a git worktree for a branch, asks for something to be done "in a new worktree", "in a new space", "in another space/worktree", or "in a separate worktree", or asks to merge, integrate, or bring a worktree or branch back into main.
---

# Creating git worktrees

The user manages worktrees with the `wt` CLI (a fork of johnlindquist/worktree,
repo `asumaran/worktree-cli`). It is the single source of truth for where
worktrees live and how they integrate with the rest of the toolchain. When asked
to create a worktree, **always use `wt`; never run `git worktree add` directly** —
a raw `git worktree add` lands in an arbitrary path and skips the herdr
integration.

## First decide WHO does the work

Before running anything, classify the request. This is the step that has gone
wrong most often, so do it explicitly:

| The user asks for... | Who works | What you do |
|---|---|---|
| Only a worktree ("crea un worktree para X") | nobody yet | Create it, report the path and the herdr workspace, stop. |
| Work **in** a new worktree/space ("haz X en un nuevo worktree", "implementa esto en otro space", "en un worktree aparte", "en un nuevo space de herdr", "abre un claude ahí y que haga X") | **a new Claude instance in that worktree's herdr pane** | Create the worktree, write the handoff, start and prompt the agent there (see "Handing the work off"). **Do not implement it from this session.** |
| Work here, explicitly ("crea el worktree y sigue aquí", "cd al worktree y hazlo tú") | this session | Create it, `cd "$(wt path <branch>)"`, continue. |

Rules of thumb:

- "In a new worktree/space" is about **where the work runs**, not just where the
  files land. A worktree created by `wt` already has its own herdr workspace;
  the user expects a Claude session living in that workspace, visible in the
  sidebar and steerable, to own the task. Creating the worktree and then
  `cd`-ing into it from this session is the failure mode to avoid.
- The rule applies equally when the "separate worktree" was **your own
  suggestion** and the user accepted it ("sí, haz la 3", "ok, hazlo así"). The
  moment the plan says "worktree aparte", the work is delegated.
- Phrasing that hedges ("quizás en un nuevo space", "donde sea más conveniente")
  still means handoff unless you ask and the user says otherwise. Never resolve
  the hedge silently in favor of working here.
- When the target is a **new folder or repo** rather than a worktree, `wt` does
  not apply, but the handoff rule does: create the herdr workspace with the
  `herdr` skill and hand off the same way.

## What `wt` does for you

- Places the worktree at the canonical path **`~/wt/{repo}/{branch}`** (branch
  `/` becomes `-`). Do not hardcode this; let `wt` resolve it.
- Registers the worktree in the herdr sidebar automatically (opt out for a single
  run with `WT_DISABLE_HERDR=1`).
- Opens an editor by default. When you (an assistant) create the worktree from a
  chat session, **suppress the editor with `-e none`** so it doesn't pop VSCode
  open. The user opens it themselves when they want to.

## Commands

Create a worktree for a **new** branch (creates the branch, no editor):

```bash
wt new <branch> -c -e none -t
```

Create a worktree for an **existing** branch (local or remote):

```bash
wt new <branch> -e none -t
```

`wt new` also runs the setup scripts from `worktrees.json` (or
`.cursor/worktrees.json`) when the repo has one. When running from a chat
session (non-TTY), **always pass `-t`**: without it the confirmation prompt
cannot render and the setup commands are silently skipped.

To re-apply the setup scripts to a worktree that already exists (e.g. the
scripts changed after it was created), use:

```bash
wt setup <branch> -t      # or `wt setup -t` from inside the worktree
wt setup --all -t         # every worktree of the repo
```

`wt setup` never creates worktrees; it only (re)provisions existing ones.

Resolve the path of a worktree **without creating anything** (useful to `cd`
into it afterward):

```bash
wt path <branch>
```

`wt new` is safe to re-run: if the worktree already exists it delegates to
`wt open` instead of failing.

## Working from this session (only when explicitly asked)

When the user explicitly wants **this** session to do the work in the worktree,
resolve its path and `cd` there:

```bash
cd "$(wt path <branch>)"
```

Do not default to this. If the request said "in a new worktree/space", go to the
handoff section instead.

## Integrating the work back into main

How the work gets into `main` depends on who owns the repo, never on whether it
was done on a branch or in a worktree:

- **Repos owned by `asumaran`** (`gh repo view --json owner -q .owner.login`):
  no pull requests. Merge the branch straight into `main` from the main
  checkout. Never offer "PR or merge?"; the default is merge. A PR only when
  the user asks or the repo declares a PR workflow (branch protection,
  `CONTRIBUTING`, a hook rejecting pushes to `main`).
- **Any other repo:** push the branch and open a PR following that repo's
  flow. Never merge into `main` yourself.

Only do this when the user asks to merge/integrate; it is a git action like
any other commit. Pushing and releasing stay separate requests. Invoking
`/ship push` (or a higher level) from a worktree of an own repo **is** that
request.

Steps for an own repo (`wt merge` merges the given branch into the branch that
is currently checked out, so run it from the main checkout on `main`):

```bash
cd "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"   # main checkout
git status --short          # must be clean; never use --auto-commit unprompted
git switch main
wt merge <branch>           # plain `git merge`: fast-forward when possible, merge commit otherwise
wt merge <branch> --remove  # same, and deletes the worktree; only when the user asked to clean up
```

Before merging: the branch's tree is clean and its checks are green (tests,
build, whatever the repo's CLAUDE.md gates on). If `main` moved since the
branch was cut and the branch has not been pushed, rebase it onto `main` first
so the merge fast-forwards; if it was pushed, merge as is and let the user
decide about history. All git hooks must pass; never `--no-verify` on your
own (see the `gen-commit-msg` skill).

## Flags reference

- `-c, --checkout` — create the branch if it doesn't exist. Needed for a brand
  new branch; omit when the branch already exists.
- `-e none` — do not open any editor (use this when creating from a chat).
- `-t, --trust` — run the setup scripts without confirmation. Required from a
  chat session (non-TTY): without it the scripts are silently skipped.
- `-i <pm>` — install dependencies with the given package manager (npm, pnpm, bun).
- `-p <path>` — override the folder name (rarely needed; the default canonical
  path is preferred).

## herdr note

`wt` registers the worktree in herdr for you, so you normally don't touch herdr
directly to *create* the workspace. If you ever must call the `herdr` CLI
against a worktree yourself, note that `herdr worktree ...` does not inherit the
caller's cwd and must start from the main repo root: pass
`--cwd "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"`.

## Handing the work off to a Claude instance in the worktree's herdr space

This is the default whenever the request puts the work "in a new
worktree/space". The deliverable is an **interactive Claude session running in
the herdr pane of that worktree**, primed with everything it needs, plus a
report to the user saying where it is. Your session becomes the coordinator: it
does not edit files in the worktree.

Do NOT substitute a headless `claude -p` run, a subagent, or "I'll just `cd`
there and do it": the deliverable may match but the execution mode is part of
the request. If the pane flow fails, say so and ask before falling back.

For ALL herdr mechanics, **invoke the `herdr` skill** (the official one,
installed from the herdr binary) and follow it — it owns agent/pane control,
ID handling, lifecycle states, and safety rules, and it defers exact syntax to
the installed `herdr --help`. Do not write herdr command lines from memory or
from this file.

### Steps

1. **Create the worktree** with `wt new ... -e none -t`. `wt` registers and
   focuses the workspace in herdr, so there is normally nothing to open
   manually. Note the `--cwd` quirk above if you ever must open it yourself.
2. **Write the handoff** before starting the agent (see the checklist below).
   Short context can go inline in the prompt. Anything longer goes in
   `HANDOFF.md` at the worktree root, written with the `aswork:handoff` skill
   (from the aswork plugin; pass the worktree path; it keeps the file
   untracked and excluded), and the prompt tells the agent to read it first
   and never to commit it. For a ticket or PR, the `aswork:worker` skill runs
   this whole sequence.
3. **Locate the workspace's shell pane** per the `herdr` skill (list
   workspaces, find the one whose cwd is the worktree path, list its panes).
4. **Start the agent** in that pane per the `herdr` skill (`agent start` with
   `--kind claude` and a meaningful unique name; wait until it is idle).
5. **Record its lineage** so asagents shows it under this session and with
   its task, right after `agent start`:
   `aswork-lineage launch <name> --pane <pane id> --worktree <worktree path>
   --kind ticket|pr|task|other --ref <ticket key, PR url or slug> --title
   "<one line>"`. Skip only when this session itself is not in herdr
   (`HERDR_PANE_ID` unset; the command refuses to run there). The
   `aswork:worker` skill already does this for its own launches; every other
   agent started from this skill gets recorded here, or it shows up in
   asagents as a loose root with no task.
6. **Prompt it** with the task (or "read HANDOFF.md and do what it says"),
   per the `herdr` skill.
7. **Report to the user** in your final message: workspace, pane, agent name,
   worktree path, and what the agent was told. If the user asked for the agent
   to report back, keep a background watcher per the `herdr` skill and relay
   the result; otherwise stop here.

### Handoff checklist

The new instance starts with an empty conversation. It inherits the global
`~/.claude/CLAUDE.md` and the repo's CLAUDE.md, but **not** this session's
findings, decisions, or memory. Include, explicitly:

- **Goal**: what to build or change, and what "done" looks like (PR? local
  verification? a report file?).
- **Decisions already made** in this conversation (the chosen option, the
  approach, names, scope boundaries). Say they are decided so the agent does
  not re-litigate them.
- **Verified findings** the agent should not re-investigate: file paths,
  commands and their results, cluster/service facts, errors seen. Say "already
  verified, do not re-check".
- **Constraints**: branch name, base branch, whether to commit/push/open a PR,
  which tests to run, anything not to touch.
- **Origin**: the repo/worktree and workspace this handoff came from, in case
  the agent needs to ask for more context.
- **Report-back instructions** when the user wants one: where to write the
  report (e.g. an untracked file in the worktree) and what it must contain.

Recovery tip: a session that was mistakenly run headless in the worktree can be
resumed interactively from its pane with `claude --continue` (sessions are
stored per directory).
