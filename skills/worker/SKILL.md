---
name: worker
description: Launch a worker, a new interactive Claude instance in its own git worktree and herdr space, primed with a HANDOFF.md and a standard boot prompt, for a Jira ticket or GitHub PR. Use when the user asks to "create a worker", "launch a worker for <ticket|PR>", or, as coordinator of a harness run, to start a worker for a ticket.
---

# Launching a worker

`/worker <ticket-url|pr-url> [--run <run-dir>]`

This session is the **coordinator**: it prepares and launches; it never edits
files in the worker's worktree and never changes its own cwd.

The pieces already exist; this skill only sequences them:

- worktree creation: the `worktree` skill (`wt pr` for a PR, `wt new` for a new branch)
- the handoff file: the `handoff` skill, with the worktree path as argument
- every herdr mechanic (panes, `agent start`, `agent prompt`): the `herdr`
  skill. Never write herdr command lines from memory.

## 1. Resolve the work

- Ticket URL: read it with `asdev:jira`. PR URL: `gh pr view <url> --json
  number,title,headRefName,headRefOid,baseRefName,body,author`.
- Repo (`REPO`, an absolute path to its main checkout):
  - with `--run`: `REPO` from `<run-dir>/run.env`;
  - with a PR: the checkout of the PR's repository (`~/Developer/<repo>`);
  - otherwise the current repo; if the ticket does not say which repo, ask.
- Branch: a PR's `headRefName`; otherwise follow the repo's branch naming (look
  at recent branches) and confirm it with the user if unsure.

Every command against the repo runs as `git -C "$REPO"` or inside a subshell
`(cd "$REPO" && ...)`, so the coordinator's own cwd never changes.

## 2. Run mode (only with `--run`)

`--run <run-dir>` is explicit. Never infer a run from directories that happen
to exist under `~/.claude/harness/`.

With `--run`, before anything else check that the run is launchable, as the
harness entry check requires (`HARNESS-SPEC.md`, "Entry check" and "launch"):

- `<run-dir>/run.env`, `<run-dir>/PLAN.md` and `<run-dir>/common.md` exist
- the worker is listed in `PLAN.md` frontmatter (`workers:`), and
  `<run-dir>/briefs/<TICKET>.md` exists and is not empty

If anything is missing, stop: designing the run and writing the brief is the
coordinator's job before launching, not this skill's. Read the worker's
`depends_on` from `PLAN.md`; it decides the base branch in step 3.

## 3. Create the worktree (or reuse it)

First look for an existing one. `wt path` only computes a path (and
`feature/x` and `feature-x` map to the same one), so an existing directory is
not proof. It is a **relaunch** only if all of these hold:

- `git -C "$REPO" worktree list --porcelain` lists that path,
- its branch (`git -C <path> symbolic-ref --short HEAD`) is exactly `<branch>`,
- with a PR, the worktree's HEAD contains **that PR's** head. Fetch the PR
  ref itself (not a same-named branch, which in a fork PR can be other code)
  from the remote whose URL is the PR's repository, check it is the PR's
  `headRefOid`, then check ancestry:
  `git -C <path> fetch <remote> "refs/pull/<number>/head"`,
  `test "$(git -C <path> rev-parse FETCH_HEAD)" = "<headRefOid>"`,
  `git -C <path> merge-base --is-ancestor FETCH_HEAD HEAD`. Local work on top
  of it is the worker's and stays.

Then reuse the worktree as is. If the path exists but any check fails, stop and
tell the user: something else lives there.

Otherwise, per the `worktree` skill, from `REPO` in a subshell:

- **PR:** `(cd "$REPO" && wt pr <pr-url> -e none -s -t)`. `wt pr` fetches the
  PR's branch; never use `wt new` for a PR (it would branch off whatever is
  checked out when the branch is not cached locally). Then check the worktree
  HEAD equals the PR's `headRefOid`; if not, stop.
- **New branch:** create the branch first from an explicit base, never from
  whatever the main checkout has checked out. The base is the `depends_on`
  worker's branch in run mode, else the trunk, `origin/<default branch>`:
  `git -C "$REPO" fetch origin && git -C "$REPO" branch --no-track <branch> <base>`,
  then `(cd "$REPO" && wt new <branch> -e none -t)` (no `-c`: the branch
  exists). `--no-track` matters: tracking the trunk would make `/ship` and
  `/asdev:pre-pr` treat the branch as published and `git push` it to the wrong
  name; its upstream is set on the first push.

Confirm the final path with `(cd "$REPO" && wt path <branch>)`.

## 4. Write the handoff (first launch only)

If `<worktree>/HANDOFF.md` already exists (relaunch), **do not touch it**: it
holds the worker's own state, dead ends and decisions, which this conversation
does not know. New context for a relaunch goes in the boot prompt (run mode: a
new `briefs/<TICKET>-followup-N.md`).

Otherwise invoke the `handoff` skill with the worktree's absolute path. Fill it
from what this conversation knows: objective, decisions, verified findings,
constraints, and **Authority**:

- Without `--run`: only what the user granted explicitly in this conversation.
  Nothing granted means no commit, push, PR or rebase.
- With `--run`: what the run's `common.md` grants; list the run files under
  Constraints by absolute path.

## 5. Start the agent and send the boot prompt

Per the `herdr` skill: find the worktree's pane, `agent start --kind claude`
with a unique, meaningful name (e.g. `es-2567`), wait until idle, then prompt.

Boot prompt (fill the placeholders; absolute paths only). Write it in Spanish,
the user's working language with workers. On a relaunch, add one line with
what changed since the previous launch (or the follow-up brief's path):

```
Eres el worker de <TICKET> en <worktree path>.
Lee entero <worktree path>/HANDOFF.md y haz lo que dice.
[--run] Lee también <run>/common.md, tu brief <run>/briefs/<TICKET>.md, y escribe tu reporte en <run>/reports/<TICKET>.md.
HANDOFF.md (y cualquier archivo del run) nunca se commitea.
Actúa solo dentro de la sección Authority del handoff; para lo demás, pregunta.
Antes de cualquier /clear, corre /handoff para dejar HANDOFF.md al día.
Cuando termines, responde solo con la ruta de tu reporte o un resumen de una línea.
```

## 6. Report to the user

Workspace, pane, agent name, worktree path, the handoff path, and the Authority
granted. If the user wants the worker watched, follow the `herdr` skill for a
background wait; otherwise stop.
