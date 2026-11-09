#!/usr/bin/env bash
# work.sh: launch one asumaran/inbox item as an interactive Claude in herdr,
# in the item's account, repo and worktree. The single launcher used by
# `/todo work <n>` (skill todo) and by inbox-agent's dispatch.sh.
#
#   work.sh <n> [--dry-run] [--model <alias|id>] [--issue-json <file>]
#   work.sh <n> --set-status "<Status>"
#
#   <n>                 inbox issue number.
#   --dry-run           resolve everything and print it (account, repo, default
#                       branch, branch, worktree, agent, lineage mode and the
#                       rendered HANDOFF.md) without writing anything: no
#                       fetch, no branch, no worktree, no file, no GitHub write,
#                       no pane. Exit codes 3/4/6 apply as in a real run.
#   --model             passed to claude after `--` (default: claude's own).
#   --issue-json <file> read the issue from a file (the JSON of `gh issue view
#                       --json number,title,body,labels,url,comments,state,
#                       projectItems`) instead of GitHub; for tests and dry runs.
#   --set-status <S>    only move the item's Project #5 card to Status <S>
#                       (Inbox, Hoy, En progreso, Para ti, Hecho) and exit.
#                       A missing option or card is reported and exits 0.
#
# Real launch, in order (nothing on GitHub changes before step 5):
#   1. read the issue (ghp); refuse closed or in-progress items (exit 6).
#   2. account from `account:<x>` (missing: personal) -> ~/.claude or
#      ~/.claude-<x>; repo from the Origin `checkout:` path, else
#      `repo:<name>` -> ~/Developer/<name> or a path in ~/.claude/projects-map.md.
#      No repo -> exit 3. No "Done when" (body or comments) -> exit 4.
#   3. herdr reachable (`herdr workspace list`) or exit 5.
#   4. git fetch origin; default branch from origin/HEAD; `git branch
#      --no-track inbox-<n>-<slug> origin/<default>` (reused if it exists);
#      `wt new <branch> -e none -t`; HANDOFF.md from ../templates/HANDOFF.md,
#      listed in `git rev-parse --git-path info/exclude`; a free shell pane
#      in the worktree's workspace (or a new tab) with
#      `export CLAUDE_CONFIG_DIR=<account dir>` and the prompt confirmed back.
#   5. reserve: label in-progress, remove ready, comment "Picked up", Status
#      En progreso.
#   6. herdr agent start wk_inbox<n> --kind claude -- --permission-mode auto.
#      If it fails: revert step 5 (labels and Status as they were, comment
#      the error) and exit 1. Never a live worker on a dispatchable issue.
#   7. lineage: with HERDR_PANE_ID (a parent in herdr) `aswork-lineage launch
#      --kind task --ref inbox#<n>`; without it the boot prompt makes the
#      worker run `aswork-lineage self` first. A lineage failure only warns.
#   8. boot prompt, waiting only until the turn starts (not for the work).
#
# Exit codes (dispatch.sh contract):
#   0 launched (or dry run printed)       1 error (after a reservation: reverted,
#   2 usage                                 except a failed boot prompt, which
#   3 no repo resolved -> Para ti           keeps it: the agent is alive)
#   4 needs /aw:new (no done-when) -> Para ti
#   5 herdr not reachable: nothing written, the item stays ready
#   6 not launchable: closed or already in-progress
#
# Every call against asumaran/inbox goes through `ghp` (gh as asumaran).
# Issue titles and comments never go into a command string: comments are
# written with --body-file and argv carries the rest.
set -euo pipefail

INBOX=asumaran/inbox
PROJECT_OWNER=asumaran
PROJECT_NUMBER=5
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="$SCRIPT_DIR/$(basename "${BASH_SOURCE[0]}")"
# The path the worker calls later: the installed copy outlives a dev checkout.
INSTALLED="$HOME/.claude/skills/todo/scripts/work.sh"
WORK_SH="$SELF"; [[ -x "$INSTALLED" ]] && WORK_SH="$INSTALLED"
TEMPLATE="$SCRIPT_DIR/../templates/HANDOFF.md"

die()  { local code=$1; shift; printf 'work.sh: %s\n' "$*" >&2; exit "$code"; }
warn() { printf 'work.sh: warning: %s\n' "$*" >&2; }
note() { printf '%s\n' "$*" >&2; }

usage() { sed -n '2,22p' "$SELF" | sed 's/^# \{0,1\}//' >&2; exit 2; }

N="" DRY=0 MODEL="" ISSUE_JSON_FILE="" SET_STATUS=""
while (($#)); do
  case "$1" in
    --dry-run) DRY=1 ;;
    --model) MODEL="${2:?--model needs a value}"; shift ;;
    --issue-json) ISSUE_JSON_FILE="${2:?--issue-json needs a file}"; shift ;;
    --set-status) SET_STATUS="${2:?--set-status needs a Status name}"; shift ;;
    -h|--help) usage ;;
    -*) die 2 "unknown option: $1" ;;
    *) [[ -z "$N" ]] || die 2 "one issue number only"; N="$1" ;;
  esac
  shift
done
[[ "$N" =~ ^[0-9]+$ ]] || usage
command -v jq >/dev/null || die 1 "jq is required"
command -v python3 >/dev/null || die 1 "python3 is required"
if [[ -z "$ISSUE_JSON_FILE" || -n "$SET_STATUS" ]] || ((DRY == 0)); then
  command -v ghp >/dev/null || die 1 "ghp not found (gh as asumaran; dotfiles claude-code module)"
fi

# --- Project #5 Status ------------------------------------------------------
# Prints nothing on success; reports and returns 0 when the board, the card or
# the option is missing (labels and comments carry the state anyway).
project_set_status() {
  local num=$1 status=$2 pid fields fid oid item
  pid="$(ghp project view "$PROJECT_NUMBER" --owner "$PROJECT_OWNER" --format json --jq .id 2>/dev/null)" \
    || { warn "Project #$PROJECT_NUMBER not reachable; Status not set"; return 0; }
  fields="$(ghp project field-list "$PROJECT_NUMBER" --owner "$PROJECT_OWNER" --format json 2>/dev/null)" || fields=""
  fid="$(jq -r '.fields[]? | select(.name=="Status") | .id' <<<"$fields")"
  oid="$(jq -r --arg o "$status" '.fields[]? | select(.name=="Status") | .options[]? | select(.name==$o) | .id' <<<"$fields" | head -1)"
  if [[ -z "$fid" || -z "$oid" ]]; then
    note "Project #$PROJECT_NUMBER has no Status option \"$status\" yet; the labels and the comment carry the state."
    return 0
  fi
  item="$(ghp project item-list "$PROJECT_NUMBER" --owner "$PROJECT_OWNER" --format json --limit 500 2>/dev/null \
    | jq -r --arg r "$INBOX" --arg n "$num" '.items[] | select(.content.repository==$r and (.content.number|tostring)==$n) | .id' | head -1)" || item=""
  if [[ -z "$item" ]]; then
    note "inbox #$num is not on Project #$PROJECT_NUMBER; Status not set."
    return 0
  fi
  ghp project item-edit --project-id "$pid" --id "$item" --field-id "$fid" --single-select-option-id "$oid" >/dev/null \
    || { warn "could not set Status \"$status\" on inbox #$num"; return 0; }
}

if [[ -n "$SET_STATUS" ]]; then
  project_set_status "$N" "$SET_STATUS"
  exit 0
fi

# --- 1. The issue -------------------------------------------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [[ -n "$ISSUE_JSON_FILE" ]]; then
  cp "$ISSUE_JSON_FILE" "$TMP/issue.json"
else
  # projectItems needs the read:project scope: without it, read the rest.
  ghp issue view "$N" -R "$INBOX" --json number,title,body,labels,url,comments,state,projectItems >"$TMP/issue.json" 2>/dev/null \
    || ghp issue view "$N" -R "$INBOX" --json number,title,body,labels,url,comments,state >"$TMP/issue.json" \
    || die 1 "could not read inbox #$N"
fi
J="$TMP/issue.json"
jq -e '.title | type == "string"' "$J" >/dev/null 2>&1 || die 1 "inbox #$N: the issue JSON is unreadable or has no title"
jqr() { jq -r "$@" "$J"; }

TITLE="$(jqr '.title')"
URL="$(jqr '.url // ""')"
STATE="$(jqr '.state // "OPEN"')"
has_label() { jq -e --arg l "$1" '[.labels[]?.name] | index($l) != null' "$J" >/dev/null; }
# shellcheck disable=SC2016 # $p is a jq variable
label_value() { jqr --arg p "$1" '[.labels[]?.name | select(startswith($p)) | ltrimstr($p)] | first // ""'; }
PRIOR_STATUS="$(jqr '[.projectItems[]? | select(.title=="Inbox") | .status.name // empty] | first // ""')"

[[ "$STATE" == OPEN ]] || die 6 "inbox #$N is $STATE: nothing to launch"
has_label in-progress && die 6 "inbox #$N is already in-progress: a worker has it"
HAD_READY=0; has_label ready && HAD_READY=1

# --- 2. Account, repo, done-when ---------------------------------------------
ACCOUNT="$(label_value account:)"; ACCOUNT="${ACCOUNT:-personal}"
[[ "$ACCOUNT" =~ ^[a-z0-9-]+$ ]] || die 1 "bad account label: account:$ACCOUNT"
if [[ "$ACCOUNT" == personal ]]; then ACCOUNT_DIR="$HOME/.claude"; else ACCOUNT_DIR="$HOME/.claude-$ACCOUNT"; fi
[[ -d "$ACCOUNT_DIR" ]] || die 1 "account dir $ACCOUNT_DIR does not exist (label account:$ACCOUNT)"

REPO_NAME="$(label_value repo:)"
[[ -z "$REPO_NAME" || "$REPO_NAME" =~ ^[A-Za-z0-9._-]+$ ]] || die 1 "bad repo label: repo:$REPO_NAME"
# Origin block, "- checkout: <path>" (the capture format of `/todo <text>`).
CHECKOUT="$(jqr '.body // "" | [splits("\n") | select(test("^\\s*-\\s*checkout:\\s*"; "i")) | sub("^\\s*-\\s*checkout:\\s*"; "i") | sub("\\s+$"; "")] | first // ""')"
CHECKOUT="${CHECKOUT/#\~/$HOME}"

is_repo() { [[ -n "$1" && -d "$1" ]] && git -C "$1" rev-parse --git-dir >/dev/null 2>&1; }
REPO=""
if [[ -n "$CHECKOUT" && "$CHECKOUT" != none ]] && is_repo "$CHECKOUT"; then
  REPO="$(cd "$CHECKOUT" && dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
  # A checkout that is not the labeled repo loses to the label.
  [[ -n "$REPO_NAME" && "$(basename "$REPO")" != "$REPO_NAME" ]] && REPO=""
fi
if [[ -z "$REPO" && -n "$REPO_NAME" ]]; then
  if is_repo "$HOME/Developer/$REPO_NAME"; then
    REPO="$HOME/Developer/$REPO_NAME"
  elif [[ -f "$HOME/.claude/projects-map.md" ]]; then
    cand="$(grep -o "\`~/[^\`]*/$REPO_NAME\`" "$HOME/.claude/projects-map.md" | head -1 | tr -d '`')" || cand=""
    cand="${cand/#\~/$HOME}"
    is_repo "$cand" && REPO="$cand"
  fi
fi
if [[ -z "$REPO" ]]; then
  die 3 "inbox #$N has no repo to work in (repo label: ${REPO_NAME:-none}, checkout: ${CHECKOUT:-none}): needs /aw:new or is not repo work"
fi
REPO_SLUG="$(git -C "$REPO" remote get-url origin 2>/dev/null | sed -E 's#^(git@[^:]+:|ssh://[^/]+/|https?://[^/]+/)##; s#\.git$##')" || REPO_SLUG=""
REPO_OWNER="${REPO_SLUG%%/*}"

# A done-when: "Done when" in the body (capture format, pulse Origin) or in a
# comment (the triage brief). Size beyond that is the caller's judgment.
if ! jq -e '[.body // "", (.comments[]?.body // "")] | any(test("done[ -]when"; "i"))' "$J" >/dev/null; then
  die 4 "inbox #$N has no done-when (body or triage brief): needs /aw:new or a brief"
fi

# --- Names --------------------------------------------------------------------
SLUG="$(python3 -I -c '
import re, sys, unicodedata
t = unicodedata.normalize("NFKD", sys.argv[1]).encode("ascii", "ignore").decode().lower()
words = [w for w in re.split(r"[^a-z0-9]+", t) if w]
out = ""
for w in words:
    if len(out) + len(w) + (1 if out else 0) > 40: break
    out = f"{out}-{w}" if out else w
print(out or "item")
' "$TITLE")"
BRANCH="inbox-$N-$SLUG"
AGENT="wk_inbox$N"
# A title safe to quote in a shell line typed by the worker (lineage self).
SAFE_TITLE="$(python3 -I -c '
import sys
print("".join(c for c in sys.argv[1] if c.isalnum() or c in " .,:#()/_-").strip()[:100])
' "$TITLE")"

DEFAULT_BRANCH="$(git -C "$REPO" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')" || DEFAULT_BRANCH=""
if [[ -z "$DEFAULT_BRANCH" ]]; then
  DEFAULT_BRANCH="$(git -C "$REPO" ls-remote --symref origin HEAD 2>/dev/null | awk '/^ref:/ {sub("refs/heads/","",$2); print $2; exit}')" || DEFAULT_BRANCH=""
fi
[[ -n "$DEFAULT_BRANCH" ]] || die 1 "cannot resolve the default branch of $REPO (origin/HEAD)"

WORKTREE="$(cd "$REPO" && wt path "$BRANCH")" || die 1 "wt path failed in $REPO"

if [[ -n "${HERDR_PANE_ID:-}" ]]; then
  LINEAGE_MODE=launch
  FIRST_ACTION="Nothing to declare: the launcher wrote your lineage record (\`aswork-lineage launch\`, ref \`inbox#$N\`). Start with the item."
  SELF_LINE=""
else
  LINEAGE_MODE=self
  SELF_LINE="aswork-lineage self --kind task --ref 'inbox#$N' --title '$SAFE_TITLE'"
  FIRST_ACTION="Declare yourself in asagents before anything else (you were launched without a parent in herdr, so you are a root grouped by the ref):

\`\`\`bash
$SELF_LINE
\`\`\`"
fi

if [[ "$REPO_OWNER" == asumaran ]]; then
  FINISH_QUESTION="\"¿Mergeo \`$BRANCH\` a \`$DEFAULT_BRANCH\`?\" (recommended: yes)."
  FINISH_ACTION="merge into \`$DEFAULT_BRANCH\` locally with the \`worktree\` skill (\`wt merge\`, section \"Integrating the work back into main\"). Do not push."
else
  FINISH_QUESTION="\"¿Abro el PR (draft)?\" (recommended: yes)."
  FINISH_ACTION="push \`$BRANCH\` and open a DRAFT PR against \`$DEFAULT_BRANCH\` with this repo's PR rules (its \`CLAUDE.md\`, \`/asdev:pre-pr\` when the repo uses it). Never take it out of draft."
fi

render_handoff() {
  TPL_NUMBER="$N" TPL_TITLE="$TITLE" TPL_URL="$URL" TPL_DATE="$(date +%F)" \
  TPL_AGENT="$AGENT" TPL_WORKTREE="$WORKTREE" TPL_BRANCH="$BRANCH" \
  TPL_DEFAULT_BRANCH="$DEFAULT_BRANCH" TPL_REPO="$REPO" TPL_REPO_SLUG="${REPO_SLUG:-unknown}" \
  TPL_ACCOUNT="$ACCOUNT" TPL_ACCOUNT_DIR="$ACCOUNT_DIR" TPL_WORK_SH="$WORK_SH" \
  TPL_FIRST_ACTION="$FIRST_ACTION" TPL_FINISH_QUESTION="$FINISH_QUESTION" TPL_FINISH_ACTION="$FINISH_ACTION" \
  python3 -I -c '
import json, os, re, sys
issue = json.load(open(sys.argv[2]))
vals = {k[4:]: v for k, v in os.environ.items() if k.startswith("TPL_")}
vals["BODY"] = (issue.get("body") or "").strip() or "(empty)"
cs = issue.get("comments") or []
vals["COMMENTS"] = "\n\n".join(
    "### {} · {}\n\n{}".format((c.get("author") or {}).get("login", "?"), c.get("createdAt", ""), (c.get("body") or "").strip())
    for c in cs) or "(none)"
tpl = open(sys.argv[1]).read()
sys.stdout.write(re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: vals.get(m.group(1), m.group(0)), tpl))
' "$TEMPLATE" "$J"
}

BOOT_PROMPT="Eres el worker del item inbox#$N ($URL) en $WORKTREE, cuenta $ACCOUNT. Lee entero $WORKTREE/HANDOFF.md y trabaja el item según su sección Authority; termina con la única pregunta de su sección Finish, o con la de bloqueo si no puedes."
[[ -n "$SELF_LINE" ]] && BOOT_PROMPT="$BOOT_PROMPT Tu primera acción: $SELF_LINE"

CLAUDE_ARGS=(--permission-mode auto)
[[ -n "$MODEL" ]] && CLAUDE_ARGS+=(--model "$MODEL")

# --- Dry run --------------------------------------------------------------------
if ((DRY)); then
  branch_state=new; git -C "$REPO" show-ref --verify --quiet "refs/heads/$BRANCH" && branch_state="exists (reused)"
  wt_state=new; [[ -d "$WORKTREE" ]] && wt_state="exists (reused)"
  herdr_state="reachable"; herdr workspace list >/dev/null 2>&1 || herdr_state="NOT reachable (a real run exits 5)"
  cat <<EOF
work.sh dry run: inbox #$N (nothing written)
  title:          $TITLE
  url:            $URL
  account:        $ACCOUNT ($ACCOUNT_DIR)
  repo:           ${REPO_SLUG:-unknown} ($REPO)
  default branch: $DEFAULT_BRANCH (origin/HEAD, not fetched in a dry run)
  branch:         $BRANCH [$branch_state] from origin/$DEFAULT_BRANCH
  worktree:       $WORKTREE [$wt_state]
  agent:          $AGENT, claude ${CLAUDE_ARGS[*]}
  lineage:        $LINEAGE_MODE (ref inbox#$N)
  herdr:          $herdr_state
  labels now:     $(jqr '[.labels[]?.name] | join(",")')
  status now:     ${PRIOR_STATUS:-not on the board}

A real run would:
  git -C $REPO fetch origin
  git -C $REPO branch --no-track $BRANCH origin/$DEFAULT_BRANCH
  (cd $REPO && wt new $BRANCH -e none -t)
  write $WORKTREE/HANDOFF.md; add HANDOFF.md to \$(git rev-parse --git-path info/exclude)
  herdr pane run <free pane of the worktree> "export CLAUDE_CONFIG_DIR=$ACCOUNT_DIR; printf ..." and wait for it
  ghp issue edit $N -R $INBOX --add-label in-progress$( ((HAD_READY)) && printf ' --remove-label ready')
  ghp issue comment $N -R $INBOX --body-file <"Picked up: $WORKTREE, $ACCOUNT account">
  Project #$PROJECT_NUMBER Status -> En progreso
  herdr agent start $AGENT --kind claude --pane <pane> -- ${CLAUDE_ARGS[*]}
  $( [[ $LINEAGE_MODE == launch ]] && printf 'aswork-lineage launch %s --pane <pane> --worktree %s --kind task --ref inbox#%s --title <title>' "$AGENT" "$WORKTREE" "$N" || printf '(no launch: the worker runs aswork-lineage self first)')
  herdr agent prompt $AGENT <boot prompt> --wait --until working --until blocked

Boot prompt:
$BOOT_PROMPT

----- HANDOFF.md -----
EOF
  render_handoff
  exit 0
fi

# --- 3. herdr -------------------------------------------------------------------
if ! command -v herdr >/dev/null || ! herdr workspace list >/dev/null 2>&1; then
  die 5 "herdr is not reachable: inbox #$N left as it was"
fi

# --- 4. Branch, worktree, HANDOFF, pane ----------------------------------------
git -C "$REPO" fetch origin --quiet || die 1 "git fetch origin failed in $REPO"
if ! git -C "$REPO" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git -C "$REPO" branch --no-track "$BRANCH" "origin/$DEFAULT_BRANCH" || die 1 "could not create $BRANCH"
fi
WT_WAS_NEW=1; [[ -d "$WORKTREE" ]] && WT_WAS_NEW=0
(cd "$REPO" && wt new "$BRANCH" -e none -t </dev/null) || die 1 "wt new $BRANCH failed in $REPO (a dirty main checkout makes wt ask: run it by hand once)"
WORKTREE="$(cd "$REPO" && wt path "$BRANCH")"
[[ -d "$WORKTREE" ]] || die 1 "worktree $WORKTREE was not created"

render_handoff >"$WORKTREE/HANDOFF.md"
EXCLUDE="$(git -C "$WORKTREE" rev-parse --path-format=absolute --git-path info/exclude)"
mkdir -p "$(dirname "$EXCLUDE")"
# Anchored: only the worktree root's HANDOFF.md, never a tracked one deeper.
if grep -qxF HANDOFF.md "$EXCLUDE" 2>/dev/null; then
  sed -i.bak 's#^HANDOFF\.md$#/HANDOFF.md#' "$EXCLUDE" && rm -f "$EXCLUDE.bak"
fi
grep -qxF /HANDOFF.md "$EXCLUDE" 2>/dev/null || printf '/HANDOFF.md\n' >>"$EXCLUDE"

find_ws() { herdr workspace list 2>/dev/null | jq -r --arg w "$WORKTREE" '.result.workspaces[]? | select(.worktree.checkout_path==$w) | .workspace_id' | head -1; }
WS="$(find_ws)"
if [[ -z "$WS" ]]; then
  herdr worktree open --cwd "$REPO" --path "$WORKTREE" >/dev/null 2>&1 || true
  WS="$(find_ws)"
fi
[[ -n "$WS" ]] || die 1 "no herdr workspace for $WORKTREE"

# Reuse only the root shell of a workspace wt just created; a reused worktree
# may have panes running editors or servers, so it gets a new tab instead.
PANE=""
if ((WT_WAS_NEW)); then
  PANE="$(herdr pane list --workspace "$WS" 2>/dev/null \
    | jq -r --arg w "$WORKTREE" '.result.panes[]? | select((.agent // null) == null and .cwd == $w) | .pane_id' | head -1)" || PANE=""
fi
if [[ -z "$PANE" ]]; then
  PANE="$(herdr tab create --workspace "$WS" --cwd "$WORKTREE" --label "Inbox #$N" --env "CLAUDE_CONFIG_DIR=$ACCOUNT_DIR" 2>/dev/null \
    | jq -r '.result.root_pane.pane_id // empty')" || PANE=""
fi
[[ -n "$PANE" ]] || die 1 "no free pane in workspace $WS"

# Account into the pane, always explicit (references/launching.md), then make
# sure the prompt came back: the marker only appears in the command's output.
TOKEN="$RANDOM$RANDOM"
herdr pane run "$PANE" "export CLAUDE_CONFIG_DIR=$ACCOUNT_DIR; printf 'work-sh-%s\\n' $TOKEN" >/dev/null \
  || die 1 "could not type into pane $PANE"
herdr pane wait-output "$PANE" --match "work-sh-$TOKEN" --timeout 15000 >/dev/null 2>&1 \
  || die 1 "pane $PANE did not return to its prompt"

# --- 5. Reserve -------------------------------------------------------------------
# Last look before writing: another launch may have taken the item meanwhile
# (wt setup scripts can take minutes), and the agent name must be free so a
# failed start below always means OUR start failed.
if herdr agent get "$AGENT" >/dev/null 2>&1; then
  die 6 "an agent named $AGENT already exists: inbox #$N is being worked"
fi
if ghp issue view "$N" -R "$INBOX" --json labels -q '[.labels[].name] | index("in-progress") != null' 2>/dev/null | grep -qx true; then
  die 6 "inbox #$N became in-progress while launching: another launch has it"
fi
reserve_edit=(--add-label in-progress); ((HAD_READY)) && reserve_edit+=(--remove-label ready)
ghp issue edit "$N" -R "$INBOX" "${reserve_edit[@]}" >/dev/null || die 1 "could not label inbox #$N in-progress"
printf 'Picked up: %s, %s account (agent %s).\n' "$WORKTREE" "$ACCOUNT" "$AGENT" >"$TMP/picked.md"
ghp issue comment "$N" -R "$INBOX" --body-file "$TMP/picked.md" >/dev/null || warn "could not comment on inbox #$N"
project_set_status "$N" "En progreso"

revert() {
  local why=$1
  local undo=(--remove-label in-progress); ((HAD_READY)) && undo+=(--add-label ready)
  ghp issue edit "$N" -R "$INBOX" "${undo[@]}" >/dev/null || warn "revert: could not restore the labels of inbox #$N"
  printf 'Launch failed, item left as it was: %s\n' "$why" >"$TMP/failed.md"
  ghp issue comment "$N" -R "$INBOX" --body-file "$TMP/failed.md" >/dev/null || warn "revert: could not comment on inbox #$N"
  local back="$PRIOR_STATUS"; [[ -n "$back" ]] || { ((HAD_READY)) && back=Hoy || back=Inbox; }
  project_set_status "$N" "$back"
  die 1 "$why (reverted)"
}

# --- 6. Agent ---------------------------------------------------------------------
herdr agent start "$AGENT" --kind claude --pane "$PANE" -- "${CLAUDE_ARGS[@]}" >"$TMP/start.json" 2>&1 \
  || revert "herdr agent start $AGENT in pane $PANE failed: $(tr '\n' ' ' <"$TMP/start.json" | cut -c1-300)"

# --- 7. Lineage -------------------------------------------------------------------
if [[ "$LINEAGE_MODE" == launch ]]; then
  aswork-lineage launch "$AGENT" --pane "$PANE" --worktree "$WORKTREE" \
    --kind task --ref "inbox#$N" --title "$TITLE" >/dev/null 2>&1 \
    || warn "aswork-lineage launch failed: the worker runs without a lineage record"
fi

# --- 8. Boot prompt ----------------------------------------------------------------
if ! herdr agent prompt "$AGENT" "$BOOT_PROMPT" --wait --until working --until blocked --timeout 60000 >/dev/null 2>&1; then
  die 1 "agent $AGENT is running in pane $PANE but the boot prompt was not confirmed; inbox #$N stays in-progress. Check the pane and send: $BOOT_PROMPT"
fi

printf 'inbox #%s launched\n  workspace: %s\n  pane:      %s\n  agent:     %s\n  worktree:  %s\n  account:   %s\n' \
  "$N" "$WS" "$PANE" "$AGENT" "$WORKTREE" "$ACCOUNT"
