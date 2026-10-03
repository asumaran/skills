---
name: zed
description: Open files, worktrees, diffs, or generated output in the user's Zed editor from a terminal session, picking the right window flag. Use when the user asks to open, show, or view something in Zed, or asks what can be driven in Zed from the CLI.
---

# Driving Zed from a terminal session

The user's editor is Zed (`/usr/local/bin/zed`). The `zed` CLI is the only
control channel: it **pushes** things into the editor and reads nothing back.
There is no API, socket, or RPC to query editor state.

## Never open anything unprompted, except documents to read

Opening a window takes over the user's screen. Only run `zed` when the user
asks for it, or offer first and wait. This mirrors the `worktree` skill, which
passes `-e none` so `wt` does not pop an editor on the user's behalf.

One standing exception, granted in the user's global `CLAUDE.md`: a document
generated for the user to read (spec, questions, plan, report, message draft)
is opened with `zed -e <file>` as soon as it is written. Source files edited as
part of the work are not documents to read and stay unopened.

## Picking the window flag

The user has `"cli_default_open_behavior": "new_window"` in
`modules/zed/settings.json` (dotfiles), so a bare `zed <path>` opens a **new
window**. Explicit flags override that setting, so always pass one:

| Case | Command |
|---|---|
| One file, for the user to look at | `zed -e file:LINE:COL` |
| Several files of the project already open | `zed -a a.ts b.ts` |
| A worktree or a different project | `zed -n ~/wt/repo/branch` |
| Show a whole change | `zed --diff before/ after/` |
| Ephemeral output, not a repo file | `cmd \| zed -` |

The rule: reuse the window when the target belongs to the project already on
screen, open a new one when it is a different project.

`--diff` accepts directories and renders a single multi-diff the user can accept
or reject hunk by hunk, which beats dumping a diff into the terminal.

## `--wait` is the only channel back

`zed --wait <file>` blocks until the file or window is closed. That allows a
handoff: write a draft, open it, let the user edit, then read the result from
disk. Use it only when the user explicitly wants to edit something by hand;
it blocks the session for as long as the file stays open.

Note `$EDITOR` and `$VISUAL` are `zed --wait`, so anything invoking `$EDITOR`
inherits the blocking behavior.

## `zed://` URLs

Verified against Zed 1.18.1 by invoking each and checking
`~/Library/Logs/Zed/Zed.log` for `unhandled url`:

- Handled: `zed://settings`, `zed://agent`, `zed://skill`
- **Not** handled: `zed://keymap`, `zed://extensions`, `zed://themes`

Third-party Zed skills document `zed://keymap`; it does not exist in this
build. Verify any new `zed://` URL with the log check below before relying on it.

## The exit code lies

`zed` returns 0 even for an unhandled URL. To confirm an invocation actually
did something:

```bash
LOG=~/Library/Logs/Zed/Zed.log; BEFORE=$(wc -l < "$LOG")
zed <args>; sleep 2
tail -n +$((BEFORE+1)) "$LOG" | grep -iE "unhandled|error"
```

## Configuration is a second, indirect channel

`~/.config/zed/settings.json` is a symlink to `modules/zed/settings.json` in the
dotfiles repo, and Zed picks up edits live. Changing that file changes the
user's editor (theme, fonts, vim mode, docks). Treat it as a config change to
the dotfiles repo, not as a way to "control" the editor, and follow the repo's
own rules for it.

Zed also reloads buffers when files change on disk, so ordinary edits already
show up in open buffers with no CLI call.

## What is not possible

Do not offer or imply any of this:

- Reading editor state: active buffer, selection, cursor, open tabs, unsaved buffers
- LSP diagnostics or anything Zed knows that the disk does not
- Running editor actions (command palette, format, go to definition)
- Closing files or windows

The VS Code and JetBrains integrations do have that read side. Zed does not,
because Zed's own integration path is ACP with Zed hosting the agent, which is
the opposite direction from a standalone terminal session.
