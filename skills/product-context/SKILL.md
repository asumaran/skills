---
name: product-context
description: Capture a durable fact about a company or its product into the user's private per-company context file (~/.claude/product-context/<company>.md), the knowledge base the product-lens skill reads. Use when the user says to save, note, or add something to the company context ("apunta esto al contexto de syft", "guarda esto en el contexto de la empresa"), shares something learned in a meeting, customer call, or Slack thread that is worth keeping, or wants to start a context file for a new company.
argument-hint: "[the fact to capture, or empty to be asked]"
model: sonnet
---

# Product context capture

Turn something the user just learned about their company — in a meeting, a
customer call, a Slack thread, a ticket — into a durable entry in the
per-company context file at `~/.claude/product-context/<company>.md`. These
files are the knowledge base of the `product-lens` skill: the better they
get, the better its insights. This skill is the capture path outside a
product-lens run; product-lens Step 5 covers capture during one.

## Step 1 — Resolve the company

Same rules as product-lens: if the directory has exactly one `.md` file, use
it; otherwise infer from the current repo's GitHub org and match filenames;
if still ambiguous, ask once.

If no file exists for the company, offer to create one with the standard
skeleton (sections: who the customer is, business model, what quality means
here, leadership themes, questions that land, glossary) and file the fact
under the right section.

## Step 2 — Distill

Rewrite the raw input as an operational fact, in the file's language and
style: what it means for product decisions, not who said it in which meeting.
Convert relative dates to absolute. Place it in the section where a future
reader would look for it; create a section only when none fits. If the fact
contradicts something already in the file, update the old line instead of
appending a contradiction.

## Step 3 — Propose, then persist

Show the user the exact line(s) you would add or change and where, via
AskUserQuestion. On approval, apply the edit, then commit and push in the
private repo the file lives in (the directory is a symlink; resolve the real
path). Conventional commit scoped to the company, e.g.
`feat(syftdata): record that CSV sources are rarely used`. The user's
approval of the edit covers that commit and push.

## Boundaries

- Durable facts about the company and its product only: customers, pricing
  mechanics, quality tradeoffs, leadership themes, vocabulary, what worked.
- Never meeting logistics, compensation, personal notes, or interview
  material — those stay in their own private places.
- The context repo is private and must stay private; never copy its content
  into public repos or artifacts.
