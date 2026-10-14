---
name: product-lens
description: Review an artifact of the user's own work (a ticket, a plan, a PR, a code review, or free text) through the eyes of an experienced product person and return a short, curated list of candidate product insights. Use when the user says "product-lens", asks what a product person would think of something, asks for the product angle on a ticket/plan/PR/review, or asks whether something is worth raising with the team.
---

# Product lens

Evaluate one artifact of the user's work the way an experienced product person
would, and hand back a few candidate insights for the user to curate. The user
is the filter: they only communicate what they can defend without an AI in
front of them. Teaching the lens matters as much as the insights themselves,
so every insight must show the question that produced it.

**This skill never communicates anything on the user's behalf.** No PR
comments, no ticket comments, no Slack messages, no edits to the artifact.
The only output is the analysis in the conversation.

## Arguments

One artifact per invocation:

| Argument | Meaning | How to fetch it |
|---|---|---|
| `ticket <KEY>` | An issue/ticket (e.g. Linear, Jira) | The issue tool available in the session (Linear MCP `get_issue`, the Jira skill, etc.) |
| `pr <number>` or a PR URL | A pull request | `gh pr view <n> --json title,body,comments,files` plus `gh pr diff <n>` when the diff matters |
| `plan <path>` | A plan or design doc on disk | Read |
| `review <path>` | A code review / findings file on disk | Read |
| anything else | Free text to evaluate as-is | Use the text directly |

If no argument is given, ask what artifact to look at. Do not guess.

## Step 1 — Load company context

The product judgment lives in a per-company context file, not in this skill:

```
~/.claude/product-context/<company>.md
```

Resolve `<company>`:

1. If the directory has exactly one `.md` file, use it.
2. Otherwise infer from the current repo's GitHub org
   (`gh repo view --json owner -q .owner.login`) and match it against the
   filenames.
3. If still ambiguous, ask the user once (AskUserQuestion) and remember the
   answer for the rest of the session.

If the file does not exist, **say so explicitly** and continue with the
generic lens only, labeling the output as "generic product lens, no company
context". Never invent company facts (customers, pricing, strategy,
benchmarks) to fill the gap; an invented fact is worse than no insight.

### Context file format

A context file is plain markdown the user maintains. Typical sections (none
are required; use whatever is there):

- **Who the customer is** — the real end user, who pays, who churns.
- **Business model** — pricing mechanics and what drives cost for customers.
- **What quality means here** — the tradeoffs the company actually cares
  about (e.g. precision vs. coverage, speed vs. accuracy).
- **Leadership themes** — what the founders/leads keep coming back to.
- **Questions that land** — product questions that have worked before.
- **Glossary** — internal terms a reviewer must not misread.

## Step 2 — Fetch and understand the artifact

Pull the artifact with the table above. Then research the surroundings **only
as far as the artifact demands**: a ticket may need a quick look at the code
it touches, a PR may need its linked ticket, a plan may need none of that.
This is a product read, not a code review; do not audit the implementation.

## Step 3 — Apply the lens

Interrogate the artifact with the core questions, plus whatever the company
context file adds:

1. **Who is this for?** Which user actually benefits, and is that the user
   the company optimizes for?
2. **What happens if we ship exactly as written?** Follow the artifact
   literally into production: what does the end user see, including the edge
   and failure cases it is silent about?
3. **What does it cost the customer?** Money, trust, time, attention. Where
   the business model makes some mistakes expensive, check for those first.
4. **How do we know it worked?** Is there any measurement, feedback loop, or
   definition of success? If none, that is often the insight.

Discard weak observations. Three strong insights beat five padded ones; one
is a valid result, and so is "nothing worth raising" when that is the honest
answer.

## Step 4 — Output

Return **3–5 candidate insights maximum**, each in this shape:

```
### <short title>

- **Observation:** what the artifact does/misses, concrete and checkable.
- **The question that surfaced it:** which lens question (or context-file
  theme) produced this, so the user learns to ask it themselves.
- **What you could propose:** the smallest concrete suggestion the user could
  make in their own words.
- **Worth communicating?** yes / maybe / no, with an honest one-line reason
  (impact, confidence, and whether the team likely knows this already).
```

Close with a one-line reminder that the user curates: nothing gets posted
anywhere by this skill.

## Hard rules

- Never post, comment, or edit anything outside the conversation.
- Never invent company facts; if the context file lacks something, say so.
- Never copy company-confidential content from the context file into
  artifacts that live in public repos.
- Stay at product altitude: implementation details only matter when they
  change what the user experiences, costs, or measurability.
