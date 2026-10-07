#!/usr/bin/env bash
# Fixture tests for skills/worker/lineage.sh: pane check on `state`,
# --kind task|other on `launch`, and the reparent in `self`. Everything runs
# against a temp LINEAGE_DIR and a fake herdr (HERDR_BIN_PATH); nothing
# touches ~/.claude. Run: bash tests/lineage_test.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LINEAGE="$REPO/skills/worker/lineage.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export LINEAGE_DIR="$TMP/lineage"
export HERDR_BIN_PATH="$TMP/herdr"
export HERDR_FAKE_SNAPSHOT="$TMP/snapshot.json"
export HERDR_FAKE_LOG="$TMP/herdr.log"
: > "$HERDR_FAKE_LOG"

cat > "$HERDR_BIN_PATH" <<'EOF'
#!/usr/bin/env bash
case "$1 $2" in
  "api snapshot") cat "$HERDR_FAKE_SNAPSHOT" ;;
  "agent rename") exit 0 ;;
  "agent prompt") printf 'prompt %s :: %s\n' "$3" "$4" >> "$HERDR_FAKE_LOG" ;;
  *) echo "fake herdr: unknown $*" >&2; exit 1 ;;
esac
EOF
chmod +x "$HERDR_BIN_PATH"

snapshot() { # <coord session id>
  python3 - "$1" > "$HERDR_FAKE_SNAPSHOT" <<'EOF'
import json, sys
coord_session = sys.argv[1]
print(json.dumps({"result": {"snapshot": {
  "workspaces": [{"workspace_id": "w1", "label": "work"}],
  "agents": [
    {"pane_id": "p1", "name": "coord-x", "workspace_id": "w1", "cwd": "/tmp",
     "agent_session": {"kind": "id", "value": coord_session}},
    {"pane_id": "p2", "name": "w-test", "workspace_id": "w1", "cwd": "/tmp/wt",
     "agent_session": {"kind": "id", "value": "s-worker"}},
  ]}}}))
EOF
}

field() { # <record name> <dotted path>
  python3 - "$LINEAGE_DIR/$1.json" "$2" <<'EOF'
import json, sys
rec = json.load(open(sys.argv[1]))
for part in sys.argv[2].split("."):
    rec = rec[part]
print(rec)
EOF
}

FAILS=0
ok()   { echo "ok: $1"; }
fail() { echo "FAIL: $1" >&2; FAILS=$((FAILS + 1)); }
expect_fail() { # <description> <args...>
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then fail "$desc (should have failed)"; else ok "$desc"; fi
}

snapshot "s-coord-1"

# --- self declares the coordinator, launch accepts --kind task -------------
HERDR_PANE_ID=p1 "$LINEAGE" self --kind task --ref ESHOP-1 --title "T" >/dev/null
[ -f "$LINEAGE_DIR/coord-x.json" ] && ok "self writes the record" || fail "self record missing"

HERDR_PANE_ID=p1 "$LINEAGE" launch w-test --pane p2 --worktree /tmp/wt \
  --kind task --ref "ESHOP-1#F" --title "F" >/dev/null
[ "$(field w-test task.kind)" = "task" ] && ok "launch --kind task" || fail "launch kind"
[ "$(field w-test parent.name)" = "coord-x" ] && ok "parent recorded" || fail "parent"
[ "$(field w-test parent.session_id)" = "s-coord-1" ] && ok "parent session" || fail "parent session"

expect_fail "launch rejects a bogus kind" \
  env HERDR_PANE_ID=p1 "$LINEAGE" launch w-bogus --pane p2 --worktree /tmp/wt \
  --kind bogus --ref x --title x

# --- state checks the pane --------------------------------------------------
expect_fail "state from another pane is rejected" \
  env HERDR_PANE_ID=p9 "$LINEAGE" state w-test running
expect_fail "state without HERDR_PANE_ID is rejected" \
  env -u HERDR_PANE_ID "$LINEAGE" state w-test running
HERDR_PANE_ID=p9 "$LINEAGE" state w-test running --force >/dev/null \
  && ok "--force overrides the pane check" || fail "--force"
HERDR_PANE_ID=p2 "$LINEAGE" state w-test blocked-on-user "which env?" >/dev/null \
  && ok "state from the record's pane" || fail "state own pane"
[ "$(field w-test state)" = "blocked-on-user" ] && ok "state written" || fail "state value"

# --- finished notifies the parent -------------------------------------------
HERDR_PANE_ID=p2 "$LINEAGE" state w-test finished "all done" >/dev/null
grep -q "prompt coord-x :: \[worker w-test\] terminó: all done" "$HERDR_FAKE_LOG" \
  && ok "finished prompts the parent" || fail "parent notice"

# --- self reparents the children after a /clear ------------------------------
snapshot "s-coord-2"
OUT="$(HERDR_PANE_ID=p1 "$LINEAGE" self --kind task --ref ESHOP-1 --title "T")"
[ "$(field w-test parent.session_id)" = "s-coord-2" ] \
  && ok "child parent.session_id refreshed" || fail "reparent session"
[ "$(field w-test parent.pane_id)" = "p1" ] && ok "child parent.pane_id kept" || fail "reparent pane"
echo "$OUT" | grep -q "reparented 1 child" && ok "reparent reported" || fail "reparent output"
# idempotent: a second self reparents nothing
OUT="$(HERDR_PANE_ID=p1 "$LINEAGE" self --kind task --ref ESHOP-1 --title "T")"
echo "$OUT" | grep -q reparented && fail "reparent not idempotent" || ok "reparent idempotent"

# --- explicit reparent --------------------------------------------------------
# w-orphan was never recorded by its launcher: it declares itself (parent null)
# and is then adopted under coord-x with `reparent`.
cat > "$LINEAGE_DIR/w-orphan.json" <<'JSON'
{"agent":{"name":"w-orphan","pane_id":"p5","session_id":"s-orphan","workspace_id":"w1","worktree":"/tmp/o"},
 "parent":null,"task":{"kind":"other","ref":"X","title":"orphan","plan":""},
 "state":"blocked-on-user","summary":"a question","launched_at":"t","version":2,"updated_at":"t"}
JSON
"$LINEAGE" reparent w-orphan --parent coord-x >/dev/null \
  && ok "reparent writes" || fail "reparent run"
[ "$(field w-orphan parent.name)" = "coord-x" ] && ok "reparent parent.name" || fail "reparent name"
[ "$(field w-orphan parent.session_id)" = "s-coord-2" ] \
  && ok "reparent parent.session from the record" || fail "reparent session"
[ "$(field w-orphan parent.workspace_label)" = "work" ] \
  && ok "reparent workspace label from herdr" || fail "reparent label"
[ "$(field w-orphan state)" = "blocked-on-user" ] && [ "$(field w-orphan task.ref)" = "X" ] \
  && ok "reparent keeps task and state" || fail "reparent preserved fields"
expect_fail "reparent to itself is rejected" "$LINEAGE" reparent w-orphan --parent w-orphan
expect_fail "reparent to a missing record is rejected" "$LINEAGE" reparent w-orphan --parent w-ghost
# cycle: w-mid hangs under w-orphan; w-orphan may not then hang under w-mid
cat > "$LINEAGE_DIR/w-mid.json" <<'JSON'
{"agent":{"name":"w-mid","pane_id":"p6","session_id":"s-mid","workspace_id":"w1","worktree":"/tmp/m"},
 "parent":{"name":"w-orphan","pane_id":"p5","session_id":"s-orphan","workspace_id":"w1","workspace_label":"work"},
 "task":{"kind":"other","ref":"X#m","title":"mid","plan":""},
 "state":"running","summary":"","launched_at":"t","version":2,"updated_at":"t"}
JSON
expect_fail "reparent refuses a cycle" "$LINEAGE" reparent w-orphan --parent w-mid

if [ "$FAILS" -gt 0 ]; then echo "$FAILS failure(s)"; exit 1; fi
echo "all lineage tests passed"
