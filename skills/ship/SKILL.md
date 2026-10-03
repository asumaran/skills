---
name: ship
description: Ship the current work up to a given level, commit, push, release or deploy, following each repo's own documented mechanism. Only runs when the user invokes /ship explicitly.
disable-model-invocation: true
---

# /ship [commit|push|release|deploy]

The user invoked this command explicitly. The level they passed is their
authorization for that level **and the ones below it, nothing more**. Default
level: `commit`.

```
commit  <  push  <  release  <  deploy
```

Stop at the first failure and report it; never skip a failed step to reach a
higher level.

## commit

Follow the `gen-commit-msg` skill entirely: staging rules (this session's files
only, never `git add -A`), owner check, hooks (never `--no-verify` on your own),
message format. "Everything" in the user's words means everything from this
session; mention unrelated changes left unstaged.

Nothing to commit is not an error: say so and continue to the next level if one
was requested.

## push

Resolve the owner (`gh repo view --json owner -q .owner.login`):

- **Own repo (`asumaran`), on `main`:** `git push`.
- **Own repo, on a branch or worktree:** this invocation **is** the request to
  integrate. Follow the `worktree` skill, "Integrating the work back into main"
  (`wt merge` from the main checkout on `main`, checks green first), then push
  `main`. Do not remove the worktree unless the user asked.
- **Own repo that declares a PR workflow, or any other repo:** push the branch.
  Never push to `main`. Opening or updating a PR is not part of `/ship`; say so
  if there is none.

A branch that already has an upstream: plain `git push`. The first push is
explicit, because a bare `git push -u` fails without an upstream under the
default `push.default=simple`:

```bash
branch=$(git symbolic-ref --short HEAD)
remote=$(git config "branch.$branch.pushRemote" || git config remote.pushDefault || git config "branch.$branch.remote" || echo origin)
git push -u "$remote" "HEAD:refs/heads/$branch"
```

## release

Use only the mechanism the repo documents. Look, in order:

1. The repo's `CLAUDE.md`: a `## Releasing` or `Release & deploy` section.
2. `scripts/release.sh` (read its header for usage).

If neither exists, stop and say the repo has no documented release; do not
improvise tags or versions.

Before running, show the user what will happen (version, tag, what gets
published). Versions:

- If the script derives the version itself (e.g. `asdev`), run its
  `--dry-run` first when it has one and show the result.
- If the script needs the version as an argument (the herdr `as*` plugin
  family: `scripts/release.sh X.Y.Z`), derive it from the Conventional Commits
  since the last `v*` tag: a breaking change (`!` or `BREAKING CHANGE`) bumps
  major, any `feat` bumps minor, anything else bumps patch. State the derivation.
- If the repo documents a manual tag (e.g. asreviewer), follow its exact format.

Never treat a `--no-push` flag as a dry run unless the script says so: some
create the commit and tag locally anyway.

## deploy

Only if the repo documents a deploy, and only following its gate exactly (e.g.
asreviewer: wait for the tag's CI with `--exit-status`, then pass that tag
explicitly to the deploy script). No documented deploy: stop and say so.

## Report

One line per level reached: commit hash and subject, what was pushed where,
version and tag released, what was deployed. If a level was not reached, say
which and why.
