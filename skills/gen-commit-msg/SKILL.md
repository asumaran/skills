---
name: gen-commit-msg
description: Generate a Conventional Commits message and commit with git following the user's format (type(scope) title, concise bullets, selective staging, no ads). Use whenever the user asks to commit changes, generate a commit message, or says "commit and push".
---

Your task is to help the user to generate a commit message and commit the changes using git.


## Guidelines

- DO NOT add any ads such as "Generated with [Claude Code](https://claude.ai/code)"
- Deciding what to commit:
  - If there are staged changes, commit exactly those. Don't stage anything else.
  - If nothing is staged, stage the files related to the work done in this session (`git add` them yourself) and commit. Don't make the user stage files for you.
  - Never blanket-stage (`git add -A` / `git add .`). If there are modified files unrelated to the session's work or of unknown origin, leave them out and mention them after committing. Ask only when you genuinely can't tell what belongs in the commit.
- Follow the rules below for the commit message.


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
