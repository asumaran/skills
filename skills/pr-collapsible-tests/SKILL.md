---
name: pr-collapsible-tests
description: Reorganize the manual test steps of a GitHub PR description into collapsible <details>/<summary> toggles, one per test step. Use when the user asks to make a PR's testing section collapsible, add toggles/desplegables to test steps, or tidy up a long PR testing section.
---

# Collapsible test steps in PR descriptions

Turn a long "Testing / Manual" section of a PR description into a compact list
of collapsible blocks: one `<details>` per test step (plus one for the setup),
so reviewers expand only the step they are executing. Only restructure — never
drop or rewrite content while doing this.

## Workflow

1. **Identify the PR.** If not given, resolve it from the current branch:
   `gh pr view --json number,title,url`. Confirm with the user if ambiguous.
2. **Back up the original body** before touching anything:

   ```bash
   gh pr view <num> --json body -q .body > <scratchpad>/pr<num>-body.md
   ```

3. **Rewrite only the testing section** into the target format (below) in a new
   file. Leave every other section byte-identical apart from stray blank lines.
4. **Apply**:

   ```bash
   gh pr edit <num> --body-file <scratchpad>/pr<num>-body-new.md
   ```

5. Tell the user where the backup of the original body lives.

## Example template

The exact structure varies per PR (adapt to how its testing section is already
organized, and to anything the user asks for). What must always hold are the
rendering gotchas in the next section. A shape that has worked well:

```markdown
<details>
<summary><b>1. Step title</b> (<code>symbol_or_metric</code>)</summary>

1. First instruction...
2. Second instruction...

Pass: what proves the step passed.

</details>
```

Ideas that usually apply (not rules):

- Keep the section heading and any one-line intro visible; a note like
  "Expand each step for details." helps reviewers.
- Wrap the **Setup** in its own `<details>` and move noisy environment/gotcha
  notes inside it — that is usually what bloats the section most.
- Keep the step numbering from the original headings (`1`, `1b`, `2`, ...) in
  the summaries; drop headings that become redundant inside the blocks.
- To leave a block expanded by default, use `<details open>`.

## GitHub rendering gotchas (the reason this skill exists)

- **Markdown does not render inside `<summary>`**: backticks and `**bold**`
  show literally. Use `<code>` and `<b>` HTML tags instead.
- **Blank line after `</summary>`** is required, otherwise the markdown inside
  the block (numbered lists, fenced code, bold) renders as plain text.
- **Blank line before `</details>`** keeps the last markdown block rendering
  correctly.
- Do **not** indent the content inside `<details>` — indentation turns it into
  a code block.
- Fenced code blocks, nested lists, and images all work inside `<details>` as
  long as the blank-line rules above are respected.

## Safety

- Editing a PR description is outward-facing: do it only when the user asked
  for the reorganization, and always keep the backup from step 2 so it can be
  restored with `gh pr edit <num> --body-file <backup>`.
