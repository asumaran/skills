---
name: todo
description: Park something for later in the user's GitHub inbox (asumaran/inbox) with the context of this conversation, list what is parked, or pick an item and launch the work where it belongs (its account, repo and worktree). Use when the user says "todo", "apúntalo", "anótalo", "guárdalo para después", "para más tarde", "inbox", "qué tengo pendiente", or asks to work or close an inbox item.
---

# The inbox

One private repo, `asumaran/inbox`. Every parked item is an issue there.
The issue is the whole record: title, the user's words, the context a fresh
Claude needs to pick it up, and labels that say where it is worked.

`gh` may have a work login active (`gh auth status` lists several). The
inbox always goes through the personal one, so prefix **every** `gh` call in
this skill with:

```bash
GH_TOKEN="$(gh auth token --user asumaran)"
```

Labels:

| Label | Meaning |
|---|---|
| `account:personal` / `account:syft` / `account:mas` | Which Claude works it: `~/.claude`, `~/.claude-syft`, `~/.claude-mas` |
| `repo:<name>` | The repo it belongs to (bare name, e.g. `repo:monorepo-front`); created on demand |
| `ready` | The user approved it: a Claude may pick it up without asking |
| `in-progress` | A worker has it (set by `work`) |

Confidentiality: the inbox is a personal repo. For items captured under a
work account write pointers (ticket keys, PR URLs, file paths, command
names), never customer data, secrets or pasted internal documents.

First-time setup (repo, labels, collaborator for the work login) is
`scripts/setup-inbox.sh` next to this file; idempotent, run it when
`gh repo view asumaran/inbox` fails.

# Session context (injected when the skill loads)

```
Account dir: !`echo "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"`
Cwd:         !`pwd`
Checkout:    !`d=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) && dirname "$d" || echo none`
Branch:      !`git branch --show-current 2>/dev/null || echo none`
Origin:      !`git remote get-url origin 2>/dev/null || echo none`
Session:     ${CLAUDE_SESSION_ID}
Date:        !`date +%F`
```

Account label from the account dir's basename: `.claude` is `personal`,
`.claude-<org>` is `<org>`. Repo label from the origin URL's `owner/name`
(bare `name`); no label outside a git repo. `Checkout` is the main checkout
even inside a linked worktree (the common git dir's parent).

# Modes

| Invocation | Does |
|---|---|
| `/todo <text>` | Park `<text>` with this conversation's context |
| `/todo` or `/todo list` | List what is parked, the items this session could work first |
| `/todo work <n>` | Launch item `n` where it belongs |
| `/todo done <n> [note]` | Close item `n` with what happened |

## add

Capture fast and return to what the session was doing. Do not start the
work, do not ask questions; one line back with the issue URL.

1. **Title**: imperative, at most 70 characters, from the user's words.
2. **Body**: the user's words verbatim first, then the context. Write it to
   a temp file (heredoc) and pass `--body-file`; never inline it.

   ```markdown
   <the user's words, verbatim>

   ## Context
   - What was going on: <one or two lines: what this session was doing>
   - Why it came up: <one line>
   - Pointers: <paths, PR/ticket URLs, commands, error text; what a fresh Claude needs>
   - Done when: <one line, your best reading>

   ## Origin
   - account: <personal|syft|mas>
   - repo: <owner/name or none>
   - checkout: <main checkout path or none>
   - cwd: <cwd>
   - branch: <branch or none>
   - session: <session id>
   - captured: <date>
   ```

   Pointers are the valuable part: a conversation the next Claude will not
   have. Name files with their paths and the lines that matter, the PR or
   ticket being worked, the command that reproduced the problem.
3. **Labels**: `account:<x>` always; `repo:<name>` inside a repo, created
   first so the create does not fail on a missing label:
   `gh label create "repo:<name>" -R asumaran/inbox --color ededed --force`
   (idempotent).
4. **Create**:
   ```bash
   gh issue create -R asumaran/inbox --title "<title>" --body-file "$tmp" \
     --label "account:<x>" --label "repo:<name>" --assignee asumaran,alfredo-syft
   ```
   Both logins are assigned so the herdr picker (asgotoissues, which lists
   issues assigned to whoever `gh` has active) shows the item from either
   account. If the second assignee is refused (collaborator invite not
   accepted yet), retry with `--assignee asumaran` and say so.
5. Reply with the URL only, then continue the previous work.

## list

```bash
gh issue list -R asumaran/inbox --state open --limit 50 \
  --json number,title,labels,createdAt,url
```

A table: `#`, title, account, repo, age, and `ready` / `in-progress` when
set. Order: items whose account **and** repo match this session first (this
session can work them right here), then the same account, then the rest.
Close with: `/todo work <n>` launches one.

## work <n>

1. **Read it**: `gh issue view <n> -R asumaran/inbox --json title,body,labels,url,comments`.
2. **Where it belongs**: account from `account:<x>` (missing: `personal`);
   account dir `$HOME/.claude` for personal, else `$HOME/.claude-<x>`.
   Repo from `repo:<name>` and `checkout:` in the body; when the path is
   gone, resolve the name with `~/.claude/projects-map.md` (personal) or
   `~/Developer/<name>` (work); refuse with a clear line if it is nowhere.
   An item captured outside Claude (GitHub app, `gh`) has no Origin block:
   derive what you can from the labels and text, and ask only for what is
   missing.
3. **Size**, from the body, decided by you:
   - **Small** (one repo, one PR, a clear done-when): hand it off with the
     `worktree` skill. Branch `inbox-<n>-<slug>`; `HANDOFF.md` carries the
     issue body (title, words, Context, Origin), the constraints (base
     branch, commit/PR rules of that repo), and these two duties: comment
     the PR URL on the issue when it opens (`gh issue comment <n> -R
     asumaran/inbox`), and close the issue when the PR merges. Inject the
     **item's** account dir into the pane, explicitly (`export
     CLAUDE_CONFIG_DIR=<account dir>` or `--env`), not this session's: the
     launching contract in the `worktree` skill assumes the launcher's
     account, and here the label decides.
   - **Large** (several PRs or repos, needs a plan) or **no repo**: run
     `/aw:new <issue url>`; it reads inbox issues and launches the
     coordinator with the item's account.
   - **A question or a thought**, nothing to build: answer it here, then
     offer `/todo done <n>`.
4. **Mark it**: `gh issue edit <n> -R asumaran/inbox --add-label in-progress`
   and `gh issue comment <n> -R asumaran/inbox --body "Picked up: <worktree
   or task, account>"`.
5. Report where it is running (workspace, worktree, account), one line each.

## done <n> [note]

```bash
gh issue close <n> -R asumaran/inbox -c "<what happened, with the PR or commit URL>"
```

# Capturing from outside Claude

The GitHub app on the phone (photos and long text included), or
`gh issue create -R asumaran/inbox` from any shell. Add the `account:` and
`repo:` labels when known; `work` fills the rest.
