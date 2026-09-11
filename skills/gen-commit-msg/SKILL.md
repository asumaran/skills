---
name: gen-commit-msg
description: Generate a Conventional Commits message and commit with git following the user's format (type(scope) title, concise bullets, selective staging, no ads), including where the commit may go (direct to main in the user's own repos, branch + PR elsewhere) and how to handle git hooks. Use whenever the user asks to commit changes, generate a commit message, says "commit and push", or when you need to decide whether a commit can land on main.
---

Your task is to help the user to generate a commit message and commit the changes using git.


## Guidelines

- DO NOT add any ads such as "Generated with [Claude Code](https://claude.ai/code)"
- Deciding what to commit:
  - If there are staged changes, commit exactly those. Don't stage anything else.
  - If nothing is staged, stage the files related to the work done in this session (`git add` them yourself) and commit. Don't make the user stage files for you.
  - Never blanket-stage (`git add -A` / `git add .`). If there are modified files unrelated to the session's work or of unknown origin, leave them out and mention them after committing. Ask only when you genuinely can't tell what belongs in the commit.
- Follow the rules below for the commit message.


## Where the commit goes

Decide this before committing. Check who owns the repo:

```bash
gh repo view --json owner -q .owner.login
```

- **Owner `asumaran` (the user's own repos):** no pull requests. Work may live
  on a branch or a worktree (the user prefers worktrees), but it is integrated
  by merging straight into `main`; see the `worktree` skill, section
  "Integrating the work back into main". Committing directly on `main` is
  fine too. Never offer "PR or merge?" as a choice: the default is `main`.
  Open a PR only when the user asks for one or the repo declares a PR
  workflow (branch protection, `CONTRIBUTING`, a hook that rejects pushes to
  `main`). A repo's own convention always wins over this default.
- **Any other owner:** never commit or push to `main`. Work on a branch and
  integrate through that repo's PR flow.
- Either way, never commit or push unless the user asked for it in this
  conversation.

### Git hooks

- Every git hook must pass. Never skip them on your own (`--no-verify`, `-n`,
  `core.hooksPath` tricks, editing the hook).
- If a commit or push fails because of a hook, stop and give the user the two
  options: (a) fix the underlying problem so the hook passes, or (b) skip the
  hook (`--no-verify`). The user chooses; never decide for them.


## Format

```
<type>:<space><message title>

<bullet points summarizing what was updated>
```

## Example Titles

```
feat(auth): add JWT login flow
fix(ui): handle null pointer in sidebar
refactor(api): split user controller logic
docs(readme): add usage section
```

## Example with Title and Body

```
feat(auth): add JWT login flow

- Implemented JWT token validation logic
- Added documentation for the validation component
```

## Rules

* title is lowercase, no period at the end.
* Title should be a clear summary, max 50 characters.
* Use the body (optional) to explain *why*, not just *what*.
* Bullet points should be concise and high-level.

Avoid

* Vague titles like: "update", "fix stuff"
* Overly long or unfocused titles
* Excessive detail in bullet points

## Allowed Types

| Type     | Description                           |
| -------- | ------------------------------------- |
| feat     | New feature                           |
| fix      | Bug fix                               |
| chore    | Maintenance (e.g., tooling, deps)     |
| docs     | Documentation changes                 |
| refactor | Code restructure (no behavior change) |
| test     | Adding or refactoring tests           |
| style    | Code formatting (no logic change)     |
| perf     | Performance improvements              |
