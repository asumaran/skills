---
name: task
description: Run any assignment as a task, a node with optional parent and children; a Jira ticket, an idea without a ticket, or a personal project. State lives in ~/.claude/work/<KEY>/ (TASK.md frontmatter, plan.md, numbered decisions, reports) and is operated with status.sh, never by editing the YAML by hand. Use when the user says /task, "new task", "task status", "what is left on <KEY>", "launch the deliverables", "promote <id>", or asks to adopt an in-flight ticket.
---

# Task: every assignment is a node

`/task <new|plan|go|status|resume|decide|close|promote|link|gate|ack|new-repo> [args]`
Bare `/task` is `/task status`.

A **task** is one assignment: a Jira ticket, an idea without a ticket, or a
personal project. It can have a parent and children. A **deliverable** is a
row in its `deliverables:` (one branch, one PR); a deliverable that needs its
own plan or several PRs is **promoted** to a child task. The pieces are the
existing skills: `worker` launches a deliverable (`--task`), `handoff` writes
resume points, `worktree`/`wt merge` integrates, `grilling` and
`asdev:second-opinion` harden plans, `asdev:jira` reads and creates tickets.

## State

Always `~/.claude/work/<KEY>/` (the **task directory**; the coordinator's cwd,
no code in it):

```
TASK.md          # YAML frontmatter (scripts read it) + prose: Goal, Done when,
                 # Open questions, Out of scope, Risks
DECISIONS.md     # numbered, append-only, marker <!-- next: D<n> -->
HANDOFF.md       # the coordinator's resume point (handoff skill)
plan.md          # the approved plan, one section per deliverable
hardening.md     # grill + second opinion findings and how each was resolved
reports/<id>.md  # one per deliverable or round (<id>-r2.md), templates/report.md
tickets/         # children specs + keys.json
.status/         # PR snapshots (ack)
prs/, messages/, verify/, archive/    # on demand
```

With `home: repo` (a root task in one of the user's own repos), `TASK.md` and
`DECISIONS.md` are **symlinks** from the task directory into the repo's
`docs/`, so they are versioned and the scanners still find them under
`work/`. `status.py` writes through the symlink (realpath).

**Every state operation goes through `status.sh`** (next to this file;
installed at `~/.claude/skills/task/status.sh`): `show [--json] [--no-live]`,
`add-row`, `set`, `set-root`, `promote`, `ack`, `gate`. Never edit the
frontmatter by hand. Row `k=v` values parse as JSON when possible:
`status.sh set F depends_on='[{"id":"B","until":"merged"}]'`.

The `key:` is the Jira KEY, or a confirmed `<repo>-<words>` slug. It is also
the lineage `ref` and the branch name's stem. `aliases:` lets a task be found
by slug and by KEY after `/task link`.

Templates: `templates/TASK.md`, `templates/DECISIONS.md`,
`templates/report.md` next to this file. Paths in state files are absolute,
never `~`.

## new <url|KEY|"idea">

1. **Identity.** A Jira URL or KEY: read the ticket with `asdev:jira` (a URL
   outside a git repo uses its `jira-key` mode), including `parent`,
   children by JQL, `issuelinks` and `fixVersions`. Free text: propose a
   `<repo>-<words>` slug and create nothing until the user confirms it.
2. **Adoption.** If `~/.claude/harness/<key, lowercased>/` exists, offer to
   adopt: set `legacy: <that path>` in the frontmatter, rebuild the
   deliverables from the **live state** (`gh pr view`, branches, worktrees),
   never from the old docs' text, and confirm row by row with the user.
   Nothing is moved or archived; old absolute references keep working. No
   new plan is launched automatically.
3. **Create the state**, idempotent (a second run on the same ticket changes
   nothing): `mkdir -p ~/.claude/work/<KEY>`, `TASK.md` and `DECISIONS.md`
   from the templates, then `status.sh set-root` for key, title, link, stack,
   parent. Fill the body (Goal, Done when, Open questions) from the ticket
   with the user. With `home: repo`: create `docs/TASK.md` and
   `docs/DECISIONS.md` in the repo and symlink them from the task directory.
4. **Hand off to the coordinator.** Open a herdr space with cwd at the task
   directory (`herdr` skill), start a Claude there, and prompt it with
   `/task plan` (plus the context). Lineage: every Claude a session starts
   via herdr is recorded, not only `/worker` workers.
   - Task **with `parent:`** (a promoted child): before the prompt, the
     launching session (the parent task's coordinator) records the new
     coordinator under itself: `~/.claude/skills/worker/lineage.sh launch
     <name> --pane <id> --worktree <task dir> --kind task --ref <child KEY>
     --title "<title>"`. The child coordinator's own `self` keeps that
     parent; it must not float as a root.
   - Task **without `parent:`**: a new initiative; no launch record. The
     coordinator registers itself as the root:
     `~/.claude/skills/worker/lineage.sh self --kind ticket|task|other
     --ref <KEY> --title "<title>"`.
   A record under the wrong parent is fixed with `lineage.sh reparent
   <name> --parent <name>`, never by editing the JSON. The session that
   invoked `/task new` continues with its own work.

## plan [--no-codex]

The coordinator's cycle; the full contract is in `references/cycle.md`:
plan mode, then `grilling` to a shared understanding, then
`asdev:second-opinion` (skipped only by `--no-codex`), then approval. On
approval: write `plan.md` and `hardening.md`, record the decisions with
`/task decide`, fill `deliverables:` with `status.sh add-row`, and ask the
Authority (mode `task` or `per-deliverable`; grants `commit`, `push`,
`pr-draft`, `pr-update`, `rebase`, `merge-main` only in own repos;
`pr-draft` requires `commit` and `push`). Store it with `status.sh set-root
authority=...`.

## go [id|all]

For each deliverable that `status` says is launchable (its `depends_on` are
met; `stacked` deps never block, they set the base):

1. **Children in Jira first.** A row with `child: pending` needs its ticket:
   set `phase=creating-child`, write the spec under `tickets/`, run
   `asdev:jira` Flujo C (`create-children.py`: dry-run, the user confirms the
   exact list, `--apply`), then `status.sh set <id> child=<new KEY>
   phase=planned`.
2. **Launch.** Set `phase=launching`, then invoke the `worker` skill with
   `--task <task dir>#<id>`. The worker skill creates the worktree from the
   row (`base`, or the `stacked` dependency's branch), writes the handoff
   with the `Task:` line and the Authority, starts the agent and records the
   lineage. Then `status.sh set <id> phase=implementing
   worktree=<path> workers='["<name>"]'`.
3. **Rounds.** A row already in PR gets a **new worker in the same
   worktree**: `--task <dir>#<id> --round <N>`. The reason is what `status`
   detected (review, red CI, rebase); if it detected nothing, ask the user
   for it and pass it in the boot prompt. Append the round worker to
   `workers`, then `status.sh ack <id>` (launching the round attends the
   events).

In `per-deliverable` Authority mode, ask the grants for this deliverable now
(same multiselect as in `plan`) and store them on the row.

Every step is idempotent and the row holds the intermediate phase
(`creating-child`, `launching`) before each effect; `status` proposes how to
complete an interrupted one.

## status (or bare /task)

Read-only. Run `status.sh show` (`--json` for machine use): it detects the
task from the cwd (the task directory, or a worktree whose branch or path is
in some row), prints the rows with live PR state (`gh pr view`: state, draft,
checks, review decision, new comments vs the `.status/` snapshot), the
reports, the lineage states, a next action per row, and the consistency
check (worktree without worker, worker without row, promote half-done, stale
plan sha). It never writes, not even snapshots. When rows have `child`
tickets, add their Jira status with `asdev:jira`. New PR events stay "new"
until a round is launched or `/task ack <id>` is run.

## resume

The retake contract of the coordinator, and the resume prompt of every task
handoff. In order:

1. `~/.claude/skills/worker/lineage.sh self --kind <kind> --ref <KEY> --title
   "<title>"`: refreshes this session's record and **reparents** its
   children's records (a `/clear` changed the session id; without this,
   workers' finish notices miss).
2. Load, whole: `HANDOFF.md`, `TASK.md` (frontmatter and body), every
   decision with Status `taken` in full, `plan.md`, and the reports.
3. Run `status.sh show` and continue from the handoff's Next.

## decide

Numbered decisions in `DECISIONS.md`; format and rules in
`references/cycle.md`. Ask for the why and the rejected alternative if
missing; supersede, never delete.

## close [id]

Verify each `Done when` criterion **now**, with the command run and its
output; "tests pass" with no command is not evidence. In eshop, separate
**integrated** (commit ancestry verified with `git merge-base --is-ancestor`
against release/master, accounting for squashes by PR title) from
**deployed** (version visible in each environment, confirmed by the user);
the process is `~/.claude/eshop-release-process.md`. A deliverable without a
PR in an own repo was integrated by its worker (`merge-main` Authority, `wt
merge` per the `worktree` skill); check the merge sha in its report. A
failing criterion stops the close. Then `status.sh set <id> phase=merged`
(or `released`). Never transition Jira.

## promote <id>

`status.sh promote <id>`: idempotent, fixed order (create
`work/<child key>/` with `parent:`, then point the row's `task:` at it). A
row without a ticket promotes as `<KEY>-<id>`. Then plan the child task as
its own task (`/task plan` in its own coordinator, launched per `new`
step 4: this coordinator records it with `lineage.sh launch`, so the child
hangs under the parent's coordinator in `asagents`). `status` shows the
parent row as the child's least-advanced deliverable.

## link <KEY>

For a task created by slug that got a ticket later: `status.sh set-root
link=<url> stack=<stack> aliases='["<KEY>"]'`. The directory is not renamed;
the task resolves by slug or by KEY.

## gate <id> <gate> done

`status.sh gate <id> "<gate name>" done` marks a human or external condition
(deploys, preflight matrices) the user verified. Gates are defined on the
row at plan time (`gates='[{"name":"...","done":false}]'`) and `status`
shows the pending ones as the next action.

## ack <id>

`status.sh ack <id>`: snapshot the row's current PR state into `.status/`;
its new events are attended without launching a round.

## new-repo <name>

The contract of the old `project new`, then a task on top:

1. Check the `herdr` skill can see the server **before any effect**; if not,
   stop with nothing created.
2. Show the exact plan and wait for an explicit yes: `~/Developer/<name>`,
   `git init`, `gh repo create asumaran/<name> --private --source
   ~/Developer/<name>`. No content push unless the user says so.
3. Create it, add the repo to the projects map
   (`~/Developer/dotfiles-bash/modules/claude-code/projects-map.md`, a
   dotfiles commit the user approves).
4. `/task new "<name>"` with `home: repo` (TASK.md and DECISIONS.md in
   `docs/`, symlinked from `work/`), and hand off to its herdr space.

## Workers, rounds and confirmation

The worker-side contract (gate, report, `¿todo resuelto?` confirmation,
`/asdev:pre-pr --delegated`) lives in the `worker` skill. From this side:
workers stay open until the user closes them; a `[worker <name>] terminó:`
prompt is a notice, not an authorization; after it, read the report, tell
the user, and act only within this session's own Authority.
