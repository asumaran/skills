#!/usr/bin/env bash
# Lineage records for workers: ~/.claude/agent-lineage/<worker-name>.json.
# asagents reads them to draw who launched whom. Every write takes the
# record's lock (flock on <name>.lock, released by the kernel however the
# process ends), writes a temporary file and renames it over the record.
#
#   lineage.sh path   <worker-name>
#   lineage.sh launch <worker-name> --pane <id> --worktree <abs> \
#                     --kind ticket|pr|milestone --ref <ref> --title <title>
#       Run by the coordinator (/worker) right after `agent start`. Names the
#       coordinator if it has no name, waits up to 10 s for the worker's
#       session id, and writes the record (or updates pane/session on a relaunch).
#   lineage.sh state  <worker-name> running|blocked-on-user|finished [text]
#       Run by the worker. The text is the one-line result (required with
#       finished) or the pending question (optional with blocked-on-user).
#       Fills the worker's session id if it was still missing.
#
# LINEAGE_DIR overrides the directory; HERDR_BIN_PATH the herdr binary.
set -euo pipefail
exec python3 - "$@" <<'PY'
import datetime, fcntl, json, os, re, subprocess, sys, tempfile, time

DIR = os.environ.get("LINEAGE_DIR") or os.path.expanduser("~/.claude/agent-lineage")
HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"
STATES = ("running", "blocked-on-user", "finished")

def die(msg):
    print(f"lineage: {msg}", file=sys.stderr)
    sys.exit(1)

def now():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")

def herdr(*args):
    r = subprocess.run([HERDR, *args], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"herdr {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout

def snapshot():
    return json.loads(herdr("api", "snapshot"))["result"]["snapshot"]

def agent_in(snap, pane):
    return next((a for a in snap["agents"] if a.get("pane_id") == pane), None)

def session_of(agent):
    s = (agent or {}).get("agent_session") or {}
    return s.get("value") if s.get("kind") == "id" else None

def valid_name(name):
    # herdr's grammar (src/app/agents.rs, valid_agent_name)
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name):
        die(f"invalid worker name {name!r}: herdr wants a lowercase letter, then [a-z0-9_-], at most 32 characters")
    return name

def record_path(name):
    return os.path.join(DIR, valid_name(name) + ".json")

class Locked:
    """The record's lock, held while it is read, changed and renamed."""
    def __init__(self, name):
        os.makedirs(DIR, exist_ok=True)
        self.path = record_path(name)
        self.lock = open(os.path.join(DIR, name + ".lock"), "w")
    def __enter__(self):
        deadline = time.time() + 10
        while True:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() > deadline:
                    die(f"{self.path}: another writer holds the lock")
                time.sleep(0.1)
    def __exit__(self, *exc):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()
    def read(self):
        if not os.path.exists(self.path):
            return None
        try:
            with open(self.path) as f:
                return json.load(f)
        except ValueError as e:
            die(f"{self.path} is not valid JSON ({e}); fix or remove it by hand")
    def write(self, rec):
        rec["updated_at"] = now()
        fd, tmp = tempfile.mkstemp(dir=DIR, prefix=".tmp-")
        with os.fdopen(fd, "w") as f:
            json.dump(rec, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, self.path)

def coord_slug(label):
    s = re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-") or "workspace"
    return ("coord-" + s)[:32].rstrip("-")

def ensure_coordinator(snap):
    """The calling pane's agent, named coord-<workspace label> if it had no name."""
    pane = os.environ.get("HERDR_PANE_ID") or die("HERDR_PANE_ID is not set: run inside herdr")
    me = agent_in(snap, pane) or die(f"no agent detected in this pane ({pane})")
    ws = next((w for w in snap["workspaces"] if w["workspace_id"] == me["workspace_id"]), {})
    label = ws.get("label", "")
    name = me.get("name")
    if not name:
        taken = {a.get("name") for a in snap["agents"] if a.get("name")}
        base = coord_slug(label)
        name, n = base, 2
        while name in taken:
            suffix = f"-{n}"
            name, n = base[: 32 - len(suffix)].rstrip("-") + suffix, n + 1
        herdr("agent", "rename", pane, name)
    return {"name": name, "pane_id": pane, "session_id": session_of(me),
            "workspace_id": me["workspace_id"], "workspace_label": label}

def cmd_launch(args):
    if not args:
        die("launch needs a worker name")
    name, opts, rest = args[0], {}, args[1:]
    while rest:
        if len(rest) < 2 or not rest[0].startswith("--"):
            die(f"bad argument {rest[0]!r}")
        opts[rest[0][2:]] = rest[1]
        rest = rest[2:]
    for need in ("pane", "worktree", "kind", "ref", "title"):
        if need not in opts:
            die(f"launch needs --{need}")
    if opts["kind"] not in ("ticket", "pr", "milestone"):
        die("--kind is ticket, pr or milestone")
    snap = snapshot()
    coord = ensure_coordinator(snap)
    # agent start returns before the agent reports its session: wait a little.
    session, deadline = None, time.time() + 10
    while True:
        worker = agent_in(snap, opts["pane"])
        session = session_of(worker)
        if session or time.time() > deadline:
            break
        time.sleep(0.5)
        snap = snapshot()
    worker = worker or {}
    with Locked(name) as rec_file:
        rec = rec_file.read()
        identity = {"name": name, "pane_id": opts["pane"], "session_id": session,
                    "workspace_id": worker.get("workspace_id"), "worktree": opts["worktree"]}
        if rec:  # relaunch: coordinator and task stay as they were
            rec["worker"].update(identity)
            rec["state"], rec["summary"] = "running", ""
        else:
            rec = {"worker": identity, "coordinator": coord,
                   "task": {"kind": opts["kind"], "ref": opts["ref"], "title": opts["title"]},
                   "state": "running", "summary": "", "launched_at": now()}
        rec_file.write(rec)
    print(rec_file.path)
    if not session:
        print("lineage: the worker's session id is not known yet; its first `state` write fills it", file=sys.stderr)

def cmd_state(args):
    if len(args) < 2 or args[1] not in STATES:
        die(f"usage: state <worker-name> {'|'.join(STATES)} [summary]")
    name, state, summary = args[0], args[1], " ".join(args[2:])
    if state == "finished" and not summary:
        die("finished needs a one-line summary")
    with Locked(name) as rec_file:
        rec = rec_file.read() or die(f"no record at {rec_file.path}")
        rec["state"] = state
        # finished: the one-line result; blocked-on-user: the question, if given; running: nothing
        rec["summary"] = summary
        if not rec["worker"].get("session_id") and os.environ.get("HERDR_PANE_ID"):
            rec["worker"]["session_id"] = session_of(agent_in(snapshot(), os.environ["HERDR_PANE_ID"]))
        rec_file.write(rec)
    print(rec_file.path)

cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
if cmd == "path" and len(args) == 1:
    print(record_path(args[0]))
elif cmd == "launch":
    cmd_launch(args)
elif cmd == "state":
    cmd_state(args)
else:
    die("usage: lineage.sh path|launch|state ... (see the header of this script)")
PY
