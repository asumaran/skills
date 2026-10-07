#!/usr/bin/env bash
# Wrapper for status.py, the single writer of a task's TASK.md frontmatter
# (same pattern as worker/lineage.sh: flock per task, temporary file renamed
# over the real one, written to realpath so `home: repo` symlinks survive).
#
#   status.sh show [--json] [--no-live] [--dir <task dir>]
#   status.sh show --all [--json] [--live]
#   status.sh help
#   status.sh workers-in <worktree> [--json]
#   status.sh add-row <id> [k=v ...]
#   status.sh set <id> k=v [...]
#   status.sh set-root k=v [...]
#   status.sh promote <id>
#   status.sh ack <id>
#   status.sh gate <id> <name> done|open
#
# k=v values parse as JSON when they can, else as the literal string.
# WORK_DIR overrides the tasks root (~/.claude/work); LINEAGE_DIR the lineage
# records; GH_BIN_PATH the gh binary. See the header of status.py.
set -euo pipefail
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/status.py" "$@"
