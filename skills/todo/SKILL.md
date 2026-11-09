---
name: todo
description: Park something for later in the user's GitHub inbox (asumaran/inbox) with the context of this conversation, list what is parked, or pick an item and launch the work where it belongs (its account, repo and worktree). Use when the user says "todo", "apúntalo", "anótalo", "guárdalo para después", "para más tarde", "inbox", "qué tengo pendiente", or asks to work or close an inbox item.
---

# The inbox

One private repo, `asumaran/inbox`. Every parked item is an issue there.
The issue is the whole record: title, the user's words, the context a fresh
Claude needs to pick it up, and labels that say where it is worked.

`gh` may have a work login active (`gh auth status` lists several). The
inbox always goes through the personal one: run **every** inbox call in this
skill with `ghp` (`gh` as the `asumaran` login, installed by the dotfiles
`claude-code` module) instead of `gh`. Where `ghp` is missing, the prose
modes (add, list, done) can prefix `gh` with
`GH_TOKEN="$(gh auth token --user asumaran)"`; the launcher `scripts/work.sh`
has no fallback and needs `ghp` (only a dry run fed by `--issue-json` works
without it).

Labels:

| Label | Meaning |
|---|---|
| `account:personal` / `account:syft` / `account:mas` | Which Claude works it: `~/.claude`, `~/.claude-syft`, `~/.claude-mas` |
| `org:masorange` / `org:syft` / `org:personal` | Which organization it belongs to (filter the inbox by company) |
| `repo:<name>` | The repo it belongs to (bare name, e.g. `repo:monorepo-front`); created on demand |
| `ready` | The user approved it: the launcher (`scripts/work.sh`, run by `/todo work` or by inbox-agent's dispatch) may start a worker on it without asking. Marking it `ready` is also the user's permission for that worker to commit on the item's branch |
| `in-progress` | A worker has it: set by `work.sh` when it launches (it removes `ready`), removed by the worker when it blocks |
| `large` | Several PRs or repos, needs a plan: `work.sh` refuses it with exit 4 and it goes to `/aw:new`. Set by inbox-agent's triage or by hand |

The board is GitHub Project #5 "Inbox"; its `Status` field is the one view
of where each item stands:

| Status | Meaning |
|---|---|
| Inbox | Not triaged yet |
| Hoy | A Claude will work it (`ready`) or it is queued |
| En progreso | A worker has it (`in-progress`) |
| Para ti | Only the user can do it: the latest comment carries the drafted message or the question with its options. Workers that block land here too |
| Hecho | Closed: done, already handled, or no longer relevant |

`work.sh <n> --set-status "<Status>"` moves a card; until an option exists
on the board it says so and the labels and comments carry the state.

Confidentiality: the inbox is a personal repo. For items captured under a
work account write pointers (ticket keys, PR URLs, file paths, command
names), never customer data, secrets or pasted internal documents.

First-time setup (repo, labels) is
`scripts/setup-inbox.sh` next to this file; idempotent, run it when
`ghp repo view asumaran/inbox` fails.

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
3. **Labels**: `account:<x>` always; `org:<masorange|syft|personal>` always
   (repo owner `masmovil` → masorange, `syftdata` → syft, else personal; a
   Jira ESHOP key → masorange, a Linear SYF2 key → syft); `repo:<name>` inside a repo, created
   first so the create does not fail on a missing label:
   `ghp label create "repo:<name>" -R asumaran/inbox --color ededed --force`
   (idempotent).
4. **Create**:
   ```bash
   ghp issue create -R asumaran/inbox --title "<title>" --body-file "$tmp" \
     --label "account:<x>" --label "org:<o>" --label "repo:<name>" --assignee asumaran
   ```
   Only the personal login is ever assigned or given access: the inbox is a
   private personal repo and work logins stay out of it. asgotoissues reads it
   through its own `inbox` stack with the `asumaran` account.
5. Reply with the URL only, then continue the previous work.

## list

```bash
ghp issue list -R asumaran/inbox --state open --limit 50 \
  --json number,title,labels,createdAt,url
```

A table: `#`, title, account, repo, age, and `ready` / `in-progress` when
set. Order: items whose account **and** repo match this session first (this
session can work them right here), then the same account, then the rest.
Close with: `/todo work <n>` launches one.

## work <n>

Launching is one script, `scripts/work.sh` next to this file, the same one
inbox-agent's dispatch uses. Do not redo its steps by hand.

1. **Read it**: `ghp issue view <n> -R asumaran/inbox --json title,body,labels,url,comments`.
2. **Size**, from the body and comments, decided by you before launching:
   - **Small** (one repo, one PR, a clear done-when): launch it, step 3.
   - **Large** (several PRs or repos, needs a plan) or **no repo**: run
     `/aw:new <issue url>`; it reads inbox issues and launches the
     coordinator with the item's account.
   - **A question or a thought**, nothing to build: answer it here, then
     offer `/todo done <n>`.
   An item captured outside Claude (GitHub app, `gh`) has no Origin block:
   if the repo or the done-when is missing, add it to the issue first (a
   comment with `Done when: ...`, the `repo:<name>` label) or go Large.
3. **Preview, then launch**:
   ```bash
   ~/.claude/skills/todo/scripts/work.sh <n> --dry-run   # prints, writes nothing
   ~/.claude/skills/todo/scripts/work.sh <n>
   ```
   It refuses a `large` item, resolves the account (`account:<x>`, default
   personal) and the repo (Origin `checkout:`, else `repo:<name>` under
   `~/Developer` or the projects map), needs a done-when criterion (a line
   starting with "Done when" in the body or a comment, with at least one
   word after it), checks that no agent `wk_inbox<n>` exists and that the
   repo does not track a root `HANDOFF.md`, branches `inbox-<n>-<slug>`
   from `origin/<default branch>`, creates the worktree with `wt`, writes
   `HANDOFF.md` from `templates/HANDOFF.md` (issue text fenced as untrusted
   data, repo rules, the worker's Authority; excluded from git), injects
   the item's `CLAUDE_CONFIG_DIR` into a free pane of the worktree's herdr
   workspace, re-reads the issue and reserves it (`in-progress`, `ready`
   removed, "Picked up" comment, Status En progreso), starts `wk_inbox<n>`
   with `--permission-mode auto`, records its lineage (`inbox#<n>`) and
   sends the boot prompt. A failed start or an interrupted launcher
   reverts the reservation, unless the start failed because another launch
   already owns `wk_inbox<n>`.

   Dry run: `--dry-run` resolves and prints everything (also the rendered
   `HANDOFF.md`) and applies exit codes 3/4/6 as a real run, but writes
   nothing: no fetch, branch, worktree, HANDOFF, GitHub write or pane; the
   only disk effect is a temp dir under `mktemp`, removed on exit. With
   `--set-status` it prints the Status it would set and exits 0.

   Exit codes (same list in the header of `work.sh`):

   ```
   0  launched, or a dry run printed
   1  error; after the reservation it is reverted, except a failed boot prompt (the agent is alive, the item stays in-progress)
   2  usage
   3  no repo resolved -> Para ti
   4  needs /aw:new: label `large`, or no done-when criterion -> Para ti
   5  herdr not reachable: nothing written, the item stays ready
   6  not launchable: closed, already in-progress, agent wk_inbox<n> exists, or the repo tracks a root HANDOFF.md
   ```

   For `/todo work`: on 3 or 4 go Large or fix the issue; on 5 nothing
   changed; on 1 the message says what was left.
4. Report what it printed (workspace, pane, agent, worktree, account), one
   line each. The worker ends with a single question (merge to main for
   `asumaran` repos, a draft PR elsewhere) or, if blocked, moves the item
   to Para ti with a comment.

## done <n> [note]

```bash
ghp issue close <n> -R asumaran/inbox -c "<what happened, with the PR or commit URL>"
```

# Capturing from outside Claude

The GitHub app on the phone (photos and long text included), or
`gh issue create -R asumaran/inbox` from any shell. Add the `account:` and
`repo:` labels when known; `work` fills the rest.
