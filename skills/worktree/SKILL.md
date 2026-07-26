---
name: worktree
description: Create git worktrees with the `wt` CLI so they follow the user's conventions (canonical path ~/wt/{repo}/{branch}, automatic herdr integration). Use whenever the user asks to create, add, make, or set up a git worktree for a branch.
---

# Creating git worktrees

The user manages worktrees with the `wt` CLI (a fork of johnlindquist/worktree,
repo `asumaran/worktree-cli`). It is the single source of truth for where
worktrees live and how they integrate with the rest of the toolchain. When asked
to create a worktree, **always use `wt`; never run `git worktree add` directly** —
a raw `git worktree add` lands in an arbitrary path and skips the herdr
integration.

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

## After creating

To work inside the new worktree, resolve its path and `cd` there:

```bash
cd "$(wt path <branch>)"
```

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
directly. If you ever must call the `herdr` CLI against a worktree yourself, note
that `herdr worktree ...` does not inherit the caller's cwd and must start from
the main repo root: pass `--cwd "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"`.
