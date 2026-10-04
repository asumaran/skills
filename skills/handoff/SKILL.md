---
name: handoff
description: Write or refresh HANDOFF.md, the untracked session-resume file at the root of a git worktree, so a fresh Claude session can continue the work without this conversation. Use when the user asks for a handoff, says they are about to /clear, asks to save the session state, or when another skill (worker, worktree) needs the handoff written for a new instance.
---

# Writing HANDOFF.md

`HANDOFF.md` is the resume point of one working session: a new instance reads
it cold and continues. It lives at the root of the worktree, is never committed,
and is **overwritten**, never appended: it describes the present, not a log.

The same file serves inside and outside a project (the `project` skill): with
project state it also says which milestone the session is on.

## Target

- Argument `<worktree-path>` when given (the `worker` skill passes it, because
  the coordinator's cwd is not the worktree). Otherwise the current worktree:
  `git rev-parse --show-toplevel`.
- Run every git command with `git -C <path>`; never `cd` the session away.

## Preconditions

1. `<path>` is inside a git work tree. If not, stop and say so.
2. `HANDOFF.md` is **not** tracked:
   `git -C <path> ls-files --error-unmatch HANDOFF.md` must fail. If it
   succeeds, stop: excluding a tracked file does nothing, and overwriting it
   would land in the next commit. Tell the user.
3. Make sure it is excluded. In a linked worktree `.git` is a file, so resolve
   the exclude file through git, never by literal path:

   ```bash
   exclude="$(git -C <path> rev-parse --path-format=absolute --git-path info/exclude)"
   grep -qxF 'HANDOFF.md' "$exclude" 2>/dev/null || echo 'HANDOFF.md' >> "$exclude"
   ```

   The exclude file is shared by all worktrees of the repo, which is what we
   want.

## Content

Overwrite the whole file with these sections, in English, every one present
(write "none" rather than dropping a section):

```markdown
# Handoff: <ticket or short title>

Updated: <YYYY-MM-DD HH:MM>  ·  Worktree: <absolute path>  ·  Branch: <branch>
Milestone: <M<n> or M<n>.<x>>  ·  Roadmap: <absolute path>  ·  Plan: <absolute path or none>

## Objective
One line, readable cold. What "done" looks like (PR, local verification, report).

## Done
Real changes, by file, and verified facts (commands run and their results).
Mark them "already verified, do not re-check".

## In progress
Exactly what was underway when this was written.

## Next
Concrete, ordered steps.

## Dead ends
What was tried and does not work, and why. This is the section a fresh session
cannot reconstruct; never leave it vague.

## Local decisions
Decisions already made (approach, names, scope). Say they are decided so the
next session does not re-litigate them.

## Constraints
Base branch, files or areas not to touch, tests to run, related files to read
(absolute paths: plan, brief, report). For a worker, its lineage record and
the `lineage.sh state` command that updates it.

## Authority
What the next session may do on its own: commit, push, open or update a PR,
rebase. Record ONLY what the user granted explicitly in the conversation
(for a project worker, the grant given when the split was approved). Default
when nothing was granted: none of them; ask the user.

## Resume prompt
The exact prompt to paste after clearing, e.g.
"Read <absolute path>/HANDOFF.md and continue from Next. Never commit it."
With project state: `/project next`.
```

## Project state

When the work belongs to a project (the `project` skill finds its roadmap for
this repo, or the session was started with `/project` or `/worker
--milestone`), keep the `Milestone:` line and make the Resume prompt
`/project next`: it reloads the roadmap, the decisions and this file. Without
project state, drop the `Milestone:` line.

## Lineage

A worker launched by the `worker` skill has a lineage record
(`~/.claude/agent-lineage/<name>.json`, read by `asagents`). When the previous
HANDOFF.md names it under Constraints, keep that line on every rewrite: it is
how the session finds its record and the `lineage.sh state` command after a
`/clear`. The handoff never edits the record itself.

## After writing

- Show the user the path and the Resume prompt.
- Do not commit anything.
- If the user is about to `/clear`, remind them the Resume prompt is the line
  to paste into the new session.
