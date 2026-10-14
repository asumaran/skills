---
name: product-lens
description: Review an artifact of the user's own work (a ticket, a plan, a PR, a code review, or free text) through the eyes of an experienced product person and return a short, curated list of candidate product insights. Use when the user says "product-lens", asks what a product person would think of something, asks for the product angle on a ticket/plan/PR/review, or asks whether something is worth raising with the team.
argument-hint: "[ticket <KEY> | pr <number> | plan <path> | review <path> | free text]"
---

# Product lens

Evaluate one artifact of the user's work the way an experienced product person
would, and hand back a few candidate insights for the user to curate. The user
is the filter: they only communicate what they can defend without an AI in
front of them. Teaching the lens matters as much as the insights themselves,
so every insight must show the question that produced it.

The skill is company-agnostic by design: it must work the same at any employer
or personal project. Everything company-specific comes from the context file
in Step 1; nothing about a particular company may ever be hardcoded here.

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

## Step 2 — Fetch the artifact and gather context

Pull the artifact with the table above. Then feed on every context source the
session actually has access to — good insights come from context, not from the
artifact alone. In rough order of value:

- **The artifact's own trail**: linked tickets, parent/child issues, PR
  comments and review threads, the ticket's discussion.
- **Related history**: search the issue tracker for earlier tickets about the
  same feature or component (e.g. Linear MCP `list_issues` with a query);
  past PRs touching the same area (`gh pr list --search`, `git log` on the
  affected paths). What was tried before and why it changed is often where
  the insight lives.
- **The code and product surface** the artifact touches: enough to understand
  what the user-visible behavior becomes, not to audit the implementation.
- **Customer signals**, when the session has them connected: support or
  feedback threads (Slack, email, meeting notes) that mention the feature.
  Read-only, and only what is relevant to this artifact.

Scale the digging to the artifact: a one-line ticket may deserve more
surrounding research than a self-contained plan. Stay a product reader, not a
code reviewer.

When the sweep is broad (several PRs, many files, a long ticket history),
delegate the gathering to an Explore subagent and keep only its conclusions:
brief it with what the artifact is about and exactly what to look for (prior
attempts, user-visible behavior, related discussions), so the raw file and PR
dumps stay out of the main context. The product judgment in Step 3 always
happens here, never in the subagent.

If a source would clearly have improved the analysis but is not available in
the session (no issue-tracker MCP, no access to customer channels, etc.), do
not fake it or silently skip it: name the gap in the output's closing line and
suggest what to connect for next time.

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
anywhere by this skill. If context gaps limited the analysis (Step 2), add
one line naming them and what to connect.

## Hard rules

- Never post, comment, or edit anything outside the conversation.
- Never invent company facts; if the context file lacks something, say so.
- Never copy company-confidential content from the context file into
  artifacts that live in public repos.
- Stay at product altitude: implementation details only matter when they
  change what the user experiences, costs, or measurability.
