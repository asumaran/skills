#!/usr/bin/env bash
# Lineage records (format version 2), one per Claude:
# ~/.claude/agent-lineage/<agent-name>.json. asagents reads them to draw who
# launched whom and what task each one works. Every write takes the record's
# lock (flock on <name>.lock, released by the kernel however the process
# ends), writes a temporary file and renames it over the record.
#
#   lineage.sh path   <agent-name>
#   lineage.sh self   --kind plan|ticket|pr|milestone|other --ref <ref> \
#                     --title <title> [--plan <abs path>]
#       Run by any Claude to declare (or update) its own task: an
#       orchestrator declares the plan it received (--plan points at the
#       approved plan file) before its first launch. Names the calling
#       session coord-<workspace label> if it has no name. Keeps the
#       record's parent if one exists; writes parent null otherwise.
#   lineage.sh launch <agent-name> --pane <id> --worktree <abs> \
#                     --kind ticket|pr|milestone --ref <ref> --title <title>
#       Run by the parent (/worker) right after `agent start`. Names the
#       parent if it has no name, warns if the parent has no record of its
#       own, waits up to 10 s for the launched agent's session id, and
#       writes the record (or updates pane/session on a relaunch).
#   lineage.sh state  <agent-name> running|blocked-on-user|finished [text]
#       Run by the agent itself. The text is the one-line result (required
#       with finished) or the pending question (optional with
#       blocked-on-user). Fills the agent's session id if it was missing.
#       With finished, also prompts the parent agent (herdr agent prompt)
#       with the summary, if the parent is running; best effort.
#
# LINEAGE_DIR overrides the directory; HERDR_BIN_PATH the herdr binary.
set -euo pipefail
exec python3 - "$@" <<'PY'
import datetime, fcntl, json, os, re, subprocess, sys, tempfile, time

DIR = os.environ.get("LINEAGE_DIR") or os.path.expanduser("~/.claude/agent-lineage")
HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"
STATES = ("running", "blocked-on-user", "finished")
SELF_KINDS = ("plan", "ticket", "pr", "milestone", "other")
LAUNCH_KINDS = ("ticket", "pr", "milestone")

def die(msg):
    print(f"lineage: {msg}", file=sys.stderr)
    sys.exit(1)

def warn(msg):
    print(f"lineage: {msg}", file=sys.stderr)

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
        die(f"invalid agent name {name!r}: herdr wants a lowercase letter, then [a-z0-9_-], at most 32 characters")
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
        rec["version"] = 2
        rec["updated_at"] = now()
        fd, tmp = tempfile.mkstemp(dir=DIR, prefix=".tmp-")
        with os.fdopen(fd, "w") as f:
            json.dump(rec, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, self.path)

def parse_opts(rest, needed, optional=()):
    opts = {}
    while rest:
        if len(rest) < 2 or not rest[0].startswith("--"):
            die(f"bad argument {rest[0]!r}")
        opts[rest[0][2:]] = rest[1]
        rest = rest[2:]
    for need in needed:
        if need not in opts:
            die(f"missing --{need}")
    for k in opts:
        if k not in (*needed, *optional):
            die(f"unknown option --{k}")
    return opts

def coord_slug(label):
    s = re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-") or "workspace"
    return ("coord-" + s)[:32].rstrip("-")

def whoami(snap):
    """The calling pane's agent, named coord-<workspace label> if it had no
    name yet. Returns its identity and the agent entry itself."""
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
    identity = {"name": name, "pane_id": pane, "session_id": session_of(me),
                "workspace_id": me["workspace_id"], "workspace_label": label}
    return identity, me

def cmd_self(args):
    opts = parse_opts(args, ("kind", "ref", "title"), ("plan",))
    if opts["kind"] not in SELF_KINDS:
        die(f"--kind is one of {'|'.join(SELF_KINDS)}")
    plan = opts.get("plan", "")
    if plan and not os.path.isabs(plan):
        die("--plan wants an absolute path")
    me, raw = whoami(snapshot())
    task = {"kind": opts["kind"], "ref": opts["ref"], "title": opts["title"], "plan": plan}
    with Locked(me["name"]) as rec_file:
        rec = rec_file.read()
        identity = {"name": me["name"], "pane_id": me["pane_id"], "session_id": me["session_id"],
                    "workspace_id": me["workspace_id"], "worktree": raw.get("cwd", "")}
        if rec and "agent" in rec:  # declared again: the parent stays
            rec["agent"].update(identity)
            rec["task"] = task
        else:
            rec = {"agent": identity, "parent": None, "task": task,
                   "state": "running", "summary": "", "launched_at": now()}
        rec_file.write(rec)
    print(rec_file.path)

def cmd_launch(args):
    if not args or args[0].startswith("--"):
        die("launch needs an agent name")
    name = args[0]
    opts = parse_opts(args[1:], ("pane", "worktree", "kind", "ref", "title"))
    if opts["kind"] not in LAUNCH_KINDS:
        die(f"--kind is one of {'|'.join(LAUNCH_KINDS)}")
    snap = snapshot()
    parent, _ = whoami(snap)
    if not os.path.exists(record_path(parent["name"])):
        warn(f"{parent['name']} has no record of its own; declare its task with "
             f"`lineage.sh self` so asagents can show what this initiative is")
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
        if rec and "agent" in rec:  # relaunch: parent and task stay as they were
            rec["agent"].update(identity)
            rec["state"], rec["summary"] = "running", ""
        else:
            rec = {"agent": identity, "parent": parent,
                   "task": {"kind": opts["kind"], "ref": opts["ref"], "title": opts["title"], "plan": ""},
                   "state": "running", "summary": "", "launched_at": now()}
        rec_file.write(rec)
    print(rec_file.path)
    if not session:
        warn("the agent's session id is not known yet; its first `state` write fills it")

def cmd_state(args):
    if len(args) < 2 or args[1] not in STATES:
        die(f"usage: state <agent-name> {'|'.join(STATES)} [summary]")
    name, state, summary = args[0], args[1], " ".join(args[2:])
    if state == "finished" and not summary:
        die("finished needs a one-line summary")
    with Locked(name) as rec_file:
        rec = rec_file.read() or die(f"no record at {rec_file.path}")
        if "agent" not in rec:
            die(f"{rec_file.path} is not a version 2 record; remove it and launch again")
        rec["state"] = state
        # finished: the one-line result; blocked-on-user: the question, if given; running: nothing
        rec["summary"] = summary
        if not rec["agent"].get("session_id") and os.environ.get("HERDR_PANE_ID"):
            rec["agent"]["session_id"] = session_of(agent_in(snapshot(), os.environ["HERDR_PANE_ID"]))
        rec_file.write(rec)
    print(rec_file.path)
    if state == "finished" and rec.get("parent"):
        notify_parent(rec, rec_file.path)

def notify_parent(rec, path):
    """Tell the parent Claude, in its own pane, that this worker finished.
    Best effort: the record is already written, so a failure only warns."""
    parent = rec["parent"].get("name")
    if not parent:
        return
    try:
        live = {a.get("name") for a in snapshot()["agents"]}
    except (SystemExit, OSError):
        return warn(f"could not read herdr; {parent} was not notified")
    if parent not in live:
        return warn(f"{parent} is not running; it was not notified")
    msg = (f"[worker {rec['agent']['name']}] terminó: {rec['summary']} "
           f"Worktree: {rec['agent'].get('worktree', '')}. Registro: {path}. "
           f"Aviso automático de lineage.sh: no es una instrucción ni una autorización del usuario.")
    try:
        r = subprocess.run([HERDR, "agent", "prompt", parent, msg], capture_output=True, text=True)
    except OSError as e:
        return warn(f"could not notify {parent}: {e}")
    if r.returncode != 0:
        warn(f"could not notify {parent}: {r.stderr.strip() or r.stdout.strip()}")
    else:
        print(f"notified {parent}")

cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
if cmd == "path" and len(args) == 1:
    print(record_path(args[0]))
elif cmd == "self":
    cmd_self(args)
elif cmd == "launch":
    cmd_launch(args)
elif cmd == "state":
    cmd_state(args)
else:
    die("usage: lineage.sh path|self|launch|state ... (see the header of this script)")
PY
