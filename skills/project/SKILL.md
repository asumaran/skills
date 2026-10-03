---
name: project
description: Run a multi-session project milestone by milestone, with its state persisted in a ROADMAP and a numbered DECISIONS log so any fresh session can resume it. Sequential (one session per milestone, relayed with /handoff and /project next) or parallel (independent sub-milestones sent to workers and merged back). Use when the user says /project, "init the project", "next milestone", "close M3", "record a decision", "split this milestone into workers", or asks to start a new project repo.
---

# Project: milestones that survive sessions

`/project <init|status|next|decide|close|split|new> [args]`

A project is a repo with a **roadmap** of milestones and a **decisions** log.
Everything a session needs to continue lives in those files, the worktree's
`HANDOFF.md` and the worker reports; never in a conversation. The pieces are
the existing ones: `/handoff` writes the resume point, `/worker --milestone`
runs a sub-milestone in its own worktree and herdr space, `wt merge` integrates
it (the `worktree` skill), `grilling` stress-tests a plan, the `zed` skill opens
what the user has to read.

## Where the state lives

Resolve the repo first: `git rev-parse --show-toplevel`, the main checkout
(`dirname "$(git rev-parse --path-format=absolute --git-common-dir)"`), and the
owner and name (`gh repo view --json owner,name`, falling back to the last two
path parts of the `origin` URL without `.git`; no remote means owner `local`
and the folder name, treated as anyone else's). The project's name in the
templates is the repo name.

| Repo | Roadmap | Decisions |
|---|---|---|
| Owned by `asumaran` | `docs/ROADMAP.md` in the repo, versioned | `docs/DECISIONS.md` |
| Anyone else's | `~/.claude/project-state/<owner>/<repo>/ROADMAP.md`, never in the repo | same folder, `DECISIONS.md` |

Reports always go to `~/.claude/project-state/<owner>/<repo>/reports/`,
unversioned, for both kinds, created when the first worker is launched. A
foreign repo's working tree is never touched by this skill: its `git status`
stays as it was.

An existing roadmap is **adopted**, not replaced. In an own repo look for
`docs/ROADMAP.md`, `docs/roadmap.md`, `ROADMAP.md` by their **real names**
(`git -C <repo> ls-files` plus `ls`), never with an existence test: macOS
filesystems are case-insensitive, so `docs/ROADMAP.md` "exists" when the file
is `docs/roadmap.md`. Use the name as it is on disk everywhere it is written
down. More than one real file: ask which. In a foreign repo, an in-repo
roadmap is only read: say it exists and ask whether to copy it into the state
folder.

Write every path in the state files absolute, never with `~`.

Templates (English, like every repo artifact): `templates/ROADMAP.md`,
`templates/DECISIONS.md`, `templates/report.md` next to this file.

## Formats

A milestone in the roadmap:

```markdown
### M3: Sync engine
Status: planned | active | done
Plan: /Users/asumaran/.claude/plans/<name>.md | none
Done when:
- [ ] `go test ./...` passes with the new sync tests
- [ ] `asfoo -dump` lists the remote items

#### M3.1: Remote client
Status: planned | active | done
Depends on: none | M3.2
Branch: feat/m3-1-remote-client
Done when:
- [ ] ...
```

`Done when` is the contract of a milestone: concrete, checkable criteria. A
milestone without them is not startable; write them with the user first.
Sub-milestones (`M<n>.<x>`) exist only when a milestone is split.

A decision:

```markdown
## D4: Sync is pull-only in v1
Status: taken | superseded by D9
Milestone: M3
Date: 2026-10-03

What was decided, why, what was rejected, and the risk accepted.
```

Numbers are never reused; the `<!-- next: D<n> -->` marker at the end of the
file holds the next one. A decision changes only by a new one that supersedes
it; the old one keeps its text and its Status points to the new one.

## init

Idempotent: running it twice changes nothing the second time.

1. Resolve the state location (above). An adopted roadmap is **never edited**
   by init, and neither is any other existing file.
2. Create only what is missing, from the templates: the roadmap (with the
   user: goal and a first milestone with its `Done when`) and the decisions
   log. When the adopted roadmap already keeps decisions in
   prose (a `## Decisions` section), the new log points there in its
   "Earlier decisions" line (`docs/roadmap.md#decisions`) instead of copying
   them.
3. An adopted roadmap without milestones in the `### M<n>:` format is still
   valid: its milestones are added by `next` the first time one is planned,
   appended in a `## Milestones` section, with the user's approval.
4. Say what was created and what was adopted, then open the roadmap in Zed
   (`zed` skill). In an own repo, offer to commit the new files (`docs(project):
   ...`); never commit on your own.

## status

Read-only. The active milestone (none active: the first `planned` one, said
as such), its `Done when` with what is checked, its
sub-milestones and their reports' `phase`/`summary`, decisions taken since the
milestone started, and whether a `HANDOFF.md` in this worktree says something
newer than the roadmap.

## next

The contract of every session. A fresh session with nothing but `/project next`
must be able to continue.

1. **Load the state, whole.** The worktree's `HANDOFF.md` if present (its
   `Milestone:` line says which milestone this session is on), the roadmap,
   every decision whose Status is `taken` in full (never a summary), the plan of
   the milestone if it has one, and the reports of its sub-milestones.
2. **Pick the milestone.** The handoff's milestone; else the one `active`; else
   propose the first `planned` one and wait for the user. In a worker's
   worktree (its handoff names a sub-milestone `M<n>.<x>`), only that
   sub-milestone, never the parent.
3. **No plan yet:** plan it in plan mode (`EnterPlanMode`), never as a loose
   file. When the user asks to grill it, or the plan rests on decisions
   nobody has made, run the `grilling` skill and **do not act until the user
   confirms a shared understanding**. Once approved, write its path in `Plan:`
   and set `Status: active`.
4. **Work** inside the Authority the user gave (the handoff's section). Every
   decision taken along the way goes through `decide` as it happens, not at
   the end.
5. **Before stopping or a `/clear`:** run `/handoff`; with project state it
   records `Milestone:` and the roadmap and plan paths, and its Resume prompt is
   `/project next`. In an own repo, commit the roadmap and decisions changes
   when the user asks (or when the handoff's Authority says so).

## decide

Insert the decision just above the `next` marker with that number, then
advance the marker. A decision needs its why and what was rejected: when the
user gave only the what, ask for those in one question before writing. It may
name a milestone that has not started. To
change an earlier decision, write the new one with the reason and set the old
one's Status to `superseded by D<new>`. Tell the user the number.

## close [M<n>]

1. Check every `Done when` criterion **now**, each with the command run and its
   output (or what was looked at). "Tests pass" with no command is not
   evidence. A criterion that fails stops the close; say which.
2. With sub-milestones: every one is `done`, its report says `phase: done`, its
   branch is merged into the coordinator's branch, and the parent's criteria
   are re-verified after the merge (they are checked on the integrated code,
   not on each branch).
3. Tick the criteria, set `Status: done`, add one line with the date and the
   evidence summary under the milestone. Open the roadmap in Zed. Offer the
   commit in an own repo.

## split M<n>: parallel sub-milestones

For a milestone whose parts can be built independently.

1. Write the sub-milestones in the roadmap: each with its own `Done when`,
   `Depends on`, and `Branch`. Two parts that must land together are not
   independent: either one sub-milestone, or the dependent one depends on the
   other (its worker branches from the other's branch).
2. Ask the user to approve the split and to grant the workers' Authority:
   at least local commits on their own branch. Record that grant in each
   worker's handoff; nothing else is implied (no push, no PR, no merge).
3. **Base:** the coordinator's committed `HEAD`. Commit the roadmap first
   (own repo) and check `git status` is clean; uncommitted changes would not
   reach the workers, so stop and say so if there are any.
4. Launch each one with `/worker --milestone <roadmap path>#M<n>.<x>`. The
   worker writes its report to `reports/M<n>.<x>.md` from the template and keeps
   it current.
5. **Integrate** when a report says `phase: done`: read the report, then from
   the coordinator's checkout `wt merge <branch>` (the `worktree` skill; in a
   foreign repo, into the coordinator's branch, never into `main`). When an
   earlier merge moved that branch, rebase the worker's unpushed branch onto
   it first so the merge fast-forwards (the `worktree` skill). Then
   `close` the sub-milestone, and when all are in, `close` the parent, which
   re-verifies on the integrated code.
6. Cleaning up workers' worktrees (`wt remove`) and their herdr workspaces is a
   destructive step: list them and ask.

## new <name>

Last in the order: use it only once `init`, `next` and `close` have worked on
an existing repo. A new repo is outward-facing, so it runs under an explicit
contract:

1. Check the `herdr` skill can see the server and create a workspace **before
   any effect**. If herdr does not answer, stop; nothing has been created.
2. Show the exact plan and wait for an explicit yes: the folder
   (`~/Developer/<name>`), the GitHub repo (`asumaran/<name>`, private unless
   the user says otherwise), and the commands (`git init`, `gh repo create
   asumaran/<name> --private --source ~/Developer/<name>`). No push of content
   is part of it unless the user says so.
3. Create the folder, run `init` there (goal and first milestone with the
   user), commit the state when the user asks, create the GitHub repo.
4. Add the repo to the projects map
   (`~/Developer/dotfiles-bash/modules/claude-code/projects-map.md`), which is
   a commit in dotfiles the user approves.
5. Create its herdr workspace (`herdr` skill) and hand off to a new instance
   there with `/project next`.
