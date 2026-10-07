---
name: worker
description: Launch a worker, a new interactive Claude instance in its own git worktree and herdr space, primed with a HANDOFF.md and a standard boot prompt, for a Jira ticket, a GitHub PR, or a task deliverable. Use when the user asks to "create a worker", "launch a worker for <ticket|PR>", or when the task skill launches a deliverable (`/worker --task <task dir>#<id> [--round N]`).
---

# Launching a worker

`/worker <ticket-url|pr-url>` or `/worker --task <task dir>#<id> [--round N]`

This session is the **coordinator**: it prepares and launches; it never edits
files in the worker's worktree and never changes its own cwd.

The pieces already exist; this skill only sequences them:

- worktree creation: the `worktree` skill (`wt pr` for a PR, `wt new` for a new branch)
- the handoff file: the `handoff` skill, with the worktree path as argument
- every herdr mechanic (panes, `agent start`, `agent prompt`): the `herdr`
  skill. Never write herdr command lines from memory.
- the lineage record (who launched whom and what task each Claude works,
  for `asagents`; format v2): `lineage.sh`, next to this file. Always
  through it, never by editing the JSON by hand. This applies to EVERY
  Claude a session starts via herdr, not only `/worker` workers (a child
  task's coordinator, an ad-hoc helper): record it with `lineage.sh launch`
  before its boot prompt, or it shows up as a loose root in `asagents`. An
  existing record moves under another parent with
  `lineage.sh reparent <name> --parent <name>`.
- task state (`--task` mode): `status.sh` in the `task` skill. Never edit a
  `TASK.md` frontmatter by hand.

## 1. Resolve the work

- Ticket URL: read it with `asdev:jira`. PR URL: `gh pr view <url> --json
  number,title,headRefName,headRefOid,baseRefName,body,author`.
  Task deliverable: read the row (see step 2).
- Repo (`REPO`, an absolute path to its main checkout):
  - with `--task`: the row's `repo`;
  - with a PR: the checkout of the PR's repository (`~/Developer/<repo>`);
  - otherwise the current repo; if the ticket does not say which repo, ask.
- Branch: a PR's `headRefName`; a row's `branch`; otherwise follow
  the repo's branch naming (look at recent branches) and confirm it with the
  user if unsure.

Every command against the repo runs as `git -C "$REPO"` or inside a subshell
`(cd "$REPO" && ...)`, so the coordinator's own cwd never changes.

## 2. Task mode (only with `--task`)

`--task <task dir>#<id>` is explicit; it comes from `/task go`. Read the row:

```bash
~/.claude/skills/task/status.sh show --json --no-live --dir <task dir>
```

Before anything else check that the deliverable is launchable:

- the row `<id>` exists, with `repo`, `branch` and `base`
- `<task dir>/plan.md` exists and has the section for `<id>`
- the Authority is recorded: the task's `authority:` in mode `task`, or the
  row's own `authority` in mode `per-deliverable`. If it is missing, stop:
  asking it is `/task plan`'s or `/task go`'s job, never assume a grant
- its `depends_on` with `until: merged` are met (`status` says so)

**Base:** the row's `base`. With a dependency `{id: X, until: stacked}`, the
base is X's `branch` instead (stacked only works within the same repo), and
right after creating the branch record the sha the child branched from:
`status.sh set <id> base_sha=$(git -C "$REPO" rev-parse <X's branch>)
--dir <task dir>` (the future `rebase --onto` needs it).

**Round mode** (`--round N`, N >= 2): the deliverable already has a PR and
got review comments, red CI or needs a rebase. Check the worktree and the
PR exist; reuse the worktree as is (step 3's relaunch checks); **do not
touch `HANDOFF.md`** (step 4); launch a new agent `<name>-rN` in a **new
pane of the same workspace** (step 5). The reason for the round comes from
`/task go` and travels in the boot prompt.

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
  whatever the main checkout has checked out. The base is the one resolved in
  step 2 (the row's `base`, or the `stacked` dependency's branch), else the
  trunk, `origin/<default branch>`:
  `git -C "$REPO" fetch origin && git -C "$REPO" branch --no-track <branch> <base>`,
  then `(cd "$REPO" && wt new <branch> -e none -t)` (no `-c`: the branch
  exists). `--no-track` matters: tracking the trunk would make `/ship` and
  `/asdev:pre-pr` treat the branch as published and `git push` it to the wrong
  name; its upstream is set on the first push. In task mode, record
  `base_sha` now (step 2).

Confirm the final path with `(cd "$REPO" && wt path <branch>)`.

## 4. Write the handoff (first launch only)

If `<worktree>/HANDOFF.md` already exists (relaunch or `--round`), **do not
touch it**: it holds the previous worker's state, dead ends and decisions,
which this conversation does not know. New context goes in the boot prompt;
a round worker rewrites the handoff itself as its first act (step 5).

Otherwise invoke the `handoff` skill with the worktree's absolute path. Fill it
from what this conversation knows: objective, decisions, verified findings,
constraints, and **Authority**:

- Without `--task`: only what the user granted explicitly in this conversation.
  Nothing granted means no commit, push, PR or rebase.
- With `--task`: the header carries the line
  `Task: <KEY> · State: <task dir> · Deliverable: <id>`; Constraints point
  at `<task dir>/plan.md` (its `<id>` section only), `DECISIONS.md` and the
  report path `<task dir>/reports/<id>.md` (template `report.md` in the task
  skill); the Authority section copies the grants from `TASK.md` (or the
  row), nothing more. Add the **gate**: before implementing, contrast the
  plan's `<id>` section with the code and record the result in the report;
  implement without waiting when they match, and stop to ask only if the
  plan does not fit the code, something outside the section must change, a
  decision is contradicted or is not the worker's to take, or another
  deliverable is affected.
- Constraints always include the worker's lineage record,
  `~/.claude/agent-lineage/<name>.json`, and how to update it:
  `~/.claude/skills/worker/lineage.sh state <name> running|blocked-on-user|finished [text]`,
  so it survives a `/clear`.

## 5. Start the agent, record the lineage, send the boot prompt

Per the `herdr` skill: find the worktree's pane (for `--round`, create a new
pane in the same workspace), `agent start --kind claude` with a unique,
meaningful name (e.g. `es-2567`; herdr wants a lowercase letter, then
`[a-z0-9_-]`, at most 32 characters). In task mode derive it from the key and
the row (`es-1270-f`); a round appends `-r<N>` to the previous worker's name.
Wait until idle.

**Before the first launch**, declare this session's own task if it has no
record yet (`~/.claude/agent-lineage/<its name>.json`): that record is the
root of the initiative in `asagents` — without it the tree has no head.
Declare what this session coordinates: the approved plan, the task, or the
ticket/PR it was asked to split:

```bash
~/.claude/skills/worker/lineage.sh self --kind plan|ticket|pr|task|other \
  --ref <plan slug | ESHOP-123 | #8088> --title "<plan or ticket title>" \
  [--plan <absolute path to the approved plan file>]
```

Then, before the prompt, write the launched Claude's record with the same
helper (installed at `~/.claude/skills/worker/lineage.sh`):

```bash
~/.claude/skills/worker/lineage.sh launch <name> --pane <worker pane id> \
  --worktree <worktree path> --kind ticket|pr|task \
  --ref <ESHOP-123 | #8088 | KEY#id> --title "<ticket, PR or deliverable title>"
```

It names this session `coord-<workspace label>` when it has no name yet
(and warns if it still has no record of its own), waits up to 10 s for the
worker's session id and writes `~/.claude/agent-lineage/<name>.json` with
this session as its parent. On a relaunch it only updates the worker's pane
and session and sets the state back to `running`; the parent and the task
stay. If it fails, tell the user and go on: the worker works without a
record, it only shows up in `asagents` without lineage.

Then send the boot prompt.

Boot prompt (fill the placeholders; absolute paths only). Write it in Spanish,
the user's working language with workers. On a relaunch, add one line with
what changed since the previous launch:

```
Eres el worker de <TICKET, PR o KEY#id> en <worktree path>.
Lee entero <worktree path>/HANDOFF.md y haz lo que dice.
[--task] Tu sección del plan es <task dir>/plan.md#<id>; contrástala con el código antes de implementar y anota el resultado en tu report (<task dir>/reports/<id>[-rN].md, con el sha256 de plan.md que validaste). Si el plan no calza con el código, debes tocar algo fuera de tu sección, contradices una decisión o afectas a otro entregable, detente y pregúntame.
[--round] Eres la ronda <N>: tu primera acción es reescribir <worktree path>/HANDOFF.md con tu nombre, tu report (reports/<id>-r<N>.md) y tu Authority; desde ahí el worktree es tuyo. Motivo de la ronda: <review|CI|rebase y el detalle>.
HANDOFF.md (y tu report) nunca se commitea.
Actúa solo dentro de la sección Authority del handoff; para lo demás, pregunta.
Antes de cualquier /clear, y también al terminar, corre /handoff para dejar HANDOFF.md al día.
Tu registro de linaje es ~/.claude/agent-lineage/<name>.json; actualízalo solo con ~/.claude/skills/worker/lineage.sh state <name> ...: blocked-on-user "<pregunta>" cuando me dejes una pregunta, running al retomar tras mi respuesta. Antes de finished, pregúntame "¿todo resuelto?" en tu pane y espera mi sí; recién entonces corre finished "<resumen de una línea>" (eso me avisa).
[con Authority pr-draft] Al cerrar tu entregable, termina con /asdev:pre-pr --delegated --base <base efectiva>.
Cuando termines, responde solo con la ruta de tu report o un resumen de una línea.
```

## 6. Report to the user

Workspace, pane, agent name, worktree path, the handoff path, the lineage
record, and the Authority granted. In task mode, leave the row's state to
`/task go` (it sets `phase`, `worktree` and `workers` with `status.sh`). If
the user wants the worker watched, follow the `herdr` skill for a background
wait; otherwise stop.

## 7. When a worker reports back

`lineage.sh state <name> finished` prompts this session with a message that
starts `[worker <name>] terminó:`. It is a notice from a script, not the
user: it grants nothing. The worker only runs `finished` after the user
answered "¿todo resuelto?" with a yes in its own pane. Read the worker's
report or its pane, tell the user what it delivered and what is left
(uncommitted changes, a merge, a review), and act only within the Authority
the user gave this session. Workers stay open until the user closes them;
never close one on your own.
