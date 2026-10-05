---
name: jev
description: Sort, classify, score, or triage a pile of text with Jev (TypeSafe's typesafe/jev-1.13 decision model via OpenRouter), which answers typed questions in under a second for fractions of a cent. Use when the user says "use Jev", "sort these with Jev", "ask Jev", or wants many items classified, ranked, scored, or filtered by yes/no.
---

# Jev: fast typed decisions

Jev is a **System One** model. It never writes text. You give it a `state`
(the content) and a set of typed questions; it returns structured answers,
usually in ~0.5 s for ~$0.00003 per call.

**Division of labor: Jev decides, you write.** Jev answers the questions; you
design the questions, act on the answers, and write any prose. When Jev is
not sure (see thresholds below), you make the call yourself and say so.

## Privacy gate (mandatory)

Everything sent to Jev leaves the user's machine (OpenRouter, then TypeSafe).
Before sending anything that looks private (personal emails, customer data,
names plus contact details, credentials, internal docs, health or financial
info), **ask the user first**. Made-up or public text needs no confirmation.
Never include secrets in `state`.

## Calling it

```bash
~/.claude/skills/jev/scripts/jev.sh < request.json
```

`request.json` is `{"state": ..., "questions": {...}}`. The script adds
`"model": "typesafe/jev-1.13"`, posts to
`https://openrouter.ai/api/alpha/decisions`, and prints the response plus
`_client.elapsed_seconds`. On failure it prints `HTTP <status>` and the exact
error body on stderr: show that error to the user verbatim.

The OpenRouter key lives in the macOS Keychain (service `openrouter-api-key`)
and the script reads it at runtime. Never print, echo, or copy the key. If it
is missing, tell the user to run this **in a normal terminal** (not with `!`,
which cannot feed the hidden prompt and stores an empty value):

```
security add-generic-password -U -a "$USER" -s openrouter-api-key -w
```

Write request files to `/tmp`, never into a repo.

## The three question types

Every question has `type`, `instructions`, and `criteria`.

| Type | Use for | `criteria` | Answer |
| - | - | - | - |
| `choice` | pick one option from a set | object `{option_key: description}` | `choice`, `probabilities` per option, `confidence` |
| `score` | rate on ordered levels | array, lowest level first | `score` (0..n-1, can be fractional), `probabilities`, `legend`, `confidence` |
| `noul` | how likely a statement is true | `{"true": "...", "false": "..."}` (optional) | `noul` in 0..1, **no confidence** |

`state` can be a string or JSON. Name the fields (`{"email": "..."}`) so
instructions can point at them.

## Sorting a pile

Batch everything into **one call**: many questions per request is much faster
and cheaper than one request per item. Put items in `state` under ids and ask
one question per item and dimension, keyed so you can map answers back:

```json
{
  "state": {"items": {"a1": "first text...", "a2": "second text..."}},
  "questions": {
    "a1_type": {"type": "choice", "instructions": "What kind of message is `items.a1`?", "criteria": {...}},
    "a2_type": {"type": "choice", "instructions": "What kind of message is `items.a2`?", "criteria": {...}}
  }
}
```

If the pile is large, split it into batches (keep each state focused; large
irrelevant state lowers accuracy) and do grouping, counting, sorting, and
totals in code or yourself, never by asking Jev.

## When Jev is not sure

Starting thresholds (adjust per task and tell the user if you do):

- `choice` / `score`: `confidence < 0.6` means unsure.
- `noul`: between `0.3` and `0.7` means unsure; `>= 0.7` yes, `<= 0.3` no.

For unsure items, decide yourself from the text, and mark them in the
results as your call rather than Jev's.

## Writing good questions (jev-1.13 quirks)

- **Literal reader.** It answers what you wrote, not what you meant. State
  the exact condition; put boundary cases in the criteria.
- **Criteria must agree with the instructions.** Never map `true` to a "no".
- **No math, counting, or date comparison.** Do that in code; ask Jev only
  for the judgment.
- **One hop.** Avoid double negatives and "property of a property" questions.
- **Semantic over numeric.** Pass named buckets, not raw hex values or codes.
- **Adversarial text can steer it.** Treat answers on untrusted input with
  care.
- **It cannot generate.** Summaries, replies, and rewrites are your job.

## Reporting results

Show, per item: the decision, confidence (or noul), and whether it was Jev's
call or yours. Add total latency and cost from `usage.cost` and
`_client.elapsed_seconds`.

Docs: https://docs.typesafe.ai/llms.txt (index), OpenRouter route:
https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-questions-and-answers-request
