---
deliverable: <id or id-rN>
task: <KEY>
branch: <branch>
worktree: <absolute path>
plan_sha256: <sha256 of plan.md as read, or none>
phase: analysis | implementing | awaiting-confirmation | done | blocked
summary: <one sentence>
updated: <YYYY-MM-DD HH:MM>
---

## Plan gate

Does the plan's section for this deliverable match the code as found?
State it explicitly. A mismatch, an out-of-section change, a contradicted
decision or an effect on another deliverable stops the work (see the gate in
the task skill); record here what was found and what the user said.

## What I did

## What I found

file:line; anything that contradicts the plan or a decision goes first.

## Done when

| Criterion | Evidence (command run and its output) |
|---|---|

## Out of scope found

Pre-existing failures and loose ends: reported, not fixed.
