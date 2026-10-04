---
name: worker
description: Launch a worker, a new interactive Claude instance in its own git worktree and herdr space, primed with a HANDOFF.md and a standard boot prompt, for a Jira ticket, a GitHub PR, or a project sub-milestone. Use when the user asks to "create a worker", "launch a worker for <ticket|PR>", or when the project skill splits a milestone (`/worker --milestone <roadmap>#M<n>.<x>`).
---

# Launching a worker

`/worker <ticket-url|pr-url>` or `/worker --milestone <roadmap>#M<n>.<x>`

This session is the **coordinator**: it prepares and launches; it never edits
files in the worker's worktree and never changes its own cwd.

The pieces already exist; this skill only sequences them:

- worktree creation: the `worktree` skill (`wt pr` for a PR, `wt new` for a new branch)
- the handoff file: the `handoff` skill, with the worktree path as argument
- every herdr mechanic (panes, `agent start`, `agent prompt`): the `herdr`
  skill. Never write herdr command lines from memory.
- the lineage record (who launched whom, for `asagents`): `lineage.sh`, next
  to this file. Always through it, never by editing the JSON by hand.

## 1. Resolve the work

- Ticket URL: read it with `asdev:jira`. PR URL: `gh pr view <url> --json
  number,title,headRefName,headRefOid,baseRefName,body,author`.
  Milestone: read the roadmap and the `M<n>.<x>` section (see step 2).
- Repo (`REPO`, an absolute path to its main checkout):
  - with `--milestone`: the roadmap's `Repo:` line (a foreign repo's roadmap
    lives outside it), else the repo that contains the roadmap;
  - with a PR: the checkout of the PR's repository (`~/Developer/<repo>`);
  - otherwise the current repo; if the ticket does not say which repo, ask.
- Branch: a PR's `headRefName`; a sub-milestone's `Branch:`; otherwise follow
  the repo's branch naming (look at recent branches) and confirm it with the
  user if unsure.

Every command against the repo runs as `git -C "$REPO"` or inside a subshell
`(cd "$REPO" && ...)`, so the coordinator's own cwd never changes.

## 2. Milestone mode (only with `--milestone`)

`--milestone <roadmap>#M<n>.<x>` is explicit; it comes from `/project split`.
Before anything else check that the sub-milestone is launchable:

- the roadmap exists and has a `#### M<n>.<x>:` section with `Done when`
  criteria and a `Branch:`
- the user approved the split and granted the workers' Authority in the
  coordinator's conversation (at least local commits on its branch). If the
  grant is not there, ask; never assume it
- the coordinator's checkout is clean: the base is its committed `HEAD`

If anything is missing, stop: writing the sub-milestone is the coordinator's
job (`/project split`), not this skill's. `Depends on:` decides the base
branch in step 3.

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
  whatever the main checkout has checked out. The base is the `Depends on`
  sub-milestone's branch, else the coordinator's committed `HEAD` in milestone
  mode, else the trunk, `origin/<default branch>`:
  `git -C "$REPO" fetch origin && git -C "$REPO" branch --no-track <branch> <base>`,
  then `(cd "$REPO" && wt new <branch> -e none -t)` (no `-c`: the branch
  exists). `--no-track` matters: tracking the trunk would make `/ship` and
  `/asdev:pre-pr` treat the branch as published and `git push` it to the wrong
  name; its upstream is set on the first push.

Confirm the final path with `(cd "$REPO" && wt path <branch>)`.

## 4. Write the handoff (first launch only)

If `<worktree>/HANDOFF.md` already exists (relaunch), **do not touch it**: it
holds the worker's own state, dead ends and decisions, which this conversation
does not know. New context for a relaunch goes in the boot prompt.

Otherwise invoke the `handoff` skill with the worktree's absolute path. Fill it
from what this conversation knows: objective, decisions, verified findings,
constraints, and **Authority**:

- Without `--milestone`: only what the user granted explicitly in this conversation.
  Nothing granted means no commit, push, PR or rebase.
- Constraints always include the worker's lineage record,
  `~/.claude/agent-lineage/<name>.json`, and how to update it:
  `~/.claude/skills/worker/lineage.sh state <name> running|blocked-on-user|finished [text]`,
  so it survives a `/clear`.
- With `--milestone`: the grant the user gave when approving the split. The
  `Milestone:` line names the sub-milestone, the roadmap and the plan; the
  report path goes under Constraints; the Resume prompt is `/project next`.

## 5. Start the agent, record the lineage, send the boot prompt

Per the `herdr` skill: find the worktree's pane, `agent start --kind claude`
with a unique, meaningful name (e.g. `es-2567`; herdr wants a lowercase letter,
then `[a-z0-9_-]`, at most 32 characters), wait until idle.

Then, before the prompt, write the lineage record with the helper next to this
file (installed at `~/.claude/skills/worker/lineage.sh`):

```bash
~/.claude/skills/worker/lineage.sh launch <name> --pane <worker pane id> \
  --worktree <worktree path> --kind ticket|pr|milestone \
  --ref <ESHOP-123 | #8088 | M2.a> --title "<ticket, PR or sub-milestone title>"
```

It names this session `coord-<workspace label>` when it has no name yet,
waits up to 10 s for the worker's session id and writes
`~/.claude/agent-lineage/<name>.json`. On a relaunch it only updates the
worker's pane and session and sets the state back to `running`; the
coordinator and the task stay. If it fails, tell the user and go on: the
worker works without a record, it only shows up in `asagents` without lineage.

Then send the boot prompt.

Boot prompt (fill the placeholders; absolute paths only). Write it in Spanish,
the user's working language with workers. On a relaunch, add one line with
what changed since the previous launch:

```
Eres el worker de <TICKET o M<n>.<x>> en <worktree path>.
Lee entero <worktree path>/HANDOFF.md y haz lo que dice.
[--milestone] Corre /project next: trabajas solo en <M<n>.<x>> del roadmap <roadmap path>, y mantienes tu reporte en <reports>/<M<n>.<x>>.md (plantilla del skill project).
HANDOFF.md (y tu reporte) nunca se commitea.
Actúa solo dentro de la sección Authority del handoff; para lo demás, pregunta.
Antes de cualquier /clear, corre /handoff para dejar HANDOFF.md al día.
Tu registro de linaje es ~/.claude/agent-lineage/<name>.json; actualízalo solo con ~/.claude/skills/worker/lineage.sh state <name> ...: blocked-on-user "<pregunta>" cuando me dejes una pregunta, running al retomar tras mi respuesta, finished "<resumen de una línea>" al terminar.
Cuando termines, responde solo con la ruta de tu reporte o un resumen de una línea.
```

## 6. Report to the user

Workspace, pane, agent name, worktree path, the handoff path, the lineage
record, and the Authority granted. If the user wants the worker watched, follow the `herdr` skill for a
background wait; otherwise stop.
