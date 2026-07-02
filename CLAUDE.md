# skills repo

Personal Agent Skills, one per `skills/<name>/SKILL.md`.

These are installed into agents by `npx skills` (and by the `skills` module of
[dotfiles-bash](https://github.com/asumaran/dotfiles-bash)). For a single target
agent `npx skills` **copies** the files, so editing a skill here does **not**
propagate to an already-installed copy until it is reinstalled.

## When you edit a skill

After modifying any `skills/<name>/SKILL.md`, **offer to update the installed
copy** so the change takes effect. Do not do it silently (it overwrites the
installed skill); ask first, then run:

```bash
DISABLE_TELEMETRY=1 npx -y skills add "$HOME/Developer/skills" --skill <name> -g -a claude-code -y
```

To update every skill at once, use `--skill '*'` instead of `--skill <name>`.
