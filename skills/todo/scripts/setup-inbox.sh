#!/usr/bin/env bash
# One-time bootstrap of the asumaran/inbox repo the todo skill writes to.
# Idempotent: safe to re-run after adding a label or a work login.
# Runs gh as the personal account, whatever login gh has active.
set -euo pipefail

REPO="asumaran/inbox"
PERSONAL="asumaran"
# Other gh logins on this machine that must see the inbox (the herdr picker
# lists issues assigned to whoever gh has active). Invited as collaborators
# and the invitation accepted with their own token.
WORK_LOGINS=(alfredo-syft)

export GH_TOKEN
GH_TOKEN="$(gh auth token --user "$PERSONAL")"

if ! gh repo view "$REPO" >/dev/null 2>&1; then
  gh repo create "$REPO" --private \
    -d "Personal inbox: things to work on later, each with the context to pick it up"
  echo "created $REPO"
fi

readme="$(mktemp)"
trap 'rm -f "$readme"' EXIT
cat > "$readme" <<'MD'
# inbox

Things to work on later, one issue each, with the context to pick them up
without the conversation they came from. Written by the `todo` skill of
Claude Code (`/todo <text>` from any session, any account), the GitHub app
or `gh issue create -R asumaran/inbox`.

## Labels

| Label | Meaning |
|---|---|
| `account:personal` / `account:syft` / `account:mas` | Which Claude works it (`~/.claude`, `~/.claude-syft`, `~/.claude-mas`) |
| `repo:<name>` | The repo it belongs to; created on demand |
| `ready` | Approved: a Claude may pick it up without asking |
| `in-progress` | A worker has it |

## Body

The user's words first, then two sections the skill fills from the session:

```markdown
## Context
- What was going on: ...
- Why it came up: ...
- Pointers: paths, PR/ticket URLs, commands, error text
- Done when: ...

## Origin
- account: personal | syft | mas
- repo: owner/name | none
- checkout: main checkout path | none
- cwd, branch, session, captured
```

Items captured outside Claude have no Origin block; `/todo work <n>` derives
what it can from the labels.

## Working an item

`/todo list` shows what is parked, `/todo work <n>` launches it where it
belongs (a worktree with a handoff for a one-PR item, `/aw:new` for anything
that needs a plan) and marks it `in-progress`; the worker comments the PR URL
here and closes the issue when it merges. `/todo done <n>` closes by hand.

## Confidentiality

Personal repo. Items from work accounts carry pointers (ticket keys, PR URLs,
paths), never customer data, secrets or internal documents.
MD
# gh prints the error body on stdout too, so only a successful call yields a sha.
if gh api "repos/$REPO/contents/README.md" >/dev/null 2>&1; then
  echo "README.md (already)"
else
  gh api --method PUT "repos/$REPO/contents/README.md" \
    -f message="docs: inbox format and labels" \
    -f content="$(base64 < "$readme" | tr -d '\n')" >/dev/null
  echo "wrote README.md"
fi

label() { # name color description
  gh label create "$1" -R "$REPO" --color "$2" --description "$3" --force >/dev/null
  echo "label $1"
}
label "account:personal" 1d76db "Work it in the personal Claude (~/.claude)"
label "account:syft"     0e8a16 "Work it in the Syft Claude (~/.claude-syft)"
label "account:mas"      fbca04 "Work it in the MasOrange Claude (~/.claude-mas)"
label "ready"            0052cc "Approved: a Claude may pick it up without asking"
label "in-progress"      d93f0b "A worker has it"

for login in "${WORK_LOGINS[@]}"; do
  if gh api "repos/$REPO/collaborators/$login" >/dev/null 2>&1; then
    echo "collaborator $login (already)"
    continue
  fi
  gh api --method PUT "repos/$REPO/collaborators/$login" -f permission=push >/dev/null
  token="$(gh auth token --user "$login" 2>/dev/null || true)"
  if [[ -z "$token" ]]; then
    echo "invited $login; accept the invitation from that account"
    continue
  fi
  inv="$(GH_TOKEN="$token" gh api /user/repository_invitations \
    -q ".[] | select(.repository.full_name == \"$REPO\") | .id" | head -1)"
  if [[ -n "$inv" ]]; then
    GH_TOKEN="$token" gh api --method PATCH "/user/repository_invitations/$inv" >/dev/null
    echo "collaborator $login (invitation accepted)"
  else
    echo "collaborator $login (invited)"
  fi
done
echo "done: https://github.com/$REPO"
