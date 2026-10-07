# The plan cycle and decisions

How `/task plan` turns an idea or a ticket into an approved plan, an
Authority and a filled `deliverables:` list. The order is fixed; `--no-codex`
only removes step 3.

## 1. Plan, in plan mode

Always `EnterPlanMode`; never a loose plan file written by hand. One plan per
task, with **one section per deliverable** (the section is what a worker
reads and implements; its heading carries the deliverable id). While
planning, read the ticket (and its parent and children) with `asdev:jira`,
the repos involved, and the task's `TASK.md` body (Goal, Done when, Open
questions).

## 2. Grilling

Run the `grilling` skill on the plan until there is a shared understanding
with the user. Do not act on the plan before that. Findings that change the
plan go back into it.

## 3. Second opinion (skip only with `--no-codex`)

Invoking `/task plan` counts as the user asking for Codex explicitly: run
`asdev:second-opinion` with the plan as artifact. Verify each finding before
accepting it, resolve the accepted ones in the plan, and keep the rejected
ones with their reason.

## 4. Approve

When the user approves the plan (ExitPlanMode):

1. **Copy the approved plan** to `<task dir>/plan.md` (a stable name; workers
   read it by absolute path from their handoff; there are no per-worker
   copies).
2. **Write `<task dir>/hardening.md`**: the grill's outcome, every second
   opinion finding and how each one was resolved (accepted and fixed, or
   rejected and why).
3. **Record the decisions** the plan embodies with `/task decide` (below),
   one by one, as they were taken.
4. **Fill `deliverables:`** with `status.sh add-row` (never editing the YAML
   by hand): one row per plan section, with `repo`, `branch`, `base`,
   `depends_on` ({id|pr, until: merged|stacked}; `stacked` only within the
   same repo) and `gates` (human or external conditions, e.g. "CORS deployed
   in dev, sta and prod").
5. **Ask the Authority** with `AskUserQuestion`, in two steps:
   - First the mode: `task` (one grant set for every deliverable) or
     `per-deliverable` (asked again at each `/task go`, stored on the row).
   - Then the grants, multiselect: `commit`, `push`, `pr-draft`, `pr-update`,
     `rebase` (force-with-lease) and, **only in the user's own repos**,
     `merge-main`.
   - Validate the implications before saving: `pr-draft` requires `commit`
     and `push`; reject the selection and re-ask if they are missing.
   - Authority never includes: taking a PR out of draft, commenting on
     GitHub or Jira, transitioning tickets.
   - Save it with `status.sh set-root authority='{"mode":"task","grants":[...]}'`
     (or `status.sh set <id> authority=...` in per-deliverable mode).

## /task decide

Insert the decision just above the `<!-- next: D<n> -->` marker in
`DECISIONS.md` with that number, then advance the marker. Format:

```markdown
## D4: <what was decided, one line>
Status: taken | superseded by D9
Deliverable: <id or task>
Date: <YYYY-MM-DD>

What was decided, why, what was rejected, and the risk accepted.
```

A decision needs its why and what was rejected: when the user gave only the
what, ask for those in one question before writing. Numbers are never
reused. To change an earlier decision, write a new one and set the old one's
Status to `superseded by D<new>`; never edit its text. Tell the user the
number.
